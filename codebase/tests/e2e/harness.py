"""Shared pieces of the end-to-end runs: nested agents, fixtures, owner moves.

A nested ``claude -p`` (or ``opencode run``) talks to the temporary hub of the
``hub`` fixture; Playwright (the ``owner`` fixture) plays the person. Nothing
here touches the real hub, its state or its config.
"""

from __future__ import annotations

import json
import math
import os
import re
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from helpers import PLUGIN_DIR, REPO_DIR

LONGRUN = Path(__file__).parent / "fixtures" / "longrun.py"
MCP_PREFIX = "mcp__plugin_agent-canvas_agent-canvas"
DOCS_INSTALL = REPO_DIR / "docs" / "install.md"


def documented_allow_rules() -> list[str]:
    """
    Return the allow rules exactly as ``docs/install.md`` tells the owner.

    Page writes, the CLI and the plugin's MCP tools. Reading them from the
    document means a wrong rule there makes the scenarios fail on denials.
    """
    for block in re.findall(r"```json\n(.*?)```", DOCS_INSTALL.read_text(), re.S):
        rules = json.loads(block).get("permissions", {}).get("allow", [])
        if any(rule.startswith("mcp__") for rule in rules):
            return rules
    raise AssertionError("docs/install.md has no allow rules with the MCP tools")


BASE_ALLOW = documented_allow_rules()
# Scenarios that run a fixture add only that command and a few read-only helpers.
FIXTURE_ALLOW = [
    "Bash(longrun:*)",
    "Bash(kill:*)",
    "Bash(cat:*)",
    "Bash(tail:*)",
    "Bash(sleep:*)",
    "Bash(ls:*)",
]


def make_bin(directory: Path, with_longrun: bool = False) -> Path:
    """
    Create a directory with an ``agent-canvas`` command running this checkout.

    With ``with_longrun`` it also holds ``longrun``, the progress fixture, so
    that one narrow permission rule (``Bash(longrun:*)``) covers it.
    """
    directory.mkdir(exist_ok=True)
    scripts = {"agent-canvas": f'exec "{sys.executable}" -m agent_canvas.cli "$@"'}
    if with_longrun:
        scripts["longrun"] = f'exec "{sys.executable}" "{LONGRUN}" "$@"'
    for name, body in scripts.items():
        wrapper = directory / name
        wrapper.write_text(f"#!/bin/sh\n{body}\n")
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
    return directory


def hub_environment(hub, bin_dir: Path) -> dict[str, str]:  # noqa: ANN001
    """Return an environment that points the agent's commands at the test hub."""
    environment = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "AGENT_CANVAS_PORT": str(hub.port),
        "AGENT_CANVAS_STATE_DIR": str(hub.state_dir),
        "AGENT_CANVAS_CONFIG_DIR": str(hub.config_dir),
        "AGENT_CANVAS_WINDOW_COMMAND": "true",
    }
    for name in ("AGENT_CANVAS_SESSION", "AGENT_CANVAS_PROJECT", "AGENT_CANVAS_AGENT"):
        environment.pop(name, None)  # the SessionStart hook must provide them
    return environment


def parse_stream(path: Path) -> list[dict]:
    """Return the JSON objects of a stream-json file (partial lines skipped)."""
    found = []
    for line in path.read_text().splitlines():
        try:
            found.append(json.loads(line))
        except ValueError:
            continue
    return found


def terminate_group(process: subprocess.Popen | None) -> None:
    """
    Terminate a nested agent's whole process group.

    The agents start in their own session, so a lingering MCP server or watch
    cannot outlive the test and restart a hub on the freed port.
    """
    if process is None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=20)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


class ClaudeRun:
    """
    A nested ``claude -p --plugin-dir plugin/`` in the default permission mode.

    Parameters
    ----------
    hub : HubHandle
        The test hub; the agent works in its project directory.
    tmp_path : Path
        Where the settings, the stream files and the wrapper commands go.
    model : str
        Claude Code model alias (``haiku``, then ``sonnet`` for the retry).
    name : str
        Distinguishes several runs in one test.
    extra_allow : list[str]
        Permission rules added to the base rules (a fixture command).
    """

    def __init__(
        self,
        hub,  # noqa: ANN001
        tmp_path: Path,
        model: str,
        name: str = "claude",
        extra_allow: list[str] | None = None,
    ) -> None:
        self.hub, self.model, self.name = hub, model, name
        self.dir = tmp_path / name
        self.dir.mkdir()
        bin_dir = make_bin(tmp_path / f"bin-{name}", with_longrun=bool(extra_allow))
        self.environment = hub_environment(hub, bin_dir)
        self.settings = self.dir / "settings.json"
        allow = [*BASE_ALLOW, *(extra_allow or [])]
        self.settings.write_text(json.dumps({"permissions": {"allow": allow}}))
        self.process: subprocess.Popen | None = None
        self.stream = self.dir / "stream.jsonl"
        self.command: list[str] = []
        self.started = 0.0

    def start(
        self, prompt: str, session_id: str | None = None, resume: str | None = None
    ) -> None:
        """Start the agent; stdin is ``/dev/null``. ``resume`` continues a session."""
        self.stream = self.dir / f"stream-{len(list(self.dir.glob('stream-*')))}.jsonl"
        command = [
            "claude", "-p", prompt, "--model", self.model,
            "--plugin-dir", str(PLUGIN_DIR), "--settings", str(self.settings),
            "--output-format", "stream-json", "--verbose", "--include-hook-events",
        ]  # fmt: skip
        command += ["--resume", resume] if resume else ["--session-id", session_id]
        self.command = command
        out = self.stream.open("w")
        err = (self.dir / "stderr.txt").open("a")
        self.process = subprocess.Popen(
            command, cwd=self.hub.project_dir, env=self.environment,
            stdin=subprocess.DEVNULL, stdout=out, stderr=err, text=True,
            start_new_session=True,
        )  # fmt: skip
        self.started = time.monotonic()

    @property
    def running(self) -> bool:
        """Whether the process is still alive."""
        return self.process is not None and self.process.poll() is None

    def events(self) -> list[dict]:
        """All stream-json events of the current run."""
        return parse_stream(self.stream)

    def results(self) -> list[dict]:
        """The ``result`` events (one per turn; a Monitor line adds one)."""
        return [e for e in self.events() if e.get("type") == "result"]

    def final(self) -> str:
        """Text of the last ``result`` event."""
        results = self.results()
        return str(results[-1].get("result")) if results else "(no result event)"

    def tools_used(self) -> list[str]:
        """Names of the tools the agent called, in order."""
        return [
            block["name"]
            for event in self.events() if event.get("type") == "assistant"
            for block in event.get("message", {}).get("content", [])
            if block.get("type") == "tool_use"
        ]  # fmt: skip

    def denials(self) -> list[dict]:
        """Permission denials reported by the results."""
        return [d for r in self.results() for d in r.get("permission_denials", [])]

    def init_tools(self) -> list[str]:
        """Tool names Claude Code listed in its ``init`` event."""
        init = next((e for e in self.events() if e.get("subtype") == "init"), {})
        return list(init.get("tools", []))

    def hooks_seen(self) -> set[str]:
        """Names of the hook events that fired."""
        return {
            e.get("hook_event")
            for e in self.events() if e.get("subtype") == "hook_started"
        }  # fmt: skip

    def wait(self, condition: Callable[[], bool], seconds: float, tick=None) -> bool:  # noqa: ANN001
        """Poll ``condition`` while the agent runs; ``tick`` keeps Playwright alive."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if condition():
                return True
            if not self.running:
                return condition()
            tick() if tick else time.sleep(0.2)
        return False

    def finish(self, seconds: float = 150) -> None:
        """Let the agent end by itself, else terminate it (a Monitor may linger)."""
        self.wait(lambda: not self.running, seconds)
        self.stop()

    def stop(self) -> None:
        """Terminate the agent and everything it started (MCP server, watches)."""
        terminate_group(self.process)

    def report(self) -> str:
        """One printable block: result lines, tools, denials, hooks."""
        lines = [r.get("result") for r in self.results()]
        return (
            f"[{self.name}/{self.model}] RESULTS: {lines}\n"
            f"  TOOLS USED: {self.tools_used()}\n  DENIALS: {self.denials()}\n"
            f"  HOOKS: {sorted(h for h in self.hooks_seen() if h)}"
        )


def session_events(hub, session_id: str) -> list[dict]:  # noqa: ANN001
    """All events of a session as the hub logged them."""
    return hub.on_loop(lambda: hub.state.events.all(session_id))


def delivery_routes(hub, session_id: str) -> dict[str, str]:
    """Map event id to the ``via`` of its ``delivered`` record in events.jsonl."""
    log = hub.project_dir / hub.project_dir_name / session_id / "events.jsonl"
    routes: dict[str, str] = {}
    if log.is_file():
        for line in log.read_text().splitlines():
            record = json.loads(line)
            if record.get("record") == "delivered":
                routes[record["id"]] = record["via"]
    return routes


def pump(owner, ms: int = 200) -> None:  # noqa: ANN001
    """Let the owner's browser run for ``ms`` milliseconds."""
    owner.page.wait_for_timeout(ms)


def frame_has(owner, selector: str, count: int = 1) -> bool:  # noqa: ANN001
    """Whether the shown page has ``count`` elements matching ``selector``."""
    try:
        return owner.frame.locator(selector).count() >= count
    except Exception:  # noqa: BLE001 - the frame may not exist yet or is reloading
        return False


def wait_listening(
    owner, run: ClaudeRun, session_id: str, seconds: float = 120
) -> bool:  # noqa: ANN001
    """Wait until a listener (watch, wait_for_feedback) or an open ask is attached."""
    hub = owner.hub

    def attached() -> bool:
        return hub.listening(session_id) or any(
            a["waiting"] for a in hub.open_asks(session_id)
        )

    return run.wait(attached, seconds, tick=lambda: pump(owner))


def send_note(owner, text: str, delivery: str = "now") -> None:  # noqa: ANN001
    """Type ``text`` into the draft bar and send it (or queue it for later)."""
    owner.page.fill("#draft-message", text)
    owner.page.click("#send-button" if delivery == "now" else "#next-button")


def open_first_tab(owner) -> bool:  # noqa: ANN001
    """Click the first session's tab unless one is open; True once a tab is active."""
    try:
        if owner.page.locator(".tab.active").count():
            return True
        tab = owner.page.locator(".tab[data-session] .tab-main")
        if tab.count():
            tab.first.click()
        return owner.page.locator(".tab.active").count() > 0
    except Exception:  # noqa: BLE001 - the shell may still be loading
        return False


def peak_point(owner, x: float) -> list[float]:  # noqa: ANN001
    """Frame pixels of the highest point of the first plot.

    Only points within 10 data units of ``x`` count.
    """
    return owner.frame.evaluate(
        """(tx) => {
            const gd = document.querySelector('canvas-plot')
              .shadowRoot.querySelector('.plot');
            let best = null;
            for (const trace of gd._fullData) {
              (trace.x || []).forEach((px, i) => {
                if (Math.abs(px - tx) <= 10 && (best === null || trace.y[i] > best))
                  best = trace.y[i];
              });
            }
            const full = gd._fullLayout, box = gd.getBoundingClientRect();
            return [box.x + full.xaxis._offset + full.xaxis.l2p(tx),
                    box.y + full.yaxis._offset + full.yaxis.l2p(best)];
        }""",
        x,
    )


def comment_mode_on(owner) -> None:  # noqa: ANN001
    """
    Press ``C`` until comment mode is on and the layout has settled.

    The comment panel opens and narrows the frame, so frame positions are
    measured only after this call.
    """
    page = owner.page
    if not page.evaluate("document.body.classList.contains('commenting')"):
        page.locator("body").press("c")
    page.wait_for_function("document.body.classList.contains('commenting')")
    page.wait_for_timeout(300)


def comment_rectangle(
    owner,
    start: tuple[float, float],
    end: tuple[float, float],
    text: str,  # noqa: ANN001
) -> None:
    """
    Make a rectangle comment as the owner does: ``C``, drag, type, Enter.

    ``start`` and ``end`` are frame pixels; returns once the comment is saved
    (the box has closed and the panel lists it).
    """
    page = owner.page
    comment_mode_on(owner)
    frame_box = page.locator("#frame").bounding_box()
    mouse = page.mouse
    mouse.move(frame_box["x"] + start[0], frame_box["y"] + start[1])
    mouse.down()
    mouse.move(frame_box["x"] + end[0], frame_box["y"] + end[1], steps=6)
    mouse.up()
    page.wait_for_selector(".cbox textarea")
    page.fill(".cbox textarea", text)
    page.press(".cbox textarea", "Enter")
    page.wait_for_selector(".cbox", state="detached")


def pick_kind(owner, kind: str) -> None:  # noqa: ANN001
    """Press the toolbar button of a comment kind and wait until the layer is on."""
    owner.page.click(f"#{kind}-button")
    owner.page.wait_for_function("document.body.classList.contains('commenting')")
    owner.frame.wait_for_function(
        f"document.documentElement.getAttribute('data-ac-commenting') === '{kind}'"
    )
    owner.frame.wait_for_function("!!window.agentCanvas.commentLayer")
    owner.page.wait_for_timeout(300)  # the comment panel opens and narrows the frame


def lasso_path(
    owner,  # noqa: ANN001
    centre: tuple[float, float],
    radius_x: float,
    radius_y: float,
    text: str,
    points: int = 14,
) -> None:
    """
    Draw a closed lasso (an ellipse) as the owner does, type ``text`` and save.

    ``centre`` is in frame pixels, measured after ``pick_kind``.
    """
    page = owner.page
    box = page.locator("#frame").bounding_box()
    ring = [
        (
            box["x"] + centre[0] + radius_x * math.cos(2 * math.pi * i / points),
            box["y"] + centre[1] + radius_y * math.sin(2 * math.pi * i / points),
        )
        for i in range(points)
    ]
    page.mouse.move(*ring[0])
    page.mouse.down()
    for x, y in ring[1:] + ring[:1]:
        page.mouse.move(x, y)
    page.mouse.up()
    page.wait_for_selector(".cbox textarea")
    page.fill(".cbox textarea", text)
    page.press(".cbox textarea", "Enter")
    page.wait_for_selector(".cbox", state="detached")


def comment_lasso_around(owner, x: float, radius: float = 45, text: str = "") -> dict:  # noqa: ANN001
    """
    Comment a lasso around the curve of the first plot at data position ``x``.

    The lasso is a circle centred on the highest point of any trace within 10
    data units of ``x`` (the peak). Returns that centre, in frame pixels.
    """
    pick_kind(owner, "lasso")  # the frame narrows: measure after it
    point = peak_point(owner, x)
    lasso_path(owner, (point[0], point[1]), radius, radius, text or "why this peak?")
    return {"centre": point, "radius": radius}


def home_entry(hub, session_id: str) -> dict | None:  # noqa: ANN001
    """The session's entry in the hub's home snapshot, or None."""
    snapshot = httpx.get(f"{hub.base_url}/api/home", headers=hub.key_headers).json()
    return next((s for s in snapshot["sessions"] if s["id"] == session_id), None)


def result_with(run: ClaudeRun, *keywords: str) -> str | None:
    """Return the last ``result`` text that contains any of ``keywords``."""
    found = None
    for result in run.results():
        text = str(result.get("result"))
        if any(word.lower() in text.lower() for word in keywords):
            found = text
    return found


def wait_reply(
    owner,  # noqa: ANN001
    run: ClaudeRun,
    session_id: str,
    keywords: tuple[str, ...],
    seconds: float = 150,
    settle: float = 0,
) -> str:
    """
    Wait for the agent's answer to a send and return the final ``result`` text.

    First waits until the hub logged a delivery, then for a ``result`` that
    contains one of ``keywords``, counting only results that came after the
    delivery (a Monitor wake-up produces its own result, and the turn that
    started the watch also ends with one). With ``settle`` it then waits that
    many seconds without a new result and returns the last matching one.
    Returns the last result when no result matches.
    """
    hub = owner.hub

    def delivered() -> bool:
        return any(e["state"] == "delivered" for e in session_events(hub, session_id))

    run.wait(delivered, seconds, tick=lambda: pump(owner))
    seen = len(run.results())  # earlier turns ("I am listening") do not count

    def answered() -> bool:
        return any(
            any(word.lower() in str(r.get("result")).lower() for word in keywords)
            for r in run.results()[seen:]
        )

    run.wait(answered, seconds, tick=lambda: pump(owner))
    quiet_since, count = time.monotonic(), len(run.results())
    while run.running and time.monotonic() - quiet_since < settle:
        pump(owner)  # a status turn can end after the send; let the answer follow
        if len(run.results()) != count:
            quiet_since, count = time.monotonic(), len(run.results())
    matching = [
        str(r.get("result"))
        for r in run.results()[seen:]
        if any(word.lower() in str(r.get("result")).lower() for word in keywords)
    ]
    return matching[-1] if matching else run.final()


OPENCODE_MODEL = "opencode/big-pickle"
OPENCODE_DOCS = REPO_DIR / "docs" / "opencode.md"


def documented_opencode_setup() -> tuple[str, str]:
    """Return (``opencode.json`` text, ``AGENTS.md`` text) from docs/opencode.md."""
    text = OPENCODE_DOCS.read_text()
    config = next(
        block
        for block in re.findall(r"```json\n(.*?)```", text, re.S)
        if '"mcp"' in block
    )
    instructions = re.search(r"```markdown\n(.*?)```", text, re.S).group(1)
    return config, instructions


class OpencodeRun:
    """
    A nested ``opencode run --model opencode/big-pickle`` set up as documented.

    The project gets the ``opencode.json`` and the ``AGENTS.md`` block of
    ``docs/opencode.md``. A private server (``--standalone``) and temporary XDG
    directories keep it away from the owner's background service, config and
    data; only the (read-only) free-model catalogue comes from the network.
    """

    def __init__(self, hub, tmp_path: Path) -> None:  # noqa: ANN001
        config, instructions = documented_opencode_setup()
        (hub.project_dir / "opencode.json").write_text(config)
        (hub.project_dir / "AGENTS.md").write_text(instructions)
        self.hub, self.dir = hub, tmp_path / "opencode"
        self.dir.mkdir()
        self.environment = hub_environment(hub, make_bin(tmp_path / "bin-opencode"))
        defaults = {"config": ".config", "data": ".local/share",
                    "state": ".local/state", "cache": ".cache"}  # fmt: skip
        for kind, default in defaults.items():
            # A mise shim (how opencode is installed on work) finds its tools
            # through these folders: keep mise's own pointing at the real ones.
            name = kind.upper()
            real = os.environ.get(f"XDG_{name}_HOME", str(Path.home() / default))
            self.environment.setdefault(f"MISE_{name}_DIR", f"{real}/mise")
            (self.dir / kind).mkdir()
            self.environment[f"XDG_{kind.upper()}_HOME"] = str(self.dir / kind)
        self.stdout = self.dir / "stdout.jsonl"
        self.stderr = self.dir / "stderr.txt"
        self.process: subprocess.Popen | None = None

    def start(self, prompt: str) -> None:
        """Start the run; stdin is ``/dev/null``."""
        command = [
            "opencode", "run", "--standalone", "--format", "json",
            "--model", OPENCODE_MODEL, prompt,
        ]  # fmt: skip
        self.process = subprocess.Popen(
            command, cwd=self.hub.project_dir, env=self.environment,
            stdin=subprocess.DEVNULL, stdout=self.stdout.open("w"),
            stderr=self.stderr.open("w"), text=True, start_new_session=True,
        )  # fmt: skip

    @property
    def running(self) -> bool:
        """Whether the process is still alive."""
        return self.process is not None and self.process.poll() is None

    def events(self) -> list[dict]:
        """The JSON lines opencode printed."""
        return parse_stream(self.stdout)

    def texts(self) -> list[str]:
        """The assistant's text parts, oldest first."""
        return [
            e["part"]["text"]
            for e in self.events()
            if e.get("type") == "text" and "text" in e.get("part", {})
        ]

    def tools_used(self) -> list[str]:
        """Names of the tool parts opencode reported."""
        return [
            str(e["part"].get("tool"))
            for e in self.events()
            if e.get("type") == "tool_use"
        ]

    def final(self) -> str:
        """The last text part."""
        texts = self.texts()
        return texts[-1] if texts else "(no text)"

    def failure(self) -> str:
        """Why the model run failed, from stderr and error events, or ``""``."""
        errors = [
            str(e.get("error", e))
            for e in self.events()
            if "error" in e.get("type", "")
        ]
        code = None if self.process is None else self.process.poll()
        stderr = self.stderr.read_text()[-500:] if self.stderr.exists() else ""
        failed = errors or (code not in (None, 0))
        return f"exit {code}; errors {errors}; stderr {stderr!r}" if failed else ""

    def wait(self, condition: Callable[[], bool], seconds: float, tick=None) -> bool:  # noqa: ANN001
        """Poll ``condition`` while the run lives; ``tick`` keeps Playwright alive."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if condition():
                return True
            if not self.running:
                return condition()
            tick() if tick else time.sleep(0.2)
        return False

    def stop(self) -> None:
        """Terminate the agent and everything it started."""
        terminate_group(self.process)


def wait_command_items(events: list[dict], command: str) -> dict[str, dict]:
    """Items (by id) of the JSON that the Bash call running ``command`` printed.

    Only the result of a Bash ``tool_use`` whose command contains ``command``
    counts, matched by ``tool_use_id``; ``{}`` when there is none or it is not JSON.
    """
    calls = {
        block["id"]
        for event in events
        if event.get("type") == "assistant"
        for block in event.get("message", {}).get("content", [])
        if block.get("type") == "tool_use"
        and block.get("name") == "Bash"
        and command in str(block["input"].get("command"))
    }
    for event in events:
        content = event.get("message", {}).get("content", [])
        for block in content if isinstance(content, list) else []:
            if (
                block.get("type") != "tool_result"
                or block.get("tool_use_id") not in calls
            ):
                continue
            body = block.get("content")
            if isinstance(body, list):
                body = "".join(part.get("text", "") for part in body)
            try:
                return {item["id"]: item for item in json.loads(body)["items"]}
            except (ValueError, KeyError, TypeError):
                continue
    return {}
