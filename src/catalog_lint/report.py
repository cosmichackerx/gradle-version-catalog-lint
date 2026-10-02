"""Output formats: text, json, github (workflow commands) and sarif."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import quote

from . import __version__
from .rules import RULES, Finding

URI = "https://github.com/cosmichackerx/gradle-version-catalog-lint"
_COLORS = {"error": "\033[31m", "warning": "\033[33m", "info": "\033[36m"}


def _rel(path: Path, base: Path) -> str:
    return os.path.relpath(path, base).replace(os.sep, "/")


def counts(findings: list[Finding]) -> dict[str, int]:
    return {s: sum(1 for f in findings if f.severity == s) for s in ("error", "warning", "info")}


def render_text(findings: list[Finding], base: Path, color: bool, notes: list[str]) -> str:
    out: list[str] = []
    by_file: dict[Path, list[Finding]] = {}
    for f in findings:
        by_file.setdefault(f.file, []).append(f)
    for file, items in sorted(by_file.items()):
        out.append(_rel(file, base))
        for f in sorted(items, key=lambda x: (x.line, x.rule)):
            sev = f"{_COLORS[f.severity]}{f.severity:<7}\033[0m" if color else f"{f.severity:<7}"
            out.append(f"  {f.line:>4}  {sev}  {f.rule:<24} {f.message}")
        out.append("")
    for n in notes:
        out.append(f"note: {n}")
    c = counts(findings)
    if findings:
        fixable = sum(1 for f in findings if f.fixable)
        out.append(
            f"{len(findings)} problem(s): {c['error']} error(s), {c['warning']} warning(s), {c['info']} info"
        )
        if fixable:
            out.append(f"{fixable} fixable with --fix (removes unused entries)")
    else:
        out.append("No problems found.")
    return "\n".join(out)


def render_json(findings: list[Finding], base: Path, notes: list[str], catalogs: list[str]) -> str:
    return json.dumps(
        {
            "schema": 1,
            "tool": {"name": "catalog-lint", "version": __version__},
            "catalogs": catalogs,
            "summary": counts(findings),
            "notes": notes,
            "findings": [f.to_dict(base) for f in findings],
        },
        indent=2,
    )


def _gh_escape(s: str) -> str:
    return s.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _gh_escape_property(s: str) -> str:
    return _gh_escape(s).replace(":", "%3A").replace(",", "%2C")


def render_github(findings: list[Finding], base: Path) -> str:
    level = {"error": "error", "warning": "warning", "info": "notice"}
    return "\n".join(
        f"::{level[f.severity]} file={_gh_escape_property(_rel(f.file, base))},line={f.line},title={f.rule}::"
        f"{_gh_escape(f.message)}"
        for f in findings
    )


def render_sarif(findings: list[Finding], base: Path) -> str:
    level = {"error": "error", "warning": "warning", "info": "note"}
    rules = [
        {
            "id": rid,
            "shortDescription": {"text": desc},
            "defaultConfiguration": {"level": level[sev]},
            "helpUri": f"{URI}#rules",
        }
        for rid, (sev, desc) in RULES.items()
    ]
    results = [
        {
            "ruleId": f.rule,
            "level": level[f.severity],
            "message": {"text": f.message},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": quote(_rel(f.file, base))},
                        "region": {"startLine": f.line},
                    }
                }
            ],
        }
        for f in findings
    ]
    doc = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "catalog-lint",
                        "version": __version__,
                        "informationUri": URI,
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(doc, indent=2)
