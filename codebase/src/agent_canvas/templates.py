"""Page templates for ``agent-canvas new`` (KIT-02, KIT-03).

Each template is a complete HTML page that links the design kit and uses the
ready-made blocks, with obvious ``(replace)`` placeholders. :func:`write_template`
is the single place that writes one into a session folder.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_canvas.drafts import draft_name_for
from agent_canvas.paths_safe import validate_page_name

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


class TemplateError(ValueError):
    """A template request that cannot be carried out (unknown template, bad name)."""


class TemplateExistsError(TemplateError):
    """The target page exists and ``force`` was not given."""


@dataclass(frozen=True)
class Template:
    """
    One page template.

    Parameters
    ----------
    name : str
        Name used with ``--template``; also the file stem in the package.
    description : str
        One line saying what the page is for.
    assets : dict[str, str]
        Extra files the page refers to, as ``{file name in the session folder:
        file name in the package}``. They are written only when missing.
    """

    name: str
    description: str
    assets: dict[str, str]

    def read_text(self) -> str:
        """
        Return the HTML of the template.

        Returns
        -------
        str
            The page source.
        """
        return (TEMPLATE_DIR / f"{self.name}.html").read_text(encoding="utf-8")


TEMPLATES: dict[str, Template] = {
    t.name: t
    for t in (
        Template("compare", "Compare options: cards, a table and a question.", {}),
        Template("results", "Report results: number tiles, plot and table.", {}),
        Template("run", "Status of a long run: progress and a Stop button.", {}),
        Template(
            "geometry",
            "Review a geometry: 3D model with markers (adds a sample part.stl).",
            {"part.stl": "part-sample.stl"},
        ),
        Template(
            "cards",
            "Compare designs: a key-numbers table and one card per design with "
            "picture, 3D model and plot (adds sample files).",
            {
                "design-a.png": "design-a.png",
                "design-b.png": "design-b.png",
                "design-c.png": "design-c.png",
                "part.stl": "part-sample.stl",
            },
        ),
    )
}


def page_name_for(name: str) -> str:
    """
    Turn ``NAME`` into a valid page file name.

    Parameters
    ----------
    name : str
        A page name with or without the ``.html`` suffix.

    Returns
    -------
    str
        The name ending in ``.html``.

    Raises
    ------
    agent_canvas.paths_safe.UnsafePathError
        If the name is not one plain file name.
    TemplateError
        If the name is a dotfile, which is never shown as a page.
    """
    page = name if name.endswith(".html") else f"{name}.html"
    validate_page_name(page)
    if page.startswith("."):
        raise TemplateError(f"Invalid page name {name!r}: dotfiles are not pages.")
    return page


def write_template(folder: Path, page: str, template: str, force: bool = False) -> Path:
    """
    Write template ``template`` as ``folder/page``.

    Parameters
    ----------
    folder : pathlib.Path
        Directory to write into (the session folder).
    page : str
        Target file name, already checked by :func:`page_name_for`.
    template : str
        A key of :data:`TEMPLATES`.
    force : bool, optional
        Overwrite an existing page. Default is False.

    Returns
    -------
    pathlib.Path
        The page that was written.

    Raises
    ------
    TemplateError
        For an unknown template.
    TemplateExistsError
        For an existing page without ``force``.
    """
    if template not in TEMPLATES:
        known = ", ".join(TEMPLATES)
        raise TemplateError(f"Unknown template {template!r}. Choose one of: {known}.")
    chosen = TEMPLATES[template]
    target = folder / page
    if target.exists() and not force:
        raise TemplateExistsError(f"{page} already exists; pass force to overwrite it.")
    target.write_text(chosen.read_text(), encoding="utf-8")
    for asset, source in chosen.assets.items():
        if not (folder / asset).exists():
            data = (TEMPLATE_DIR / source).read_bytes()
            (folder / asset).write_bytes(data)
    return target


def describe_templates() -> dict[str, list[dict[str, str]]]:
    """
    List the templates for ``new --list`` and the ``new_page`` tool.

    Returns
    -------
    dict[str, list[dict[str, str]]]
        ``{"templates": [{"name", "description"}, ...]}``.
    """
    return {
        "templates": [
            {"name": t.name, "description": t.description} for t in TEMPLATES.values()
        ]
    }


def new_page_result(
    folder: Path, name: str, template: str, force: bool = False, draft: bool = True
) -> dict[str, str | bool]:
    """
    Validate ``name``, write the template and describe the result.

    Shared by the CLI and the MCP tool; it turns every refusal into a
    :class:`~agent_canvas.output.CliError`.

    Parameters
    ----------
    folder : pathlib.Path
        The session folder.
    name : str
        Page name with or without ``.html``.
    template : str
        A key of :data:`TEMPLATES`.
    force : bool, optional
        Overwrite an existing file. Default is False.
    draft : bool, optional
        Write the private draft ``NAME.draft.html`` instead of ``NAME.html``
        (DRAFT-04). Default is True: a template is a starting point full of
        placeholders that the owner should not see.

    Returns
    -------
    dict[str, str | bool]
        ``{"path", "page", "template", "draft"}``; ``page`` is the file name
        that was written.

    Raises
    ------
    agent_canvas.output.CliError
        ``usage`` for a bad name or template, ``failed`` for an existing page.
    """
    from agent_canvas.output import CliError
    from agent_canvas.paths_safe import UnsafePathError

    try:
        page = page_name_for(name)
        if draft:
            page = draft_name_for(page)
        path = write_template(folder, page, template, force)
    except TemplateExistsError as error:
        raise CliError("failed", str(error)) from error
    except (UnsafePathError, TemplateError) as error:
        raise CliError("usage", str(error)) from error
    return {"path": str(path), "page": page, "template": template, "draft": draft}
