"""action.yml must meet the GitHub Marketplace rules (name, <=125 char description, branding)."""

import re
from pathlib import Path

ACTION = (Path(__file__).resolve().parent.parent / "action.yml").read_text(encoding="utf-8")
COLORS = {"white", "black", "yellow", "blue", "green", "orange", "red", "purple", "gray-dark"}


def top(key: str) -> str:
    m = re.search(rf"^{key}:\s*(.+)$", ACTION, re.M)
    assert m, f"{key} missing"
    return m.group(1).strip().strip("'\"")


def test_name_and_description():
    assert 0 < len(top("name")) <= 60
    assert len(top("description")) <= 125, len(top("description"))


def test_branding():
    m = re.search(r"^branding:\s*\n\s+icon:\s*(\S+)\s*\n\s+color:\s*(\S+)", ACTION, re.M)
    assert m, "branding block missing"
    assert m.group(1)
    assert m.group(2) in COLORS


def test_is_composite():
    assert re.search(r"^runs:\s*\n\s+using:\s*['\"]?composite", ACTION, re.M)
