"""Edge cases: Windows paths, CRLF line endings, BOMs and unusual (but valid) TOML."""

import json

import pytest

from catalog_lint.catalog import parse_catalog, split_lines
from catalog_lint.cli import main
from catalog_lint.scanner import discover

BUILD = "dependencies { implementation(libs.live) }\n"
CATALOG_LF = '[versions]\nunused = "1"\nk = "1"\n\n[libraries]\nlive = { module = "g:live", version.ref = "k" }\ndead = "g:dead:1"\n'


def write(path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def project(tmp_path, catalog: bytes, build: str = BUILD):
    write(tmp_path / "gradle" / "libs.versions.toml", catalog)
    write(tmp_path / "build.gradle.kts", build.encode())
    return tmp_path


# --- line endings / BOM --------------------------------------------------------------------


def test_split_lines_only_breaks_on_lf_and_crlf():
    assert split_lines("a\r\nb\nc\u2028d\x85e\n") == ["a", "b", "c\u2028d\x85e"]
    assert split_lines("a\r\nb", keepends=True) == ["a\r\n", "b"]
    assert split_lines("") == []


def test_fix_preserves_crlf(tmp_path, capsys):
    root = project(tmp_path, CATALOG_LF.replace("\n", "\r\n").encode())
    assert main([str(root), "--fix"]) == 0
    data = (root / "gradle" / "libs.versions.toml").read_bytes()
    assert b"dead" not in data and b"unused" not in data
    assert data.count(b"\r\n") == data.count(b"\n") > 0  # no bare LF introduced
    capsys.readouterr()


def test_fix_preserves_lf(tmp_path, capsys):
    root = project(tmp_path, CATALOG_LF.encode())
    assert main([str(root), "--fix"]) == 0
    assert b"\r" not in (root / "gradle" / "libs.versions.toml").read_bytes()
    capsys.readouterr()


def test_fix_keeps_bom_and_appends_crlf_when_missing_final_newline(tmp_path, capsys):
    text = '[libraries]\r\nlive = "g:live:1"\r\ndead = "g:dead:1"'
    root = project(tmp_path, b"\xef\xbb\xbf" + text.encode())
    assert main([str(root), "--fix"]) == 0
    data = (root / "gradle" / "libs.versions.toml").read_bytes()
    assert data.startswith(b"\xef\xbb\xbf[libraries]")
    assert data.endswith(b'"g:live:1"\r\n')
    capsys.readouterr()


def test_bom_catalog_is_parsed(tmp_path):
    p = tmp_path / "libs.versions.toml"
    p.write_bytes(b'\xef\xbb\xbf[libraries]\nx = "g:n:1"\n')
    cat = parse_catalog(p)
    assert cat.bom and "x" in cat.entries["library"]


def test_crlf_line_numbers_and_multiline_bundle(tmp_path, capsys):
    toml = '[libraries]\r\na = "g:a:1"\r\nb = "g:b:1"\r\n\r\n[bundles]\r\nbb = [\r\n  "a",\r\n  "b",\r\n]\r\n'
    root = project(tmp_path, toml.encode(), "libs.a\n")
    assert main([str(root), "--format", "json"]) == 1
    findings = json.loads(capsys.readouterr().out)["findings"]
    assert {(f["rule"], f["line"]) for f in findings} == {("unused-bundle", 6), ("unused-library", 3)}


def test_unicode_line_separators_do_not_shift_line_numbers(tmp_path):
    p = tmp_path / "libs.versions.toml"
    p.write_text('[versions]\n# note\u2028 and a \u0085 here\nk = "1"\n', encoding="utf-8")
    assert parse_catalog(p).entries["version"]["k"].line == 3


def test_invalid_utf8_catalog_reports_error(tmp_path, capsys):
    root = project(tmp_path, b'[libraries]\nx = "\xff\xfe"\n')
    assert main([str(root)]) == 2
    assert "cannot read file" in capsys.readouterr().err


# --- unusual TOML ---------------------------------------------------------------------------


def test_table_style_entries_are_removed_whole(tmp_path, capsys):
    toml = (
        '[versions]\nk = "1"\n\n[libraries]\nused = "g:u:1"\n\n'
        '[libraries.tbl]\nmodule = "g:tbl"\nversion.ref = "k"\n\n'
        '[libraries.other]\nmodule = "g:other"\nversion = "2"\n'
    )
    root = project(tmp_path, toml.encode(), "libs.used\n")
    assert main([str(root), "--fix"]) == 0
    out = (root / "gradle" / "libs.versions.toml").read_text(encoding="utf-8")
    assert "tbl" not in out and "other" not in out and "used" in out
    capsys.readouterr()


def test_quoted_dotted_and_literal_string_keys(tmp_path, capsys):
    toml = '[libraries]\n"a.b" = \'g:ab:1\'\n\'c-d\' = "g:cd:1"\nplain.module = "g:p"\nplain.version = "1"\n'
    root = project(tmp_path, toml.encode(), "libs.a.b\nlibs.c.d\nlibs.plain\n")
    assert main([str(root)]) == 0
    capsys.readouterr()


def test_multiline_array_with_brackets_in_strings_and_comments(tmp_path, capsys):
    toml = (
        '[libraries]\na = "g:a:1"\nb = "g:b:1"\n\n[bundles]\n'
        'bb = [\n  "a", # ] looks like the end\n  "b", # [libraries]\n]\n'
    )
    root = project(tmp_path, toml.encode(), "libs.bundles.bb\n")
    assert main([str(root)]) == 0
    capsys.readouterr()


def test_inline_ignore_comment_survives_crlf(tmp_path, capsys):
    toml = '[libraries]\r\nlive = "g:live:1"\r\ndead = "g:dead:1" # catalog-lint: ignore=unused-library\r\n'
    root = project(tmp_path, toml.encode())
    assert main([str(root)]) == 0
    capsys.readouterr()


def test_strictly_range_is_not_dynamic_but_open_require_range_is(tmp_path, capsys):
    toml = (
        '[versions]\nok = { strictly = "[1.0, 2.0[", prefer = "1.5" }\nbad = { require = "[1.0, 2.0[" }\n'
        'plus = "1.2.+"\nlatest = "latest.release"\n[libraries]\n'
        'x = { module = "g:x", version.ref = "ok" }\ny = { module = "g:y", version.ref = "bad" }\n'
        'z = { module = "g:z", version.ref = "plus" }\nw = { module = "g:w", version.ref = "latest" }\n'
    )
    root = project(tmp_path, toml.encode(), "libs.x\nlibs.y\nlibs.z\nlibs.w\n")
    assert main([str(root), "--format", "json"]) == 1
    findings = json.loads(capsys.readouterr().out)["findings"]
    assert {f["alias"] for f in findings if f["rule"] == "dynamic-version"} == {"bad", "plus", "latest"}


def test_empty_catalog_and_empty_version_string(tmp_path, capsys):
    root = project(tmp_path, b'[versions]\nempty = ""\n[libraries]\n', "")
    assert main([str(root), "--fail-on", "error"]) == 0
    capsys.readouterr()


def test_unreadable_catalog_next_to_a_good_one_fails(tmp_path, capsys):
    write(tmp_path / "gradle" / "libs.versions.toml", b'[libraries]\nx = "g:n:1"\n')
    write(tmp_path / "sub" / "gradle" / "broken.versions.toml", b"[versions\n")
    write(tmp_path / "build.gradle.kts", b"libs.x\n")
    assert main([str(tmp_path)]) == 2
    assert "invalid TOML" in capsys.readouterr().err
    assert main([str(tmp_path), "--fail-on", "never"]) == 0
    capsys.readouterr()


# --- Windows paths / separators --------------------------------------------------------------


@pytest.mark.parametrize("pattern", ["samples/*", "samples\\*", ".\\samples\\*", "./samples/*"])
def test_exclude_accepts_windows_and_dot_slash_patterns(make_project, pattern):
    root = make_project(
        {
            "gradle/libs.versions.toml": "[libraries]\na = 'g:a:1'\n",
            "build.gradle.kts": "libs.a\n",
            "samples/build.gradle.kts": "libs.zzz\n",
        }
    )
    proj = discover([root], [pattern])
    assert [f.name for f in proj.files] == ["build.gradle.kts"]
    assert all("samples" not in str(f) for f in proj.files)


def test_findings_use_forward_slashes_in_all_formats(tmp_path, capsys):
    root = project(tmp_path, b'[libraries]\ndead = "g:dead:1"\n', "libs.x\n")
    assert main([str(root), "--format", "json"]) == 1
    assert json.loads(capsys.readouterr().out)["findings"][0]["file"] == "gradle/libs.versions.toml"
    assert main([str(root), "--format", "sarif"]) == 1
    sarif = json.loads(capsys.readouterr().out)
    assert sarif["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == (
        "gradle/libs.versions.toml"
    )
    assert main([str(root), "--format", "github"]) == 1
    assert "file=gradle/libs.versions.toml," in capsys.readouterr().out


def test_paths_with_spaces_and_commas_are_encoded(tmp_path, capsys):
    base = tmp_path / "my project,v2"
    base.mkdir()
    root = project(base, b'[libraries]\ndead = "g:dead:1"\n', "libs.x\n")
    assert main([str(root), "--format", "sarif"]) == 1
    uri = json.loads(capsys.readouterr().out)["runs"][0]["results"][0]["locations"][0]["physicalLocation"]
    assert uri["artifactLocation"]["uri"] == "gradle/libs.versions.toml"  # relative to the project root
    nested = tmp_path / "other"
    nested.mkdir()
    write(nested / "my project,v2" / "gradle" / "libs.versions.toml", b'[libraries]\ndead = "g:d:1"\n')
    write(nested / "my project,v2" / "build.gradle.kts", b"libs.x\n")
    assert main([str(nested), "--format", "sarif"]) == 1
    uri = json.loads(capsys.readouterr().out)["runs"][0]["results"][0]["locations"][0]["physicalLocation"]
    assert uri["artifactLocation"]["uri"] == "my%20project%2Cv2/gradle/libs.versions.toml"
    assert main([str(nested), "--format", "github"]) == 1
    assert "file=my project%2Cv2/gradle/libs.versions.toml," in capsys.readouterr().out


def test_settings_catalog_path_with_subdirectory(make_project, capsys):
    root = make_project(
        {
            "settings.gradle.kts": 'dependencyResolutionManagement { versionCatalogs { create("deps") { from(files("cat/deps.versions.toml")) } } }\n',
            "cat/deps.versions.toml": "[libraries]\na = 'g:a:1'\nb = 'g:b:1'\n",
            "app/build.gradle.kts": "dependencies { implementation(deps.a) }\n",
        }
    )
    assert main([str(root), "--format", "json"]) == 1
    findings = json.loads(capsys.readouterr().out)["findings"]
    assert [f["alias"] for f in findings] == ["b"]


def test_non_ascii_alias_never_crashes_on_a_narrow_console(tmp_path, monkeypatch, capfd):
    root = project(tmp_path, '[libraries]\n"ünï" = "g:u:1"\n'.encode(), "libs.x\n")
    monkeypatch.setenv("PYTHONIOENCODING", "ascii")
    import io
    import sys

    narrow = io.TextIOWrapper(io.BytesIO(), encoding="ascii", errors="strict")
    monkeypatch.setattr(sys, "stdout", narrow)
    assert main([str(root)]) == 1  # would raise UnicodeEncodeError without the output guard
