from catalog_lint.rules import run_catalog_rules, run_global_rules
from catalog_lint.scanner import discover, scan_files


def lint(root, naming=None):
    proj = discover([root])
    scans = scan_files(proj)
    findings, notes = [], []
    for c in proj.catalogs:
        f, n = run_catalog_rules(proj, c, scans, naming=naming)
        findings += f
        notes += n
    findings += run_global_rules(proj, scans)
    return findings, notes


def rules_of(findings):
    return sorted((f.rule, f.alias) for f in findings)


BASE = {
    "settings.gradle.kts": "",
    "build.gradle.kts": "",
}


def test_clean_project_has_no_findings(make_project):
    root = make_project(
        {
            **BASE,
            "gradle/libs.versions.toml": """
                [versions]
                kt = "1.9.0"
                [libraries]
                core-ktx = { module = "androidx.core:core-ktx", version.ref = "kt" }
                [plugins]
                kotlin = { id = "org.jetbrains.kotlin.android", version.ref = "kt" }
            """,
            "app/build.gradle.kts": "plugins { alias(libs.plugins.kotlin) }\n"
            "dependencies { implementation(libs.core.ktx) }",
        }
    )
    findings, _ = lint(root)
    assert findings == []


def test_unused_entries_and_bundle_liveness(make_project):
    root = make_project(
        {
            **BASE,
            "gradle/libs.versions.toml": """
                [versions]
                v1 = "1"
                v2 = "2"
                v3 = "3"
                [libraries]
                direct = { module = "g:direct", version.ref = "v1" }
                via-bundle = { module = "g:viabundle", version.ref = "v2" }
                dead = { module = "g:dead", version.ref = "v3" }
                [bundles]
                live = ["via-bundle"]
                dead-bundle = ["dead"]
                [plugins]
                deadplugin = { id = "x.dead", version = "1" }
            """,
            "app/build.gradle.kts": "dependencies { implementation(libs.direct); implementation(libs.bundles.live) }",
        }
    )
    findings, _ = lint(root)
    assert rules_of(findings) == [
        ("unused-bundle", "dead-bundle"),
        ("unused-library", "dead"),
        ("unused-plugin", "deadplugin"),
        ("unused-version", "v3"),
    ]


def test_usage_forms(make_project):
    root = make_project(
        {
            **BASE,
            "gradle/libs.versions.toml": """
                [versions]
                jackson = "1"
                jackson-databind = "2"
                kotlin = "2"
                [libraries]
                camelCaseLib = "g:camel:1"
                under_score = "g:under:1"
                grp-sub = "g:sub:1"
                by-lookup = "g:lookup:1"
                by-groovy = "g:groovy:1"
                provider-lib = "g:provider:1"
                [plugins]
                kotlin-jvm = { id = "k", version.ref = "kotlin" }
            """,
            "a/build.gradle.kts": """
                dependencies {
                    implementation(libs.camelCaseLib)
                    implementation(libs.under.score)
                    implementation(libs.grp.sub.get())
                    implementation(libs.provider.lib.asProvider())
                }
                val j = libs.versions.jackson.asProvider().get()
                val d = libs.versions.jackson.databind.get()
                plugins { alias(libs.plugins.kotlin.jvm) }
            """,
            "b/build.gradle": "dependencies { implementation libs.by.groovy }",
            "build-logic/src/main/kotlin/conv.gradle.kts": 'val c = versionCatalogs.named("libs"); c.findLibrary("by-lookup")',
        }
    )
    findings, _ = lint(root)
    assert findings == []


def test_commented_out_usage_does_not_count(make_project):
    root = make_project(
        {
            **BASE,
            "gradle/libs.versions.toml": "[libraries]\nfoo = 'g:foo:1'\n",
            "app/build.gradle.kts": "// implementation(libs.foo)\n/* libs.foo */",
        }
    )
    findings, _ = lint(root)
    assert rules_of(findings) == [("unused-library", "foo")]


def test_structural_errors(make_project):
    root = make_project(
        {
            **BASE,
            "gradle/libs.versions.toml": """
                [libraries]
                a = { module = "g:a", version.ref = "missing" }
                [bundles]
                b = ["a", "ghost"]
                [plugins]
                p = { id = "x", version.ref = "alsomissing" }
            """,
            "app/build.gradle.kts": "libs.a; libs.bundles.b; libs.plugins.p",
        }
    )
    findings, _ = lint(root)
    assert rules_of(findings) == [
        ("undefined-bundle-member", "b"),
        ("undefined-version-ref", "a"),
        ("undefined-version-ref", "p"),
    ]
    assert all(f.severity == "error" for f in findings)


def test_duplicates_dynamic_snapshot(make_project):
    root = make_project(
        {
            **BASE,
            "gradle/libs.versions.toml": """
                [versions]
                dyn = "1.+"
                latest = "latest.release"
                rng = "[1.0,2.0)"
                pinned = { strictly = "[1.0,2.0[", prefer = "1.5" }
                snap = "1.0-SNAPSHOT"
                [libraries]
                one = { module = "g:same", version = "1.0" }
                two = { group = "g", name = "same", version = "2.0" }
                inline-dyn = "g:inlinedyn:+"
                use-dyn = { module = "g:x", version.ref = "dyn" }
            """,
            "app/build.gradle.kts": "libs.one; libs.two; libs.inline.dyn; libs.use.dyn;"
            "libs.versions.latest.get(); libs.versions.rng.get(); libs.versions.pinned.get(); libs.versions.snap.get()",
        }
    )
    findings, _ = lint(root)
    assert rules_of(findings) == [
        ("duplicate-library", "one"),
        ("duplicate-library", "two"),
        ("dynamic-version", "dyn"),
        ("dynamic-version", "inline-dyn"),
        ("dynamic-version", "latest"),
        ("dynamic-version", "rng"),
        ("snapshot-version", "snap"),
    ]


def test_hardcoded_dependency_and_unknown_lookup(make_project):
    root = make_project(
        {
            **BASE,
            "gradle/libs.versions.toml": "[libraries]\nok = { module = 'com.squareup.okhttp3:okhttp', version = '4' }\n",
            "app/build.gradle.kts": """
                dependencies {
                    implementation(libs.ok)
                    implementation("com.squareup.okhttp3:okhttp:4.12.0")
                    implementation("com.other:thing:1")
                }
            """,
            "build-logic/c.gradle.kts": 'x.findLibrary("nope"); x.findPlugin("ghost"); x.findLibrary("ok")',
        }
    )
    findings, _ = lint(root)
    assert rules_of(findings) == [
        ("hardcoded-dependency", "ok"),
        ("unknown-lookup", "ghost"),
        ("unknown-lookup", "nope"),
    ]
    hard = next(f for f in findings if f.rule == "hardcoded-dependency")
    assert hard.line == 3 and "libs.ok" in hard.message


def test_ignore_comment_suppresses(make_project):
    root = make_project(
        {
            **BASE,
            "gradle/libs.versions.toml": """
                [libraries]
                # catalog-lint: ignore=unused-library
                kept = "g:kept:1"
                gone = "g:gone:1"
            """,
            "app/build.gradle.kts": "// nothing",
        }
    )
    findings, _ = lint(root)
    assert rules_of(findings) == [("unused-library", "gone")]


def test_published_catalog_skips_unused(make_project):
    root = make_project(
        {
            "gradle/libs.versions.toml": "[libraries]\nfoo = 'g:foo:1'\n",
            "build.gradle.kts": 'plugins { `version-catalog` }\ncatalog { versionCatalog { from(files("gradle/libs.versions.toml")) } }',
        }
    )
    findings, notes = lint(root)
    assert findings == []
    assert any("published catalog" in n for n in notes)


def test_no_build_files_skips_unused(make_project):
    root = make_project({"gradle/libs.versions.toml": "[libraries]\nfoo = 'g:foo:1'\n"})
    findings, notes = lint(root)
    assert findings == []
    assert any("no Gradle build files" in n for n in notes)


def test_multiple_catalogs_with_custom_name(make_project):
    root = make_project(
        {
            "gradle/libs.versions.toml": "[libraries]\na = 'g:a:1'\n",
            "gradle/test.versions.toml": "[libraries]\njunit = 'junit:junit:4'\nunused = 'g:u:1'\n",
            "settings.gradle.kts": 'versionCatalogs { create("testLibs") { from(files("gradle/test.versions.toml")) } }',
            "app/build.gradle.kts": "libs.a; testLibs.junit",
        }
    )
    findings, _ = lint(root)
    assert rules_of(findings) == [("unused-library", "unused")]


def test_nested_build_with_own_catalog_is_separate(make_project):
    root = make_project(
        {
            "gradle/libs.versions.toml": "[libraries]\nouter = 'g:outer:1'\n",
            "build.gradle.kts": "libs.outer",
            "tools/gradle/libs.versions.toml": "[libraries]\ninner = 'g:inner:1'\n",
            "tools/build.gradle.kts": "// libs.outer is not valid here\nlibs.inner",
        }
    )
    findings, _ = lint(root)
    assert findings == []


def test_opt_in_naming_styles_and_ignores(make_project):
    root = make_project(
        {
            **BASE,
            "gradle/libs.versions.toml": """
        [versions]
        BadVersion = "1"
        [libraries]
        good-name = "g:good:1"
        camelName = "g:camel:1"
        snake_name = "g:snake:1"
        IgnoredName = "g:ignored:1" # catalog-lint: ignore=naming-convention
        [bundles]
        BadBundle = ["good-name"]
        [plugins]
        BadPlugin = { id = "g.plugin", version = "1" }
    """,
        }
    )
    assert not any(f.rule == "naming-convention" for f in lint(root)[0])
    for style, good in [("kebab", "good-name"), ("camel", "camelName"), ("snake", "snake_name")]:
        findings = [f for f in lint(root, style)[0] if f.rule == "naming-convention"]
        assert {f.alias for f in findings} == {
            "BadVersion",
            "BadBundle",
            "BadPlugin",
            "good-name",
            "camelName",
            "snake_name",
        } - {good}
        assert all(f.severity == "info" and not f.fixable for f in findings)


def test_naming_respects_gradle_reserved_segments(make_project):
    root = make_project(
        {
            **BASE,
            "gradle/libs.versions.toml": """
        [versions]
        versions-ok = "1"
        [libraries]
        versions-bad = "g:v:1"
        bundles-bad = "g:b:1"
        plugins-bad = "g:p:1"
        foo-class-bar = "g:c:1"
        foo-extensions = "g:ext:1"
        convention-plugin = "g:convplugin:1"
        extensions = "g:e:1"
        convention = "g:conv:1"
        [plugins]
        plugins-ok = { id = "g.plugin", version = "1" }
    """,
        }
    )
    findings = [f for f in lint(root, "kebab")[0] if f.rule == "naming-convention"]
    assert {f.alias for f in findings} == {
        "versions-bad",
        "bundles-bad",
        "plugins-bad",
        "foo-class-bar",
        "extensions",
        "convention",
    }
    assert all("reserved" in f.message for f in findings)
