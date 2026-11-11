"""MkDocs hook that publishes the docs for coding agents and LLM tools.

It writes, next to the HTML site:

- ``llms.txt``: a short summary and an index of every page (https://llmstxt.org/);
- a Markdown copy of every page, at the page's source path (``how-to/x.md``);
- ``llms-full.txt``: every page in navigation order, in one file.

Snippet includes are expanded. ``:::`` API directives become a compact
Markdown summary of the public names: signatures, docstrings and public
members, read from the source with griffe (no imports, no optional extras).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import griffe  # type: ignore[import-not-found]  # installed with the [docs] extra

SUMMARY = (
    "Pytest plugin that tests chatbots and tool-using agents for prompt injection, "
    "data leaks and unauthorized tool use. Agent results come from what a controlled "
    "harness recorded the agent doing, not from the agent's own text. Runs locally, "
    "including against Ollama, vLLM and llama.cpp models with no API key."
)

NOTES = """\
Facts for coding agents:

- Install with `pip install pytest-wardenbot`. Extras: `[mcp]` (agent suite harness),
  `[langgraph]`, `[claude-agent]`, `[openai]`, `[anthropic]`, `[langchain]`, `[judge]`.
- Chatbot suite: provide a `chatbot` fixture (an adapter), then run
  `pytest --pyargs pytest_wardenbot.tests`.
- Agent suite: provide `agent_target` and `agent_observer` fixtures, then run
  `pytest --pyargs pytest_wardenbot.agent_tests --wardenbot-agent-required`.
- Import only from the public modules listed on the stability page; other module
  paths are internal.
- Agent outcomes are `violated`, `resisted`, `inconclusive`, `unsupported` and `error`;
  the reason codes are explained on the agent outcomes page.
"""

OPTIONAL_SECTIONS = {"About", "Changelog"}
_SNIPPET = re.compile(r'^(?P<indent>[ \t]*)--8<-- "(?P<path>[^"]+)"[ \t]*$', re.M)
_DIRECTIVE = re.compile(r"^::: (?P<id>[\w.]+)[ \t]*\n(?P<options>(?:[ \t]+.*\n|[ \t]*\n)*)", re.M)

_markdown: dict[str, str] = {}
_titles: dict[str, str] = {}
_descriptions: dict[str, str] = {}
_nav: Any = None
_package: Any = None


def on_config(config: Any) -> Any:
    _markdown.clear()
    _titles.clear()
    _descriptions.clear()
    return config


def on_nav(nav: Any, config: Any, files: Any) -> Any:
    global _nav
    _nav = nav
    return nav


def on_page_markdown(markdown: str, page: Any, config: Any, files: Any) -> str:
    root = Path(config["config_file_path"]).parent
    text = _SNIPPET.sub(lambda match: _include(root, match), markdown)
    _markdown[page.file.src_uri] = _DIRECTIVE.sub(lambda match: _api(root, match), text)
    if isinstance(page.meta.get("description"), str):
        _descriptions[page.file.src_uri] = page.meta["description"]
    return markdown


def on_page_context(context: Any, page: Any, config: Any, nav: Any) -> Any:
    _titles[page.file.src_uri] = page.title or page.file.src_uri
    return context


def on_post_build(config: Any) -> None:
    site = Path(config["site_dir"])
    base = config["site_url"] or ""
    if base and not base.endswith("/"):
        base += "/"
    for src_uri, text in _markdown.items():
        target = site / src_uri
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text.rstrip() + "\n", encoding="utf-8")

    sections: list[tuple[str, list[str]]] = []
    for item in _nav.items if _nav else []:
        pages = list(_pages(item))
        if item.is_section or item.title in OPTIONAL_SECTIONS:
            sections.append((item.title, pages))
        elif sections and not sections[-1][0].endswith(("started", "More")):
            sections.append(("More", pages))
        elif sections:
            sections[-1][1].extend(pages)
        else:
            sections.append(("Get started", pages))

    index = [f"# {config['site_name']}", "", f"> {SUMMARY}", "", NOTES]
    full = [f"# {config['site_name']}", "", f"> {SUMMARY}", "", NOTES]
    optional: list[str] = []
    for title, pages in sections:
        lines = [f"- [{_titles.get(src, src)}]({base}{src}): {_describe(src)}" for src in pages]
        if title in OPTIONAL_SECTIONS:
            optional.extend(lines)
            continue
        index += [f"## {title}", "", *lines, ""]
        for src in pages:
            if src in _markdown:
                full += [f"<!-- {base}{src} -->", "", _markdown[src].strip(), ""]
    if optional:
        index += ["## Optional", "", *optional, ""]
    (site / "llms.txt").write_text("\n".join(index).rstrip() + "\n", encoding="utf-8")
    (site / "llms-full.txt").write_text("\n".join(full).rstrip() + "\n", encoding="utf-8")


def _pages(item: Any):
    if item.is_page:
        yield item.file.src_uri
    for child in getattr(item, "children", None) or ():
        yield from _pages(child)


def _include(root: Path, match: re.Match[str]) -> str:
    text = (root / match["path"]).read_text(encoding="utf-8").rstrip("\n")
    return "\n".join(match["indent"] + line if line else line for line in text.splitlines())


def _describe(src: str) -> str:
    """The page's ``description``, or the first sentence of its first paragraph."""
    if src in _descriptions:
        return _descriptions[src]
    text = _markdown.get(src, "")
    text = re.sub(r"^```.*?^```", "", text, flags=re.S | re.M)
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph or paragraph.startswith(("#", "|", "-", "!", ">", "<", "*", "[!")):
            continue
        plain = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", " ".join(paragraph.split()))
        sentence = re.split(r"(?<=[.!?])\s", plain, maxsplit=1)[0]
        return sentence if len(sentence) <= 200 else sentence[:197].rstrip() + "..."
    return ""


# -- API summary --------------------------------------------------------------------


def _api(root: Path, match: re.Match[str]) -> str:
    global _package
    if _package is None:
        _package = griffe.load(
            "pytest_wardenbot", search_paths=[str(root / "src")], resolve_aliases=True
        )
    identifier = match["id"]
    options = match["options"]
    level_option = re.search(r"heading_level: (\d)", options)
    level = int(level_option[1]) if level_option else 2
    obj = _package[identifier.removeprefix("pytest_wardenbot.")] if "." in identifier else _package
    if obj.is_alias:
        obj = obj.final_target
    if not obj.is_module:
        return _render(obj, obj.name, level) + "\n"
    members = re.findall(r'"(\w+)"', options) if "members:" in options else None
    names = members if members is not None else list(obj.exports or ())
    blocks = []
    for name in names:
        if name.startswith("__"):
            continue
        member = obj[name]
        if member.is_alias:
            member = member.final_target
        blocks.append(_render(member, name, level))
    return "\n".join(blocks) + "\n"


def _render(obj: Any, name: str, level: int) -> str:
    lines = [f"{'#' * level} `{name}`", ""]
    if obj.is_class:
        bases = ", ".join(str(base) for base in obj.bases)
        if _has_init(obj) and not bases.endswith("Enum"):
            signature = f"class {name}({_parameters(obj.parameters)})"
        else:
            signature = f"class {name}({bases})" if bases else f"class {name}"
        lines += ["```python", signature, "```", ""]
    elif obj.is_function:
        prefix = "async def" if "async" in obj.labels else "def"
        returns = f" -> {obj.returns}" if obj.returns else ""
        signature = f"{prefix} {name}({_parameters(obj.parameters)}){returns}"
        lines += ["```python", signature, "```", ""]
    elif obj.is_attribute and obj.annotation is not None:
        lines += [f"`{name}: {obj.annotation}`", ""]
    if obj.docstring:
        lines += [obj.docstring.value.strip(), ""]
    if obj.is_class:
        lines += _members(obj)
    return "\n".join(lines)


def _has_init(cls: Any) -> bool:
    try:
        return any(parameter.name not in {"self", "cls"} for parameter in cls.parameters)
    except Exception:
        return False


def _members(cls: Any) -> list[str]:
    enum = any(str(base).endswith("Enum") for base in cls.bases)
    rows = []
    for member_name, member in cls.members.items():
        if member_name.startswith("_") or member.is_alias:
            continue
        summary = member.docstring.value.strip().splitlines()[0] if member.docstring else ""
        if enum and member.is_attribute:
            rows.append(f"- `{member_name} = {member.value}`")
        elif member.is_function:
            prefix = "async " if "async" in member.labels else ""
            returns = f" -> {member.returns}" if member.returns else ""
            if "property" in member.labels:
                signature = f"{member_name}{returns.replace(' -> ', ': ')}"
            else:
                signature = f"{prefix}{member_name}({_parameters(member.parameters)}){returns}"
            rows.append(f"- `{signature}`" + (f": {summary}" if summary else ""))
        elif member.is_attribute and summary:
            rows.append(f"- `{member_name}`: {summary}")
    return [*rows, ""] if rows else []


def _parameters(parameters: Any) -> str:
    parts: list[str] = []
    keyword_only_marked = False
    previous_kind = None
    for parameter in parameters:
        if parameter.name in {"self", "cls"}:
            continue
        kind = parameter.kind.value
        if previous_kind == "positional-only" and kind != "positional-only":
            parts.append("/")
        if kind == "keyword-only" and not keyword_only_marked:
            parts.append("*")
            keyword_only_marked = True
        text = parameter.name
        if kind == "variadic positional":
            text, keyword_only_marked = f"*{text}", True
        elif kind == "variadic keyword":
            text = f"**{text}"
        if parameter.annotation is not None:
            text += f": {parameter.annotation}"
        if parameter.default is not None:
            text += f" = {parameter.default}" if parameter.annotation else f"={parameter.default}"
        parts.append(text)
        previous_kind = kind
    return ", ".join(parts)
