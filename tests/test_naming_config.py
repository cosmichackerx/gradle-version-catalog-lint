import json

import pytest

from catalog_lint.cli import main
from catalog_lint.config import ConfigError, load_config


@pytest.mark.parametrize("value", ['"other"', "42", '["kebab"]'])
def test_invalid_naming_option(tmp_path, value):
    path = tmp_path / ".catalog-lint.toml"
    path.write_text(f"naming = {value}\n")
    with pytest.raises(ConfigError, match="naming.*kebab, camel, snake"):
        load_config(path)


def test_cli_configuration_and_suppression(make_project, capsys):
    root = make_project(
        {
            "settings.gradle.kts": "",
            "build.gradle.kts": "",
            "gradle/libs.versions.toml": '[libraries]\nBadName = "g:n:1"\n',
            ".catalog-lint.toml": 'naming = "kebab"\ndisable = ["unused-library"]\n',
        }
    )
    assert main([str(root), "--format", "json", "--fail-on", "info"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["findings"][0]["rule"] == "naming-convention"
    for suppression in [
        'disable = ["unused-library", "naming-convention"]',
        'disable = ["unused-library"]\nignore = ["library:BadName"]',
    ]:
        (root / ".catalog-lint.toml").write_text('naming = "kebab"\n' + suppression + "\n")
        assert main([str(root), "--format", "json", "--fail-on", "info"]) == 0
        assert json.loads(capsys.readouterr().out)["findings"] == []
