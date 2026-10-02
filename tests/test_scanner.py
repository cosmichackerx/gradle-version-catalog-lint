from pathlib import Path

from catalog_lint.scanner import discover, scan_text, strip_comments


def test_strip_comments_keeps_strings_and_lines():
    src = 'a("https://x") // libs.gone\n/* libs.gone2\n x */ b(libs.keep)\n"""// not a comment"""\n'
    out = strip_comments(src)
    assert "gone" not in out
    assert "https://x" in out
    assert "libs.keep" in out
    assert "// not a comment" in out
    assert out.count("\n") == src.count("\n")


def test_scan_text_accessors_lookups_coords():
    text = """
    dependencies {
        implementation(libs.androidx.core.ktx)
        implementation(libs.versions.kotlin.get())
        implementation("com.squareup.okhttp3:okhttp:4.12.0")
        x.findLibrary("a-b").get()
        // libs.commented
    }
    val s = "${libs.versions.agp.get()}"
    """
    scan = scan_text(Path("build.gradle.kts"), text, {"libs"})
    tokens = [t for t, _ in scan.accessors["libs"]]
    assert ["androidx", "core", "ktx"] in tokens
    assert ["versions", "kotlin", "get"] in tokens
    assert ["versions", "agp", "get"] in tokens
    assert not any("commented" in t for t in tokens)
    assert scan.lookups == [("library", "a-b", 6)]
    assert ("com.squareup.okhttp3", "okhttp", "4.12.0", 5) in scan.coords


def test_discover_names_from_settings(make_project):
    root = make_project(
        {
            "gradle/libs.versions.toml": "[libraries]\na = 'g:a:1'\n",
            "gradle/tools.versions.toml": "[libraries]\nb = 'g:b:1'\n",
            "settings.gradle.kts": """
                dependencyResolutionManagement { versionCatalogs {
                    create("myTools") { from(files("gradle/tools.versions.toml")) }
                } }
            """,
        }
    )
    proj = discover([root])
    names = {c.path.name: c.names for c in proj.catalogs}
    assert names["libs.versions.toml"] == ["libs"]
    assert names["tools.versions.toml"] == ["myTools"]


def test_discover_groovy_settings_and_skip_dirs(make_project):
    root = make_project(
        {
            "gradle/deps.versions.toml": "[libraries]\na = 'g:a:1'\n",
            "settings.gradle": "versionCatalogs { deps { from(files('gradle/deps.versions.toml')) } }",
            "build/gradle/libs.versions.toml": "[libraries]\nz = 'g:z:1'\n",
        }
    )
    proj = discover([root])
    assert [c.path.name for c in proj.catalogs] == ["deps.versions.toml"]
    assert proj.catalogs[0].names == ["deps"]


def test_discover_collects_broken_catalog_errors(make_project):
    root = make_project({"gradle/libs.versions.toml": "[[[", "gradle/ok.versions.toml": "[libraries]\n"})
    proj = discover([root])
    assert len(proj.errors) == 1 and len(proj.catalogs) == 1


def test_exclude_globs(make_project):
    root = make_project(
        {
            "gradle/libs.versions.toml": "[libraries]\na = 'g:a:1'\n",
            "samples/build.gradle.kts": "libs.a",
            "build.gradle.kts": "",
        }
    )
    proj = discover([root], ["samples/*"])
    assert [f.name for f in proj.files] == ["build.gradle.kts"]
    proj_backslashes = discover([root], ["samples\\*"])
    assert [f.name for f in proj_backslashes.files] == ["build.gradle.kts"]
