"""Safe removal of unused catalog entries (``--fix``)."""

from __future__ import annotations

import difflib
import tomllib
from pathlib import Path

from .catalog import Catalog, CatalogError, split_lines
from .rules import Finding


def remove_entries(catalog: Catalog, findings: list[Finding]) -> tuple[str, int]:
    """Return ``(new_text, removed_count)`` with fixable findings removed.

    The result is re-parsed with ``tomllib`` and must still be valid TOML and
    must not contain any of the removed aliases; otherwise ``CatalogError`` is
    raised and nothing is written.
    """
    doomed: set[tuple[str, str]] = {
        (f.kind, f.alias) for f in findings if f.fixable and f.file == catalog.path and f.kind and f.alias
    }
    lines = split_lines(catalog.text, keepends=True)
    drop: set[int] = set()
    removed = 0
    for kind, alias in doomed:
        entry = catalog.get(kind, alias)
        if entry is None:
            continue
        removed += 1
        for a, b in entry.spans:
            drop.update(range(a - 1, b))
    new_lines = [ln for i, ln in enumerate(lines) if i not in drop]
    new_text = "".join(new_lines)
    if new_text and not new_text.endswith("\n"):
        new_text += catalog.newline
    try:
        data = tomllib.loads(new_text)
    except tomllib.TOMLDecodeError as exc:
        raise CatalogError(catalog.path, f"--fix would produce invalid TOML: {exc}") from exc
    section = {"version": "versions", "library": "libraries", "plugin": "plugins", "bundle": "bundles"}
    for kind, alias in doomed:
        if alias in data.get(section[kind], {}):
            raise CatalogError(catalog.path, f"--fix could not cleanly remove '{alias}'")
    return new_text, removed


def unified_diff(path: Path, old: str, new: str, label: str) -> str:
    return "".join(
        difflib.unified_diff(
            split_lines(old, keepends=True), split_lines(new, keepends=True),
            fromfile=f"a/{label}", tofile=f"b/{label}",
        )
    )  # fmt: skip
