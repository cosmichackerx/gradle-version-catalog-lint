"""Optional ``.catalog-lint.toml`` configuration."""

from __future__ import annotations

import fnmatch
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .rules import RULES, SEVERITY_RANK

CONFIG_NAME = ".catalog-lint.toml"


class ConfigError(Exception):
    pass


@dataclass
class Config:
    disable: set[str] = field(default_factory=set)
    ignore: list[str] = field(default_factory=list)  # "alias" or "kind:alias" globs
    exclude: list[str] = field(default_factory=list)
    fail_on: str | None = None

    def ignored(self, kind: str | None, alias: str | None) -> bool:
        if alias is None:
            return False
        for pat in self.ignore:
            if ":" in pat:
                k, a = pat.split(":", 1)
                if k in (kind, (kind or "") + "s", (kind or "")[:-1] + "ies") and fnmatch.fnmatch(alias, a):
                    return True
            elif fnmatch.fnmatch(alias, pat):
                return True
        return False


def _str_list(data: dict, key: str, path: Path) -> list[str]:
    value = data.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{path}: '{key}' must be a list of strings")
    return value


def load_config(path: Path) -> Config:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML: {exc}") from exc
    unknown = set(data) - {"disable", "ignore", "exclude", "fail-on"}
    if unknown:
        raise ConfigError(f"{path}: unknown option(s): {', '.join(sorted(unknown))}")
    disable = set(_str_list(data, "disable", path))
    bad = disable - set(RULES)
    if bad:
        raise ConfigError(f"{path}: unknown rule(s) in 'disable': {', '.join(sorted(bad))}")
    fail_on = data.get("fail-on")
    if fail_on is not None and fail_on not in (*SEVERITY_RANK, "never"):
        raise ConfigError(f"{path}: 'fail-on' must be one of error, warning, info, never")
    return Config(disable, _str_list(data, "ignore", path), _str_list(data, "exclude", path), fail_on)
