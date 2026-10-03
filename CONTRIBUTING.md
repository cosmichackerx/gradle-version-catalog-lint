# Contributing

Thanks for helping make Gradle builds a little tidier! Bug reports, rule ideas, docs fixes and
pull requests are all welcome.

## Development setup

```bash
git clone https://github.com/cosmichackerx/gradle-version-catalog-lint
cd gradle-version-catalog-lint
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest              # run the tests
ruff check .        # lint
ruff format .       # format
```

Python 3.11+ is required (the tool relies on the standard-library `tomllib`). The runtime has
**no third-party dependencies** and we want to keep it that way.

## Ground rules

- Every behaviour change needs a test. Rules live in `src/catalog_lint/rules.py`; add a case to
  `tests/test_rules.py` that builds a tiny project with the `make_project` fixture.
- Prefer **false negatives over false positives**. A linter that cries wolf gets uninstalled.
  If a heuristic could misfire, make it conservative and document the limitation.
- Keep the CLI output stable; JSON and SARIF are consumed by CI. Additions are fine, removals
  or renames need a major version bump.
- Update `CHANGELOG.md` under "Unreleased".
- Run `pytest` and `ruff check . && ruff format --check .` before pushing; CI runs the same.

## Adding a rule

1. Add an entry to `RULES` in `rules.py` (id, severity, one-line description).
2. Implement it in `run_catalog_rules` or `run_global_rules` and emit `Finding`s.
3. Add tests (positive, negative, and an ignore-comment case).
4. Document it in the README rules table.

## Commit / PR style

Small, focused PRs with a clear description. Conventional-commit-style prefixes (`feat:`, `fix:`,
`docs:`, `test:`, `ci:`) are appreciated but not required.

By contributing you agree that your contribution is licensed under the MIT License.
* Releasing: bump the version and the README pins in a PR, merge when green, then run **Actions > Release gate** with the new tag (for example `v1.2.3`) *before* you create the tag. The same check runs again on the tag, and a weekly job (`claims-latest.yml`) fails when the README pins an older release than the newest tag.
