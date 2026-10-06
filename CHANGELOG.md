# Changelog

## Unreleased

* README troubleshooting audit of OkHttp, with confirmed indirect-lookup false positives and targeted suppressions.

* CI: the version pins in the README are checked against the package version by [claims-check](https://github.com/cosmichackerx/claims-check) (`.claims.json`). The first run found nothing stale.

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.4] - 2026-10-03

### Changed
- Maintenance release, no change in what the linter reports. The action and CI now use `actions/setup-python` 7.0.0 and
  `actions/checkout` 7.0.1 (both pinned by commit SHA), a `dependabot.yml` keeps them current, and CI runs
  `dependabot-gaps` in pull request mode.

## [0.1.3] - 2026-10-02

### Changed
- `action.yml` and CI now use `actions/setup-python` v6.3.0 (declares `node24`); v5 declared `node20`, which GitHub Actions
  no longer provides (found with [node24-ready](https://github.com/cosmichackerx/node24-ready)). CI has a new job that checks
  the repository's own workflows with that tool.

## [0.1.2] - 2026-10-02

### Changed
- `action.yml` is Marketplace-ready: description shortened to 121 characters (limit 125); a test checks name,
  description length, branding and the composite `runs` block.

## [0.1.1] - 2026-10-02

Robustness release: Windows/CRLF/BOM handling and several correctness fixes. CI now runs on Ubuntu, Windows and macOS.

### Fixed
- Catalogs starting with a UTF-8 byte order mark (common with Windows editors) were rejected as invalid TOML.
- `--fix` converted CRLF catalogs to LF (and LF catalogs to CRLF when run on Windows); line endings and the BOM are now preserved.
- `--fix` on table-style entries (`[libraries.foo]` followed by `module = ...`) removed only the header and aborted
  with "invalid TOML"; the whole table is now removed.
- Line numbers drifted when a catalog contained Unicode line separators (U+2028, U+0085, ...) because lines were split
  with `str.splitlines`; only LF/CRLF are line breaks now, matching TOML.
- An unreadable/invalid catalog next to valid ones was only printed to stderr and the exit code stayed 0; the run now
  exits with code 2 (unless `--fail-on never`).
- `--fix` could write some catalogs and then abort on another; all fixes are now computed before any file is written.
- `--format github`: `,` and `:` in file paths are escaped, so annotations on paths such as `my app,v2/...` resolve.
- `--format sarif`: artifact URIs are percent-encoded (paths with spaces produced invalid URIs).
- Crash with `UnicodeEncodeError` when printing non-ASCII aliases/paths to a console that cannot encode them
  (e.g. cp1252/ASCII); unencodable characters are now replaced.
- `exclude` globs written with Windows separators (`samples\*`) or a leading `./` now match.
- `.catalog-lint.toml` with a BOM is accepted.

### Added
- `tests/test_edge_cases.py`: CRLF/LF/BOM round trips, Windows-style and special-character paths, table-style,
  quoted/dotted keys, multi-line arrays, version ranges and Unicode separators.
- CI: test matrix over Ubuntu/Windows/macOS x Python 3.11-3.13, GitHub Action self-test on all three OSes, and an
  end-to-end pre-commit hook test.

## [0.1.0] - 2026-10-02

First public release.

### Added
- `catalog-lint` CLI (also installed as `gradle-catalog-lint`) with zero runtime dependencies.
- Rules: `unused-library`, `unused-plugin`, `unused-version`, `unused-bundle`,
  `undefined-version-ref`, `undefined-bundle-member`, `duplicate-library`, `dynamic-version`,
  `snapshot-version`, `hardcoded-dependency`, `unknown-lookup`.
- Usage detection for type-safe accessors (`libs.a.b`, `libs.versions.x`, `libs.plugins.x`,
  `libs.bundles.x`), `findLibrary/findPlugin/findVersion/findBundle` lookups, Groovy and Kotlin
  DSL, convention plugins in `buildSrc`/`build-logic`, comment stripping.
- Multiple catalogs, custom catalog names from `settings.gradle(.kts)`, nested builds with their own catalog.
- `--fix` / `--fix --dry-run` to remove unused entries, validated by re-parsing the TOML.
- Output formats: `text`, `json`, `github` (workflow annotations) and `sarif` (code scanning).
- `.catalog-lint.toml` configuration and inline `# catalog-lint: ignore[=rule,...]` comments.
- Composite GitHub Action (`action.yml`) and `.pre-commit-hooks.yaml`.

[0.1.2]: https://github.com/cosmichackerx/gradle-version-catalog-lint/releases/tag/v0.1.2
[0.1.1]: https://github.com/cosmichackerx/gradle-version-catalog-lint/releases/tag/v0.1.1
[0.1.0]: https://github.com/cosmichackerx/gradle-version-catalog-lint/releases/tag/v0.1.0
