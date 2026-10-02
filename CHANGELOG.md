# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- README troubleshooting audit of OkHttp, with confirmed indirect-lookup false positives and targeted suppressions.

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

[0.1.1]: https://github.com/cosmichackerx/gradle-version-catalog-lint/releases/tag/v0.1.1
[0.1.0]: https://github.com/cosmichackerx/gradle-version-catalog-lint/releases/tag/v0.1.0
