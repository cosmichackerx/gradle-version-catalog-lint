<div align="center">

# Gradle Version Catalog Lint

**Find unused libraries, plugins and versions in `libs.versions.toml` — and fail CI before dependency rot ships.**

A fast, zero-dependency linter for [Gradle version catalogs](https://docs.gradle.org/current/userguide/version_catalogs.html).
Built for Android and Kotlin projects, works with any Gradle build (Kotlin DSL and Groovy).

[![CI](https://github.com/cosmichackerx/gradle-version-catalog-lint/actions/workflows/ci.yml/badge.svg)](https://github.com/cosmichackerx/gradle-version-catalog-lint/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/cosmichackerx/gradle-version-catalog-lint?sort=semver)](https://github.com/cosmichackerx/gradle-version-catalog-lint/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB.svg?logo=python&logoColor=white)](pyproject.toml)
[![Dependencies: 0](https://img.shields.io/badge/runtime%20dependencies-0-brightgreen.svg)](pyproject.toml)

</div>

---

Gradle has no built-in way to tell you which `libs.versions.toml` entries are dead
([gradle/gradle#25400](https://github.com/gradle/gradle/issues/25400) is still open), so catalogs rot: removed
modules leave libraries behind, `version.ref`s outlive their users, `+` and `-SNAPSHOT` versions sneak in, and
someone pastes `"com.squareup.okhttp3:okhttp:4.12.0"` next to a catalog entry for the very same artifact.

`catalog-lint` is a **static analysis CLI** (no Gradle daemon, no network, no build needed) that reads your catalog
and every build script, then tells you exactly what is wrong, on which line. It finishes in seconds even on large
multi-module Android projects, and plugs into GitHub Actions (annotations + SARIF code scanning), pre-commit and any CI.

On real projects it finds real problems: running it on a fresh clone of
[`android/nowinandroid`](https://github.com/android/nowinandroid) reports unused entries
(`kotlinx-coroutines-android`, `androidx-dataStore-core`, an orphaned `retrofitKotlinxSerializationJson` version) —
and `square/okhttp`'s catalog has 14 removable entries.

## Features

| | |
|---|---|
| 🧹 **Unused entries** | libraries, plugins, versions and bundles that no build script references (bundle-aware: a library used only through a live bundle is *used*) |
| 📌 **Reproducibility** | dynamic versions (`1.+`, `latest.release`, open ranges) and `-SNAPSHOT` versions |
| 🔁 **Duplicates & hard-coding** | two aliases for the same `group:name`; `"g:n:v"` strings in build scripts that already exist in the catalog |
| 🧯 **Broken references** | undefined `version.ref`, bundles pointing at missing libraries, `findLibrary("typo")` lookups that would fail at configuration time |
| 🛠 **`--fix`** | removes unused entries (cascades to versions that become orphans), re-validates the TOML, supports `--dry-run` diffs |
| 🤖 **CI-native** | exit codes, `--format github` annotations, `--format sarif` for code scanning, `--format json` for scripts and AI agents |
| 🧩 **Understands real builds** | Groovy + Kotlin DSL, comments ignored, `buildSrc` / `build-logic` convention plugins, multiple catalogs, custom names from `settings.gradle(.kts)`, nested builds |
| 📦 **Zero dependencies** | pure Python 3.11+ standard library |

## Install

```bash
# recommended: isolated install straight from the tagged release
pipx install git+https://github.com/cosmichackerx/gradle-version-catalog-lint@v0.1.1

# or with pip
pip install git+https://github.com/cosmichackerx/gradle-version-catalog-lint@v0.1.1
```

Requires Python 3.11 or newer. Installs two equivalent commands: `catalog-lint` and `gradle-catalog-lint`.

## Usage

```bash
catalog-lint                       # lint the project in the current directory
catalog-lint path/to/project       # lint another project
catalog-lint gradle/libs.versions.toml
catalog-lint --fix --dry-run       # show a diff of what --fix would remove
catalog-lint --fix                 # remove unused entries
catalog-lint --format sarif > catalog-lint.sarif
catalog-lint --fail-on error       # only fail on errors, not warnings
catalog-lint --list-rules
```

### Example

The repository ships a deliberately messy Android project in [`examples/android-app`](examples/android-app):

```text
$ catalog-lint examples/android-app
app/build.gradle.kts
    12  warning  hardcoded-dependency     'com.squareup.retrofit2:retrofit' is already in the catalog; use libs.retrofit

build-logic/src/main/kotlin/android-conventions.gradle.kts
     5  error    unknown-lookup           no library alias 'androidx-core-ktxx' in any version catalog

gradle/libs.versions.toml
     5  warning  unused-version           version 'appcompat' is not used by any live entry or script
     8  warning  dynamic-version          version 'okhttp' uses dynamic version '4.12.+'
     9  warning  unused-version           version 'legacy-lint' is not used by any live entry or script
    10  warning  snapshot-version         version 'timber' uses SNAPSHOT version '5.0.1-SNAPSHOT'
    14  warning  unused-library           library 'androidx-appcompat' is never used (libs.androidx.appcompat)
    16  warning  unused-library           library 'androidx-compose-material3' is never used (libs.androidx.compose.material3)
    17  warning  duplicate-library        'retrofit' duplicates com.squareup.retrofit2:retrofit (also: retrofit, retrofit-core)
    18  warning  duplicate-library        'retrofit-core' duplicates com.squareup.retrofit2:retrofit (also: retrofit, retrofit-core)
    18  warning  unused-library           library 'retrofit-core' is never used (libs.retrofit.core)
    21  warning  unused-library           library 'legacy-support' is never used (libs.legacy.support)
    26  warning  unused-bundle            bundle 'old-ui' is never used (libs.bundles.old.ui)
    31  warning  unused-plugin            plugin 'kotlin-serialization' is never used (libs.plugins.kotlin.serialization)

14 problem(s): 1 error(s), 13 warning(s), 0 info
8 fixable with --fix (removes unused entries)
```

`--fix` removes the 8 unused entries (including the versions that only they used) and leaves the rest of your
file — comments, ordering and formatting — untouched.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | no findings at or above `--fail-on` (default `warning`) |
| `1` | findings at or above the threshold |
| `2` | usage error: bad arguments, unreadable/invalid catalog or config, no catalog found |

## GitHub Actions

Use the bundled composite action (pinned to the release tag; consider pinning to a commit SHA):

```yaml
name: Catalog lint
on: [pull_request]
permissions:
  contents: read
jobs:
  catalog-lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: cosmichackerx/gradle-version-catalog-lint@v0.1.1
        with:
          fail-on: warning      # error | warning | info | never
```

Findings show up as inline annotations on the PR. For GitHub code scanning:

```yaml
      - uses: cosmichackerx/gradle-version-catalog-lint@v0.1.1
        with:
          format: sarif
          output-file: catalog-lint.sarif
          fail-on: never
      - uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: catalog-lint.sarif
```

### pre-commit

```yaml
repos:
  - repo: https://github.com/cosmichackerx/gradle-version-catalog-lint
    rev: v0.1.1
    hooks:
      - id: catalog-lint
```

## Rules

Alias style checks are opt-in: set `naming = "kebab"` (or `"camel"`, `"snake"`) in `.catalog-lint.toml`. Single lowercase words fit every style. The rule checks all entry kinds, reports Gradle reserved segments, and never renames aliases automatically. `bundles`, `versions`, and `plugins` are reserved first segments only for libraries. Use ignore comments or config suppression for deliberate exceptions.

| Rule | Severity | Fixable | What it catches |
|---|---|---|---|
| `naming-convention` | info | | Opt-in naming style and Gradle reserved segments; never auto-fixed |
| `unused-library` | warning | ✅ | library alias never referenced by a script (directly or through a used bundle) |
| `unused-plugin` | warning | ✅ | plugin alias never referenced (`alias(libs.plugins.x)`) |
| `unused-version` | warning | ✅ | `[versions]` entry not used by any live library/plugin nor by a script (`libs.versions.x.get()`) |
| `unused-bundle` | warning | ✅ | bundle never referenced (`libs.bundles.x`) |
| `undefined-version-ref` | error | | `version.ref` points to a missing `[versions]` key |
| `undefined-bundle-member` | error | | bundle lists a library alias that does not exist |
| `duplicate-library` | warning | | two aliases resolve to the same `group:name` |
| `dynamic-version` | warning | | `+`, `latest.*` or open range as a version (`strictly` ranges are fine) |
| `snapshot-version` | warning | | `-SNAPSHOT` version in the catalog |
| `hardcoded-dependency` | warning | | `"group:name:version"` string in a script although the catalog has `group:name` |
| `unknown-lookup` | error | | `findLibrary/findPlugin/findVersion/findBundle("x")` where `x` does not exist in any catalog |

### Suppressing findings

Inline, in the catalog (on the line above the entry or at the end of its line):

```toml
[libraries]
# catalog-lint: ignore=unused-library
kotlin-stdlib = "org.jetbrains.kotlin:kotlin-stdlib:2.0.21"
legacy-thing = "com.example:legacy:1.0"  # catalog-lint: ignore
```

Or project-wide with a `.catalog-lint.toml` (see [`.catalog-lint.toml.example`](.catalog-lint.toml.example)):

```toml
disable = ["hardcoded-dependency"]
ignore = ["library:kotlin-stdlib", "*-bom"]
exclude = ["samples/*"]
fail-on = "warning"
```

## How it works

1. **Discover** every `*.versions.toml` below the given path (skipping `build/`, `.gradle/`, `node_modules/`, …).
   The catalog name comes from `settings.gradle(.kts)` (`create("tools") { from(files(...)) }`) or the file name.
2. **Parse** each catalog with `tomllib`, plus a small line scanner that records which lines every alias occupies.
3. **Scan** `*.gradle`, `*.gradle.kts` and sources under `buildSrc` / `build-logic` / `convention*`: comments are blanked
   out, then `libs.some.alias` accessors (normalised exactly like Gradle does: `-` and `_` become `.`),
   `findLibrary("…")`-style lookups and coordinate strings are collected.
4. **Report** findings with file and line; optionally **fix** by deleting the exact line spans and re-validating the TOML.

## Limitations (read this before using `--fix` in CI)

The analysis is static. Be aware of:

- **Dynamic access is invisible**: aliases built from strings at runtime (`findLibrary("androidx-$name")`) cannot be
  seen; those entries will be reported as unused. Use `# catalog-lint: ignore`.
- **Catalogs for publishing**: if a build applies the `version-catalog` plugin, `unused-*` rules are skipped for it.
- **Catalogs consumed by other repositories** will look unused from inside their own repo; use `disable` or `ignore`.
- Only top-level `[versions]`, `[libraries]`, `[plugins]` and `[bundles]` tables are understood; programmatic
  `versionCatalogs { library(...) }` declarations in `settings.gradle` are not linted.
- Always review `--fix --dry-run` first and commit before running `--fix`.
- Tested in CI on Linux, Windows and macOS (Python 3.11-3.13). Catalogs with CRLF line endings or a UTF-8 BOM are
  supported, and `--fix` preserves the file's original line endings.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check . && ruff format --check .
```

See [CONTRIBUTING.md](CONTRIBUTING.md). Good first issues are labelled
[`good first issue`](https://github.com/cosmichackerx/gradle-version-catalog-lint/labels/good%20first%20issue).

## Roadmap

- [ ] Optional `--check-updates`: report catalog versions that are outdated or very fresh (dependency cooldown)
- [ ] `unused-version` support for versions injected through `settings.gradle` `version("x", "…")`
- [ ] Lint `settings.gradle(.kts)` programmatic catalogs
- [x] Rule: alias naming conventions (camelCase vs kebab-case consistency, reserved prefixes)
- [x] Windows and macOS in the CI matrix
- [ ] Publish to PyPI (`pipx install gradle-catalog-lint`)
- [ ] SARIF `fixes` so code scanning can suggest the deletion

Ideas and rule requests are welcome as issues.

## Alternatives & prior art

[`gvc`](https://github.com/kingsword09/gvc) (catalog updates, Rust), [Inspecta](https://github.com/HossamSadekk/Inspecta)
(Gradle plugin) and IntelliJ's *Unused version catalog entry* inspection overlap partly with this tool.
`catalog-lint` aims to be the standalone, build-free, CI-first option with machine-readable output.

## License

[MIT](LICENSE) © 2026 Muhammad Arslan
