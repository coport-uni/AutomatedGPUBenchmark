@external/CommonClaude/CLAUDE.md

# Project Overrides: AutomatedGPUBenchmark

## Scope
- Target: NVIDIA GPUs only, in three classes: consumer (GeForce),
  workstation (Quadro RTX, NVIDIA RTX), datacenter (everything else).
  AMD and Intel GPUs, multi-node runs, and NCCL tests are out of scope.
- Specification: `docs/DevSpec.md` (Korean, for the user). Everything
  committed to the repository, including README and docs, is English.
- Python package name is `gpubench`; the product and repository name is
  AutomatedGPUBenchmark.

## Hardware verification
- Burn and VRAM tests heat the GPU. Never start them without explicit
  operator confirmation in the session, even with the `quick` profile.
- During development use the `quick` profile. Run the full 900 s
  profiles only for release verification.
- Code that drives the GPU (runners, telemetry, signal handling) counts
  as verified only after a run on the real GPU with the operator
  present. Keep the console output for the PR `## Testing` section.
- Parsers, evaluation, charts, and report generation are verified with
  fixture-based tests plus `ruff check` and `ruff format --check`.
- A PR whose GPU path could not be exercised states `NOT VERIFIED` in
  `## Testing` and is not merged.

## Development host
- The development host is Windows 11 with Docker Desktop (WSL2 backend).
  Claude Code runs on the host; GPU work runs inside the runtime
  container. See `LearnedPatterns.md` §5 for what WSL2 cannot provide
  (NVIDIA Vulkan ICD, DCGM device nodes).
- Do not confuse the CommonClaude development container (privileged
  Ubuntu 24.04) with the product runtime container (`Dockerfile`,
  unprivileged, `--gpus --init`).

## Files
- Debug and exploratory scripts go to `claude_test/`, indexed in
  `claude_test/README.md`.
- `ToDo.md` is append only. `LearnedPatterns.md` follows the
  Problem / Cause / Fix / Rule format.
- Shell scripts, Python, YAML, and JSON keep LF line endings
  (`.gitattributes`); they run inside Linux containers.
