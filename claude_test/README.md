# claude_test

Scratch area for debug, exploratory, and one-off diagnostic scripts.
Production tests live in `tests/`. See CommonClaude CLAUDE.md §3.

Scripts that touch the GPU are still hardware work: they run only with
the operator present (CommonClaude CLAUDE.md §5.1).

| File | Purpose | What was learned |
|---|---|---|
| `make_synthetic_fixtures.py` | Writes the synthetic `consumer` and `datacenter` fixtures under `tests/fixtures/` from fixed idle and load values (M1). | Fixtures must carry every field of `loader.telemetry_fields`; the script asserts the schema so drift shows up at generation time, not in a later test. |
| `capture_idle_fixture.py` | Samples idle NVML telemetry from the real GPUs inside the runtime image and writes `tests/fixtures/workstation/` (M1b). Read-only, no load. | Seeds the M2 collector; documents which NVML calls return Not Supported on Quadro RTX 6000 under WSL2 (LP E3). |
