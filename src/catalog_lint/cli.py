"""Command line interface."""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
from pathlib import Path

from . import __version__
from .catalog import Catalog, CatalogError
from .config import CONFIG_NAME, Config, ConfigError, load_config
from .fixer import remove_entries, unified_diff
from .report import _rel, render_github, render_json, render_sarif, render_text
from .rules import RULES, SEVERITY_RANK, Finding, run_catalog_rules, run_global_rules
from .scanner import discover, scan_files

EXIT_OK, EXIT_FINDINGS, EXIT_USAGE = 0, 1, 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="catalog-lint",
        description="Lint Gradle version catalogs (libs.versions.toml): unused entries, "
        "dynamic/SNAPSHOT versions, hard-coded dependencies, duplicates and more.",
    )
    p.add_argument("paths", nargs="*", default=["."], help="project directories or *.versions.toml files")
    p.add_argument("--format", choices=["text", "json", "github", "sarif"], default="text")
    p.add_argument("--fail-on", choices=["error", "warning", "info", "never"], default=None,
                   help="lowest severity that makes the exit code 1 (default: warning)")  # fmt: skip
    p.add_argument("--fix", action="store_true", help="remove unused entries from the catalog files")
    p.add_argument("--dry-run", action="store_true", help="with --fix, print a diff instead of writing")
    p.add_argument(
        "--disable", action="append", default=[], metavar="RULE", help="disable a rule (repeatable)"
    )
    p.add_argument("--config", type=Path, help=f"config file (default: ./{CONFIG_NAME} if present)")
    p.add_argument("--no-color", action="store_true")
    p.add_argument("--list-rules", action="store_true", help="print all rules and exit")
    p.add_argument("--version", action="version", version=f"catalog-lint {__version__}")
    return p


def _fail(msg: str) -> int:
    print(f"catalog-lint: error: {msg}", file=sys.stderr)
    return EXIT_USAGE


def _make_output_robust() -> None:
    """Never crash on aliases/paths the console encoding cannot represent (e.g. cp1252 on Windows)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(OSError, ValueError):
                reconfigure(errors="replace")


def main(argv: list[str] | None = None) -> int:
    _make_output_robust()
    args = build_parser().parse_args(argv)

    if args.list_rules:
        for rid, (sev, desc) in RULES.items():
            print(f"{rid:<26} {sev:<8} {desc}")
        return EXIT_OK
    if args.dry_run and not args.fix:
        return _fail("--dry-run requires --fix")
    unknown = [r for r in args.disable if r not in RULES]
    if unknown:
        return _fail(f"unknown rule(s): {', '.join(unknown)} (see --list-rules)")

    paths = [Path(p) for p in args.paths]
    for p in paths:
        if not p.exists():
            return _fail(f"path does not exist: {p}")

    cfg = Config()
    cfg_path = args.config
    if cfg_path is None:
        root = paths[0] if paths[0].is_dir() else paths[0].parent
        for cand in (root / CONFIG_NAME, Path.cwd() / CONFIG_NAME):
            if cand.is_file():
                cfg_path = cand
                break
    try:
        if cfg_path is not None:
            cfg = load_config(cfg_path)
    except ConfigError as exc:
        return _fail(str(exc))

    project = discover(paths, cfg.exclude)
    for err in project.errors:
        print(f"catalog-lint: error: {err}", file=sys.stderr)
    if project.errors and not project.catalogs:
        return EXIT_USAGE
    if not project.catalogs:
        return _fail("no version catalog (*.versions.toml) found under: " + ", ".join(map(str, paths)))

    scans = scan_files(project)
    disabled = set(args.disable) | cfg.disable
    findings: list[Finding] = []
    notes: list[str] = []
    for cat in project.catalogs:
        f, n = run_catalog_rules(project, cat, scans, naming=cfg.naming)
        findings += f
        notes += n
    findings += run_global_rules(project, scans)
    findings = [f for f in findings if f.rule not in disabled and not cfg.ignored(f.kind, f.alias)]
    # stable, de-duplicated order
    uniq: dict[tuple, Finding] = {}
    for f in findings:
        uniq.setdefault((f.rule, str(f.file), f.line, f.alias, f.catalog), f)
    findings = sorted(uniq.values(), key=lambda f: (str(f.file), f.line, f.rule))

    if args.fix:
        # Compute every fix first so a failure leaves all files untouched.
        planned: list[tuple[Catalog, str, int]] = []
        for cat in project.catalogs:
            try:
                new_text, removed = remove_entries(cat, findings)
            except CatalogError as exc:
                return _fail(str(exc))
            if removed:
                planned.append((cat, new_text, removed))
        for cat, new_text, removed in planned:
            label = _rel(cat.path, project.base)
            if args.dry_run:
                print(unified_diff(cat.path, cat.text, new_text, label))
            else:
                # bytes: keep CRLF/LF exactly as found and keep a UTF-8 BOM if there was one
                cat.path.write_bytes((b"\xef\xbb\xbf" if cat.bom else b"") + new_text.encode("utf-8"))
                print(f"fixed {label}: removed {removed} unused entr{'y' if removed == 1 else 'ies'}",
                      file=sys.stderr)  # fmt: skip
        if not args.dry_run:
            # Re-lint so the report and exit code reflect the fixed state.
            return main([a for a in (argv if argv is not None else sys.argv[1:]) if a != "--fix"])
        return EXIT_OK

    color = not args.no_color and sys.stdout.isatty() and "NO_COLOR" not in os.environ
    if args.format == "text":
        out = render_text(findings, project.base, color, notes)
    elif args.format == "json":
        catalogs = [_rel(c.path, project.base) for c in project.catalogs]
        out = render_json(findings, project.base, notes, catalogs)
    elif args.format == "github":
        out = render_github(findings, project.base)
        for n in notes:
            print(f"note: {n}", file=sys.stderr)
    else:
        out = render_sarif(findings, project.base)
    if out:
        print(out)

    threshold = args.fail_on or cfg.fail_on or "warning"
    if project.errors and threshold != "never":
        return EXIT_USAGE  # an unreadable catalog must never look like a clean run
    if threshold != "never" and any(SEVERITY_RANK[f.severity] >= SEVERITY_RANK[threshold] for f in findings):
        return EXIT_FINDINGS
    return EXIT_OK
