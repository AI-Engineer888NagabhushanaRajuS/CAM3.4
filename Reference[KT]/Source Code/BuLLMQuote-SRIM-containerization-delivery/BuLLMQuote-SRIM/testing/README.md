# testing/

Placeholder — not yet populated.

The current test/validation artifacts belong to the backend, which hasn't been
migrated into this repo yet:

- `centum intake\test_1` through `test_21` — CBOM pipeline validation fixtures
- `centum intake\Test_fixes\` — bug-fix validation scripts and reference files
- `centum intake\staged\inbox\` — staged upload files

Consolidating these here is deferred until the backend migration pass.
`accomplish-ui\apps\web\__tests__\` (Vitest) stays with the frontend, not here,
since it's part of that app's own build/test tooling.
