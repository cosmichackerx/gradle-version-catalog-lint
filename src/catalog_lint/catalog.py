"""Parsing of ``*.versions.toml`` files, including line spans of every entry.

``tomllib`` gives us the data, but not *where* an entry lives. We need the
location to report precise findings and to remove unused entries safely, so a
small line scanner maps each alias to the lines it occupies.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SECTIONS = ("versions", "libraries", "plugins", "bundles")
KIND_OF_SECTION = {
    "versions": "version",
    "libraries": "library",
    "plugins": "plugin",
    "bundles": "bundle",
}

_KEY_RE = re.compile(r"""^\s*(?:"([^"]+)"|'([^']+)'|([A-Za-z0-9_\-.]+))\s*=""")
_HEADER_RE = re.compile(r"^\s*\[(?!\[)\s*(.+?)\s*\]\s*(?:#.*)?$")
_IGNORE_RE = re.compile(r"catalog-lint:\s*ignore(?:=([\w,\- ]+))?")
_TOKEN_RE = re.compile(r"\"[^\"]*\"|'[^']*'|[^.\s]+")


class CatalogError(Exception):
    """Raised when a catalog cannot be read or parsed."""

    def __init__(self, path: Path, message: str):
        super().__init__(f"{path}: {message}")
        self.path = path
        self.message = message


@dataclass
class Entry:
    kind: str  # version | library | plugin | bundle
    alias: str
    data: Any
    spans: list[tuple[int, int]]  # inclusive, 1-based line ranges
    ignored: set[str] = field(default_factory=set)  # rule ids, or {"*"}

    @property
    def line(self) -> int:
        return self.spans[0][0]

    @property
    def accessor(self) -> str:
        return normalize(self.alias)


@dataclass
class Catalog:
    path: Path
    names: list[str]
    text: str  # exact file contents (line endings preserved, BOM removed)
    entries: dict[str, dict[str, Entry]]
    bom: bool = False  # the file started with a UTF-8 byte order mark

    @property
    def name(self) -> str:
        return self.names[0]

    def get(self, kind: str, alias: str) -> Entry | None:
        return self.entries[kind].get(alias)

    @property
    def newline(self) -> str:
        return "\r\n" if "\r\n" in self.text else "\n"

    def all_entries(self) -> list[Entry]:
        return [e for kind in KIND_OF_SECTION.values() for e in self.entries[kind].values()]


def split_lines(text: str, keepends: bool = False) -> list[str]:
    """Split on ``\\n`` / ``\\r\\n`` only (``str.splitlines`` also breaks on U+2028, form feeds, ...).

    TOML defines a newline as LF or CRLF, so editors, ``tomllib`` and this tool must agree on it.
    """
    lines = re.findall(r"[^\n]*\n|[^\n]+", text)
    return lines if keepends else [ln.removesuffix("\n").removesuffix("\r") for ln in lines]


def read_toml_text(path: Path) -> tuple[str, bool]:
    """Read a TOML file as UTF-8 without translating newlines; returns ``(text, had_bom)``."""
    text = path.read_bytes().decode("utf-8")
    if text.startswith("\ufeff"):
        return text[1:], True
    return text, False


def normalize(alias: str) -> str:
    """Gradle maps ``-`` and ``_`` in aliases to ``.`` in type-safe accessors."""
    return alias.replace("-", ".").replace("_", ".")


def default_name(path: Path) -> str:
    name = path.name
    for suffix in (".versions.toml", ".toml"):
        if name.endswith(suffix):
            return name[: -len(suffix)] or "libs"
    return name


# --------------------------------------------------------------------------- #
# data helpers
# --------------------------------------------------------------------------- #


def library_module(data: Any) -> tuple[str, str] | None:
    """Return ``(group, name)`` for a library definition, if determinable."""
    if isinstance(data, str):
        parts = data.split(":")
        return (parts[0], parts[1]) if len(parts) >= 2 else None
    if isinstance(data, dict):
        module = data.get("module")
        if isinstance(module, str) and ":" in module:
            group, name = module.split(":")[:2]
            return group, name
        group, name = data.get("group"), data.get("name")
        if isinstance(group, str) and isinstance(name, str):
            return group, name
    return None


def version_ref(data: Any) -> str | None:
    """The ``[versions]`` key a library/plugin points at, if any."""
    if isinstance(data, dict):
        v = data.get("version")
        if isinstance(v, dict) and isinstance(v.get("ref"), str):
            return v["ref"]
    return None


def version_literals(kind: str, data: Any) -> list[str]:
    """All literal version strings declared by an entry (for dynamic checks)."""
    out: list[str] = []

    def rich(v: Any) -> None:
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, dict):
            for key in ("require", "strictly", "prefer"):
                val = v.get(key)
                # a strictly range such as "[1.0, 2.0[" is a deliberate bound, not a dynamic version
                if isinstance(val, str) and not (key == "strictly" and val[:1] in "[("):
                    out.append(val)

    if kind == "version":
        rich(data)
    elif kind == "library":
        if isinstance(data, str):
            parts = data.split(":")
            if len(parts) >= 3:
                out.append(parts[2])
        elif isinstance(data, dict):
            rich(data.get("version"))
            module = data.get("module")
            if isinstance(module, str) and module.count(":") >= 2:
                out.append(module.split(":")[2])
    elif kind == "plugin":
        if isinstance(data, str):
            parts = data.split(":")
            if len(parts) >= 2:
                out.append(parts[1])
        elif isinstance(data, dict):
            rich(data.get("version"))
    return out


# --------------------------------------------------------------------------- #
# line scanning
# --------------------------------------------------------------------------- #


def _depth_delta(line: str) -> int:
    """Net bracket depth change of a line, ignoring strings and comments."""
    depth = 0
    quote = ""
    i = 0
    while i < len(line):
        c = line[i]
        if quote:
            if c == "\\" and quote == '"':
                i += 1
            elif c == quote:
                quote = ""
        elif c in "\"'":
            quote = c
        elif c == "#":
            break
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
        i += 1
    return depth


def _resolve_alias(raw: str, keys: dict[str, Any]) -> str | None:
    """Map a (possibly dotted) key such as ``foo.module`` onto alias ``foo``."""
    if raw in keys:
        return raw
    best = None
    for alias in keys:
        if raw.startswith(alias + ".") and (best is None or len(alias) > len(best)):
            best = alias
    return best


def _split_header(inner: str) -> list[str]:
    return [t.strip("\"'") for t in _TOKEN_RE.findall(inner)]


def _comment_ignores(line: str) -> set[str]:
    m = _IGNORE_RE.search(line[line.find("#") :]) if "#" in line else None
    if not m:
        return set()
    if m.group(1):
        return {r.strip() for r in m.group(1).split(",") if r.strip()}
    return {"*"}


def parse_catalog(path: Path, names: list[str] | None = None) -> Catalog:
    try:
        text, bom = read_toml_text(path)
    except (OSError, UnicodeDecodeError) as exc:
        raise CatalogError(path, f"cannot read file: {exc}") from exc
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise CatalogError(path, f"invalid TOML: {exc}") from exc

    for section in SECTIONS:
        if section in data and not isinstance(data[section], dict):
            raise CatalogError(path, f"[{section}] must be a table")

    lines = split_lines(text)
    boundaries: list[tuple[int, str | None, str | None]] = []  # (line idx, section, alias)
    section: str | None = None
    depth = 0
    in_alias_table = False  # inside ``[libraries.foo]``: its keys belong to ``foo``, not to new aliases
    for idx, line in enumerate(lines):
        if depth == 0:
            stripped = line.strip()
            header = _HEADER_RE.match(line) if stripped.startswith("[") else None
            if header:
                parts = _split_header(header.group(1))
                section = parts[0] if parts and parts[0] in SECTIONS else None
                alias = None
                if section and len(parts) > 1:
                    alias = _resolve_alias(".".join(parts[1:]), data.get(section, {}))
                in_alias_table = alias is not None
                boundaries.append((idx, section, alias))
            elif in_alias_table:
                pass
            elif section and (m := _KEY_RE.match(line)):
                raw = m.group(1) or m.group(2) or m.group(3)
                alias = _resolve_alias(raw, data.get(section, {}))
                boundaries.append((idx, section, alias))
        depth = max(0, depth + _depth_delta(line))

    spans: dict[tuple[str, str], list[tuple[int, int]]] = {}
    for n, (idx, sec, alias) in enumerate(boundaries):
        if sec is None or alias is None:
            continue
        end = (boundaries[n + 1][0] if n + 1 < len(boundaries) else len(lines)) - 1
        while end > idx and (not lines[end].strip() or lines[end].lstrip().startswith("#")):
            end -= 1
        spans.setdefault((sec, alias), []).append((idx + 1, end + 1))

    entries: dict[str, dict[str, Entry]] = {k: {} for k in KIND_OF_SECTION.values()}
    for sec in SECTIONS:
        for alias, value in (data.get(sec) or {}).items():
            sp = spans.get((sec, alias))
            if not sp:
                continue
            ignored: set[str] = set()
            first = sp[0][0]
            if first >= 2 and lines[first - 2].lstrip().startswith("#"):
                ignored |= _comment_ignores(lines[first - 2])
            for a, b in sp:
                for ln in range(a, b + 1):
                    ignored |= _comment_ignores(lines[ln - 1])
            kind = KIND_OF_SECTION[sec]
            entries[kind][alias] = Entry(kind, alias, value, sp, ignored)

    return Catalog(path=path, names=names or [default_name(path)], text=text, entries=entries, bom=bom)
