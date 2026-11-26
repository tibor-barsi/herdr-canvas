"""Access key, login tokens and credential checks (SEC-02 to SEC-05)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import stat
import threading
from collections.abc import Callable
from pathlib import Path

from agent_canvas.client import health_proof

KEY_HEADER = "X-Agent-Canvas-Key"
COOKIE_NAME = "agent_canvas_session"
LOGIN_TOKEN_SECONDS = 60.0


def cookie_name(port: int) -> str:
    """
    Return the owner cookie's name for a hub port.

    Cookies ignore ports, so two hubs on 127.0.0.1 (or a dev server) would
    overwrite each other's cookie under one name (SEC-10).
    """
    return f"{COOKIE_NAME}_{port}"


class KeyFileError(Exception):
    """Raised when the access key file cannot be used."""


def load_or_create_key(state_dir: Path) -> str:
    """
    Return the access key, creating it on first start.

    Parameters
    ----------
    state_dir : pathlib.Path
        State directory; created with mode 0700 if missing.

    Returns
    -------
    str
        The 32-byte URL-safe base64 key.

    Raises
    ------
    KeyFileError
        If the key file is readable by group or others, or is empty. The
        message names the file.
    """
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_dir.chmod(0o700)
    key_file = state_dir / "key"
    if not key_file.exists():
        key = secrets.token_urlsafe(32)
        _write_private(key_file, key + "\n")
        return key
    if key_file.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise KeyFileError(
            f"access key file {key_file} is readable by group or others; "
            f"run: chmod 600 {key_file}"
        )
    key = key_file.read_text().strip()
    if not key:
        raise KeyFileError(f"access key file {key_file} is empty")
    return key


def _write_private(path: Path, text: str) -> None:
    """Create ``path`` with mode 0600 from the start (no permission window)."""
    import os

    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(text)


class Credentials:
    """
    Check keys and cookies, and issue single-use login tokens.

    Parameters
    ----------
    key : str
        The access key.
    clock : Callable[[], float]
        Monotonic time source; injectable so tests can move time (SEC-04).
    """

    def __init__(self, key: str, clock: Callable[[], float]) -> None:
        self._key = key
        self._clock = clock
        # The cookie is derived from the key so that an open window survives
        # a hub restart without storing session state.
        self._cookie = hmac.new(key.encode(), b"shell-cookie-v1", hashlib.sha256)
        self._login_tokens: dict[str, float] = {}
        self._lock = threading.Lock()

    @property
    def pool_tag(self) -> str:
        """The TAG of this hub's pools: 8 hex of SHA-256 over the key (A-1003)."""
        return hashlib.sha256(f"{self._key}\npool-tag-v1".encode()).hexdigest()[:8]

    @property
    def cookie_value(self) -> str:
        """Value of the owner cookie."""
        return self._cookie.hexdigest()

    def key_ok(self, candidate: str | None) -> bool:
        """Compare ``candidate`` with the access key in constant time."""
        return _equal(candidate, self._key)

    def health_proof(self, port: int, challenge: str) -> str:
        """Answer a ``/health`` challenge with the key (SEC-13)."""
        return health_proof(self._key, port, challenge)

    def cookie_ok(self, candidate: str | None) -> bool:
        """Compare ``candidate`` with the owner cookie in constant time."""
        return _equal(candidate, self.cookie_value)

    def new_login_token(self) -> str:
        """Issue a single-use login token valid for 60 s."""
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._login_tokens[token] = self._clock() + LOGIN_TOKEN_SECONDS
        return token

    def consume_login_token(self, token: str | None) -> bool:
        """Return True once for a fresh token, False for reused or expired ones."""
        if not token:
            return False
        with self._lock:
            now = self._clock()
            self._login_tokens = {
                t: until for t, until in self._login_tokens.items() if until > now
            }
            return self._login_tokens.pop(token, None) is not None


def _equal(candidate: str | None, expected: str) -> bool:
    """Constant-time string comparison that tolerates ``None``."""
    if candidate is None:
        return False
    return hmac.compare_digest(candidate.encode(), expected.encode())
