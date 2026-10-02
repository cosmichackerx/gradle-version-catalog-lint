"""Static discovery of catalogs and of every place a build references them."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .catalog import Catalog, CatalogError, default_name, parse_catalog

SKIP_DIRS = {
    ".git", ".gradle", ".idea", ".kotlin", "build", "out", "node_modules",
    ".venv", "venv", "__pycache__", ".tox", ".mypy_cache", ".ruff_cache",
}  # fmt: skip
SCRIPT_SUFFIXES = (".gradle", ".gradle.kts")
SOURCE_SUFFIXES = (".kt", ".java", ".groovy")
# Convention plugins live in ordinary source files; only look in the usual places.
SOURCE_DIR_HINTS = ("buildsrc", "build-logic", "build_logic", "buildlogic", "convention", "gradle")

_ACCESSOR_TAIL = r"([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)"
_LOOKUP_RE = re.compile(r"""\.(find(?:Library|Plugin|Version|Bundle))\(\s*["']([^"']+)["']\s*\)""")
_COORD_RE = re.compile(r"""["']([A-Za-z0-9_.\-]+):([A-Za-z0-9_.\-]+)(?::([^"'\s]*))?["']""")
_SETTINGS_FROM_RE = re.compile(
    r"""(?:create\(\s*["'](\w+)["']\s*\)|\b(\w+))\s*\{\s*from\(\s*files\(\s*["']([^"']+)["']"""
)
_PUBLISH_RE = re.compile(r"""version-catalog|`version-catalog`""")
_LOOKUP_KIND = {
    "findLibrary": "library",
    "findPlugin": "plugin",
    "findVersion": "version",
    "findBundle": "bundle",
}


def strip_comments(src: str) -> str:
    """Blank out ``//`` and ``/* */`` comments, keeping strings and line numbers."""
    out: list[str] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if src.startswith('"""', i) or src.startswith("'''", i):
            q = src[i : i + 3]
            j = src.find(q, i + 3)
            j = n if j == -1 else j + 3
            out.append(src[i:j])
            i = j
        elif c in "\"'":
            j = i + 1
            while j < n and src[j] != c and src[j] != "\n":
                if src[j] == "\\":
                    j += 1
                j += 1
            j = min(j + 1, n)
            out.append(src[i:j])
            i = j
        elif src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j == -1 else j
            out.append(" " * (j - i))
            i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j == -1 else j + 2
            out.append(re.sub(r"[^\n]", " ", src[i:j]))
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


@dataclass
class FileScan:
    path: Path
    accessors: dict[str, list[tuple[list[str], int]]] = field(default_factory=dict)
    lookups: list[tuple[str, str, int]] = field(default_factory=list)  # kind, name, line
    coords: list[tuple[str, str, str | None, int]] = field(default_factory=list)
    publishes_catalog: bool = False


def scan_text(path: Path, text: str, catalog_names: set[str]) -> FileScan:
    clean = strip_comments(text)
    scan = FileScan(path)

    def line_of(pos: int) -> int:
        return clean.count("\n", 0, pos) + 1

    for name in catalog_names:
        rx = re.compile(r"(?<![\w$])" + re.escape(name) + r"\." + _ACCESSOR_TAIL)
        for m in rx.finditer(clean):
            scan.accessors.setdefault(name, []).append((m.group(1).split("."), line_of(m.start())))
    for m in _LOOKUP_RE.finditer(clean):
        scan.lookups.append((_LOOKUP_KIND[m.group(1)], m.group(2), line_of(m.start())))
    for m in _COORD_RE.finditer(clean):
        scan.coords.append((m.group(1), m.group(2), m.group(3), line_of(m.start())))
    scan.publishes_catalog = bool(_PUBLISH_RE.search(clean))
    return scan


@dataclass
class Project:
    """Everything discovered below the paths given on the command line."""

    base: Path
    catalogs: list[Catalog]
    scopes: dict[Path, list[Path]]  # catalog path -> scope root dirs
    excluded: dict[Path, list[Path]]  # catalog path -> nested roots to ignore
    files: list[Path]
    errors: list[CatalogError]


def _walk(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for f in sorted(filenames):
            yield Path(dirpath) / f


def _wants_source(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path
    return any(hint in part.lower() for part in rel.parts[:-1] for hint in SOURCE_DIR_HINTS)


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def project_root_of(toml: Path) -> Path:
    return toml.parent.parent if toml.parent.name == "gradle" else toml.parent


def discover(paths: list[Path], exclude: list[str] | None = None) -> Project:
    import fnmatch

    # accept Windows-style separators and a leading "./" in exclude globs
    exclude = [e.replace("\\", "/").removeprefix("./") for e in (exclude or [])]
    base = (paths[0] if paths[0].is_dir() else paths[0].parent).resolve()
    tomls: list[Path] = []
    files: list[Path] = []
    settings: list[Path] = []
    for p in paths:
        p = p.resolve()
        if p.is_file():
            tomls.append(p)
            root = project_root_of(p)
            walk = _walk(root)
        else:
            walk = _walk(p)
            root = p
        for f in walk:
            rel = os.path.relpath(f, base).replace(os.sep, "/")
            if any(fnmatch.fnmatch(rel, pat) for pat in exclude):
                continue
            name = f.name
            if name.endswith(".versions.toml"):
                if f not in tomls:
                    tomls.append(f)
            elif name.endswith(SCRIPT_SUFFIXES) or (
                name.endswith(SOURCE_SUFFIXES) and _wants_source(f, root)
            ):
                if f not in files:
                    files.append(f)
                if name in ("settings.gradle", "settings.gradle.kts"):
                    settings.append(f)

    # catalog names: default from file name, overridden by settings.gradle imports
    names: dict[Path, list[str]] = {}
    extra_roots: dict[Path, list[Path]] = {}
    for s in settings:
        try:
            text = strip_comments(s.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        for m in _SETTINGS_FROM_RE.finditer(text):
            name = m.group(1) or m.group(2)
            if name in {"files", "from", "versionCatalogs", "dependencyResolutionManagement"}:
                continue
            target = (s.parent / m.group(3)).resolve()
            names.setdefault(target, [])
            if name not in names[target]:
                names[target].append(name)
            extra_roots.setdefault(target, []).append(s.parent)

    catalogs: list[Catalog] = []
    errors: list[CatalogError] = []
    scopes: dict[Path, list[Path]] = {}
    for t in tomls:
        try:
            cat = parse_catalog(t, names.get(t) or [default_name(t)])
        except CatalogError as exc:
            errors.append(exc)
            continue
        catalogs.append(cat)
        roots = [project_root_of(t)]
        for r in extra_roots.get(t, []):
            if r not in roots:
                roots.append(r)
        scopes[t] = roots

    excluded: dict[Path, list[Path]] = {}
    for cat in catalogs:
        ex: list[Path] = []
        for other in catalogs:
            if other.path == cat.path or not set(other.names) & set(cat.names):
                continue
            for r in scopes[other.path]:
                if any(r != mine and _is_under(r, mine) for mine in scopes[cat.path]):
                    ex.append(r)
        excluded[cat.path] = ex
    return Project(base, catalogs, scopes, excluded, files, errors)


def file_in_scope(project: Project, catalog: Catalog, file: Path) -> bool:
    if not any(_is_under(file, r) for r in project.scopes[catalog.path]):
        return False
    return not any(_is_under(file, r) for r in project.excluded[catalog.path])


def scan_files(project: Project) -> dict[Path, FileScan]:
    names = {n for c in project.catalogs for n in c.names}
    out: dict[Path, FileScan] = {}
    for f in project.files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        out[f] = scan_text(f, text, names)
    return out
