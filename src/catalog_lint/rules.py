"""Lint rules. Each finding is tied to a file and line so CI can annotate it."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .catalog import Catalog, Entry, library_module, normalize, version_literals, version_ref
from .scanner import FileScan, Project, file_in_scope

ERROR, WARNING, INFO = "error", "warning", "info"
SEVERITY_RANK = {INFO: 0, WARNING: 1, ERROR: 2}

RULES: dict[str, tuple[str, str]] = {
    "naming-convention": (INFO, "Opt-in alias naming style and reserved-name checks."),
    "unused-library": (WARNING, "Library alias is never referenced by any build script."),
    "unused-plugin": (WARNING, "Plugin alias is never referenced by any build script."),
    "unused-version": (WARNING, "Version is not used by any live library, plugin or script."),
    "unused-bundle": (WARNING, "Bundle is never referenced by any build script."),
    "undefined-version-ref": (ERROR, "version.ref points to a version that does not exist."),
    "undefined-bundle-member": (ERROR, "Bundle lists a library alias that does not exist."),
    "duplicate-library": (WARNING, "Two aliases point at the same group:name."),
    "dynamic-version": (WARNING, "Dynamic version (+, latest.*, open range) breaks reproducibility."),
    "snapshot-version": (WARNING, "SNAPSHOT version in a catalog makes builds non-reproducible."),
    "hardcoded-dependency": (WARNING, "Hard-coded coordinates that already exist in the catalog."),
    "unknown-lookup": (ERROR, "findLibrary/findPlugin/... refers to an alias that does not exist."),
}  # fmt: skip

_FIXABLE = {"unused-library", "unused-plugin", "unused-version", "unused-bundle"}


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: Path
    line: int
    catalog: str | None = None
    kind: str | None = None
    alias: str | None = None

    @property
    def fixable(self) -> bool:
        return self.rule in _FIXABLE

    def to_dict(self, base: Path) -> dict:
        import os

        return {
            "rule": self.rule,
            "severity": self.severity,
            "message": self.message,
            "file": os.path.relpath(self.file, base).replace(os.sep, "/"),
            "line": self.line,
            "catalog": self.catalog,
            "kind": self.kind,
            "alias": self.alias,
            "fixable": self.fixable,
        }


@dataclass
class Usage:
    libraries: set[str] = field(default_factory=set)  # aliases
    plugins: set[str] = field(default_factory=set)
    versions: set[str] = field(default_factory=set)
    bundles: set[str] = field(default_factory=set)


def _index(catalog: Catalog, kind: str) -> dict[str, str]:
    return {e.accessor: a for a, e in catalog.entries[kind].items()}


def _resolve(tokens: list[str], index: dict[str, str]) -> str | None:
    for n in range(len(tokens), 0, -1):
        key = ".".join(tokens[:n])
        if key in index:
            return index[key]
    return None


def collect_usage(project: Project, catalog: Catalog, scans: dict[Path, FileScan]) -> Usage:
    usage = Usage()
    idx = {k: _index(catalog, k) for k in ("library", "plugin", "version", "bundle")}
    for path, scan in scans.items():
        if not file_in_scope(project, catalog, path):
            continue
        for name in catalog.names:
            for tokens, _line in scan.accessors.get(name, []):
                head = tokens[0] if tokens else ""
                if head == "versions" and len(tokens) > 1:
                    a = _resolve(tokens[1:], idx["version"])
                    if a:
                        usage.versions.add(a)
                elif head == "plugins" and len(tokens) > 1:
                    a = _resolve(tokens[1:], idx["plugin"])
                    if a:
                        usage.plugins.add(a)
                elif head == "bundles" and len(tokens) > 1:
                    a = _resolve(tokens[1:], idx["bundle"])
                    if a:
                        usage.bundles.add(a)
                else:
                    a = _resolve(tokens, idx["library"])
                    if a:
                        usage.libraries.add(a)
        for kind, raw, _line in scan.lookups:
            a = idx[kind].get(normalize(raw))
            if a:
                getattr(usage, {"library": "libraries", "plugin": "plugins",
                                "version": "versions", "bundle": "bundles"}[kind]).add(a)  # fmt: skip
    return usage


def _is_dynamic(v: str) -> bool:
    v = v.strip()
    return v.endswith("+") or v.startswith("latest.") or (v[:1] in "[(" and "," in v)


def _loc(catalog: Catalog, e: Entry) -> tuple[Path, int]:
    return catalog.path, e.line


def run_catalog_rules(
    project: Project, catalog: Catalog, scans: dict[Path, FileScan], *, naming: str | None = None
) -> tuple[list[Finding], list[str]]:
    findings: list[Finding] = []
    notes: list[str] = []
    cname = catalog.name

    def add(rule: str, e: Entry, msg: str) -> None:
        if "*" in e.ignored or rule in e.ignored:
            return
        findings.append(Finding(rule, RULES[rule][0], msg, catalog.path, e.line, cname, e.kind, e.alias))

    in_scope = [s for p, s in scans.items() if file_in_scope(project, catalog, p)]
    published = any(s.publishes_catalog for s in in_scope)
    check_unused = bool(in_scope) and not published
    if not in_scope:
        notes.append(f"{catalog.path.name}: no Gradle build files found in scope; unused-* rules skipped")
    elif published:
        notes.append(
            f"{catalog.path.name}: applies the version-catalog plugin (published catalog); "
            "unused-* rules skipped"
        )

    libs, plugins = catalog.entries["library"], catalog.entries["plugin"]
    versions, bundles = catalog.entries["version"], catalog.entries["bundle"]

    # Opt-in only: aliases affect generated accessors, so never rename them automatically.
    if naming is not None:
        patterns = {
            "kebab": r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*",
            "snake": r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*",
            "camel": r"[a-z][A-Za-z0-9]*",
        }
        for e in catalog.all_entries():
            segments = e.accessor.split(".")
            reserved = e.accessor in {"extensions", "convention"} or "class" in segments
            reserved = reserved or (e.kind == "library" and segments[0] in {"bundles", "versions", "plugins"})
            if reserved:
                add("naming-convention", e, f"{e.kind} '{e.alias}' uses a Gradle reserved alias segment")
            elif re.fullmatch(patterns[naming], e.alias) is None:
                add("naming-convention", e, f"{e.kind} '{e.alias}' does not follow {naming} naming")

    # --- structural errors -------------------------------------------------- #
    for e in list(libs.values()) + list(plugins.values()):
        ref = version_ref(e.data)
        if ref is not None and ref not in versions:
            add("undefined-version-ref", e, f"{e.kind} '{e.alias}' uses undefined version ref '{ref}'")
    for b in bundles.values():
        members = b.data if isinstance(b.data, list) else []
        for m in members:
            if m not in libs:
                add("undefined-bundle-member", b, f"bundle '{b.alias}' references unknown library '{m}'")

    # --- duplicates ---------------------------------------------------------- #
    by_module: dict[tuple[str, str], list[Entry]] = {}
    for e in libs.values():
        mod = library_module(e.data)
        if mod:
            by_module.setdefault(mod, []).append(e)
    for (group, name), group_entries in by_module.items():
        if len(group_entries) > 1:
            aliases = ", ".join(x.alias for x in group_entries)
            for e in group_entries:
                add("duplicate-library", e, f"'{e.alias}' duplicates {group}:{name} (also: {aliases})")

    # --- dynamic / snapshot versions ---------------------------------------- #
    for e in catalog.all_entries():
        if e.kind in ("bundle",):
            continue
        for v in version_literals(e.kind, e.data):
            if v.endswith("-SNAPSHOT"):
                add("snapshot-version", e, f"{e.kind} '{e.alias}' uses SNAPSHOT version '{v}'")
            elif _is_dynamic(v):
                add("dynamic-version", e, f"{e.kind} '{e.alias}' uses dynamic version '{v}'")

    # --- hard-coded coordinates --------------------------------------------- #
    modules = {m: [x.alias for x in es] for m, es in by_module.items()}
    seen: set[tuple[Path, int, str]] = set()
    for path, scan in scans.items():
        if not file_in_scope(project, catalog, path):
            continue
        for group, name, _ver, line in scan.coords:
            aliases = modules.get((group, name))
            if not aliases or (path, line, aliases[0]) in seen:
                continue
            seen.add((path, line, aliases[0]))
            hint = f"{cname}.{normalize(aliases[0])}"
            findings.append(
                Finding(
                    "hardcoded-dependency", WARNING,
                    f"'{group}:{name}' is already in the catalog; use {hint}",
                    path, line, cname, "library", aliases[0],
                )
            )  # fmt: skip

    if not check_unused:
        return findings, notes

    # --- unused entries ------------------------------------------------------ #
    usage = collect_usage(project, catalog, scans)
    used_bundles = set(usage.bundles)
    live_libs = set(usage.libraries)
    for b in used_bundles:
        for m in bundles[b].data if isinstance(bundles[b].data, list) else []:
            live_libs.add(m)
    for a, e in bundles.items():
        if a not in used_bundles:
            add("unused-bundle", e, f"bundle '{a}' is never used ({cname}.bundles.{e.accessor})")
    live_plugins = set(usage.plugins)
    for a, e in libs.items():
        if a not in live_libs:
            add("unused-library", e, f"library '{a}' is never used ({cname}.{e.accessor})")
    for a, e in plugins.items():
        if a not in live_plugins:
            add("unused-plugin", e, f"plugin '{a}' is never used ({cname}.plugins.{e.accessor})")
    live_versions = set(usage.versions)
    for a in live_libs:
        r = version_ref(libs[a].data) if a in libs else None
        if r:
            live_versions.add(r)
    for a in live_plugins:
        r = version_ref(plugins[a].data) if a in plugins else None
        if r:
            live_versions.add(r)
    for a, e in versions.items():
        if a not in live_versions:
            add("unused-version", e, f"version '{a}' is not used by any live entry or script")
    return findings, notes


def run_global_rules(project: Project, scans: dict[Path, FileScan]) -> list[Finding]:
    """Rules that look at scripts across all catalogs."""
    findings: list[Finding] = []
    if not project.catalogs:
        return findings
    known = {k: set() for k in ("library", "plugin", "version", "bundle")}
    for c in project.catalogs:
        for kind in known:
            known[kind] |= {e.accessor for e in c.entries[kind].values()}
    for path, scan in scans.items():
        for kind, raw, line in scan.lookups:
            if normalize(raw) not in known[kind]:
                findings.append(
                    Finding("unknown-lookup", ERROR,
                            f"no {kind} alias '{raw}' in any version catalog",
                            path, line, None, kind, raw)
                )  # fmt: skip
    return findings
