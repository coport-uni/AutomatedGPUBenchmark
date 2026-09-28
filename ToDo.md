# ToDo

Append only. Never rewrite or reorder earlier entries; only flip
checkboxes and add commit or issue references to completed lines.

---

## 1. M0: apply CommonClaude harness

### Background
User request (2026-09-28): start development according to
`docs/DevSpec.md`. DevSpec section 0 requires the harness to be in place
before the first feature commit. Issue: #1.
Reference: `docs/DevSpec.md` sections 0 and 6, CommonClaude `CLAUDE.md`
at commit `ca42b88`.

### Decisions (2026-09-28)
- Repository and product name: AutomatedGPUBenchmark (the DevSpec draft
  says gpu-burnin-report). Python package stays `gpubench`.
- GPU classes: consumer (GeForce), workstation (Quadro RTX, NVIDIA RTX),
  datacenter (other brands). `--gpu-class` overrides detection.
- Development host is Windows 11 with Docker Desktop (WSL2). The
  CommonClaude privileged development container is not used; hooks run
  through Git Bash on the host.
- memtest_vulkan and DCGM diag cannot run under WSL2 (see LP section 5).
  Their hardware verification waits for a native Linux host.

### Tasks
- [x] Install missing harness dependencies: uv, Node.js LTS,
      standalone Claude Code CLI
- [x] Add `external/CommonClaude` submodule pinned to `ca42b88`
- [x] Root `CLAUDE.md` with `@external/CommonClaude/CLAUDE.md` import
      and project overrides
- [x] Root `.claude/settings.json` with hook paths inside the submodule
- [x] `claude_test/README.md`, `.gitattributes`, `.gitignore`
- [x] `scripts/setup_harness.sh`
- [x] Register MCP servers serena, context7, fetch (`claude mcp add`)
- [x] `LearnedPatterns.md` initial entries (DevSpec 4.6.1 prototype
      notes, WSL2 findings)
- [ ] Section 0.3 verification, output attached to PR `## Testing`
- [ ] Commit, push, PR, merge, delete branch

### Milestone verification plan
How each milestone in DevSpec section 6 will be verified. Every
milestone also requires `ruff check` and `ruff format --check` output
and a PR under 400 lines where possible. Hardware runs use the `quick`
profile, need operator confirmation in the session, and their console
output is pasted into the PR.

| Milestone | Software verification | Hardware verification (this host, 2x Quadro RTX 6000, WSL2) |
|---|---|---|
| M0 harness | `git submodule status`; each hook script fed a simulated Claude Code JSON payload; `claude mcp list`; `scripts/setup_harness.sh` exits 0; `/hooks` and `/memory` checked after session restart | none |
| M1 skeleton, CI | `ruff`, `pytest` on fixture loader smoke tests; `docker build` locally and in GitHub Actions; image prints `nvidia-smi -L` under `--gpus all`; `gpu_burn` and `cuda_memtest` binaries answer `--help` without loading the GPU | idle NVML samples captured from the real GPUs (no heating) become the workstation fixture; datacenter fixture is synthetic and marked as such |
| M2 detect, sysinfo, telemetry | fixture tests: brand to class table (GeForce, Quadro RTX, NVIDIA RTX, Tesla, H100, override), `/proc/cpuinfo`, `/proc/meminfo`, `os-release` parsers, unsupported NVML field becomes `null` | `gpubench run --profile quick` limited to preflight and idle phases inside the container; check 1 s cadence, one line per GPU, `null` for ECC, remap, memory temperature; `sysinfo.json` compared with `nvidia-smi -q` |
| M3 gpu-burn, cuda_memtest runners | parser tests on real logs captured in the M3 hardware run plus synthetic failure logs (compute errors, memory pattern errors, truncated output) | quick burn and short cuda_memtest with operator confirmation; check Gflop/s parsed per GPU, raw output only in `logs/`, leftover-process check aborts when a `gpu_burn` is still running |
| M4 analysis, evaluate | fixture tests only: phase boundaries, max temperature, throttle seconds, clock retention, GPU-to-GPU ratio; one test per rule for PASS, WARN, FAIL, N/A; exit code mapping; every threshold constant carries its documented source | none |
| M5 charts, docx, pdf | run inside the container on fixtures: PNG and SVG files exist; docx passes OOXML schema validation; PDF page count equals 1 (pypdf); overflow fixture with many WARN rows triggers regeneration; PDF text has no `0 건` style spacing; `gpubench pdf` re-converts an edited docx | none; the user reviews the rendered PDF visually |
| M6 console, runtime, docker exec | unit tests for mode detection, lock, state file, exit codes | `docker exec -it` live mode, `docker exec` without `-t` plain mode, `--output json`; Ctrl+C during burn kills the child process group, writes an INCOMPLETE report, exits 3; `kill -HUP` is ignored; `docker exec -d` plus `status`, `attach`, `stop`; second concurrent run refused by `/results/.lock` |
| M7 memtest_vulkan, dcgm_diag | parser tests on sample outputs from the tool documentation, marked synthetic | not possible on WSL2 (no NVIDIA Vulkan ICD, DCGM software plugin fails on `/dev`). Runner PRs stay `NOT VERIFIED` and unmerged until a native Linux host is available |
| M8 README | every command executed in order from a fresh `git clone --recurse-submodules` into a new directory; outputs pasted from those runs | one complete quick run through README sections 3 to 14 on this host |
| M9 v0.1.0 | CI green on `main`; tag pushed | full workstation profile run (about 35 min) with operator present; result folder attached to the release; datacenter profile marked unverified in the release notes |
