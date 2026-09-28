# claude_test

Scratch area for debug, exploratory, and one-off diagnostic scripts.
Production tests live in `tests/`. See CommonClaude CLAUDE.md §3.

Scripts that touch the GPU are still hardware work: they run only with
the operator present (CommonClaude CLAUDE.md §5.1).

| File | Purpose | What was learned |
|---|---|---|
| `make_synthetic_fixtures.py` | Writes the synthetic `consumer` and `datacenter` fixtures under `tests/fixtures/` from fixed idle and load values (M1). | Fixtures must carry every field of `loader.telemetry_fields`; the script asserts the schema so drift shows up at generation time, not in a later test. |
