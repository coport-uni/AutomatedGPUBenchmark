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
- [x] Section 0.3 verification, output attached to PR `## Testing`
      (submodule pinned to 4390147, CommonClaude#32)
- [x] Commit, push, PR, merge, delete branch (PR #2, 8c05bf4)

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

---

## 2. M0 follow-up: hook path guards fail on Windows

### Background
Re-verification of DevSpec section 0.3 in a new session (2026-09-28):
items 1, 2, 3, 5, 6 pass with real tool calls, but item 4 does not.
A real `Write` of `tests/debug_x.py` succeeded because Claude Code on
Windows passes `C:\...\tests\debug_x.py` and the CommonClaude hooks
test `*/tests/*` with forward-slash globs. `post-write-debug-remind`
has the same defect; `post-write-lint` and `pre-read-env-guard` work
because they do not match on directory separators. The previous
session had only tested the hooks with hand-written forward-slash
payloads. Fix belongs upstream in CommonClaude (see LP section 2, G2).

### Tasks
- [x] (70ed91d, merged as CommonClaude#32 / 4390147)
      CommonClaude: branch `fix/windows-hook-paths`, normalise
      backslashes in `pre-write-guard`, `post-write-debug-remind`,
      `pre-read-env-guard`; verify with both path styles; issue CommonClaude#31 and PR
- [x] Update PR #2 `## Testing` with the new-session evidence and the
      item 4 failure; PR #2 stays open until the fix is pinned
- [x] After the upstream PR is merged: bump the submodule pin, re-run
      item 4 with a real `Write`, then merge PR #2

---

## 3. M1: repository skeleton, pyproject, CI, fixtures

### Background
User request (2026-09-28): verify M0 and continue with the next
milestone. DevSpec section 6 M1 is "repo skeleton, pyproject, CI,
fixture collection", verified by CI passing. Verification plan: ToDo
section 1 table, row M1. Reference: DevSpec sections 3, 4.1, 4.3, 4.8.
Relevant patterns: LP G1 (LF endings), W1 (one file per write),
E3 (NVML fields on this host).

### Decisions (2026-09-28)
- Split into two PRs to stay near the 400-line guideline:
  M1a Python skeleton, config, fixtures, tests, CI lint and test job;
  M1b Dockerfile, compose, entrypoint, CI image build job, and the
  workstation fixture captured from the real GPUs.
- Branch base: `chore/harness-setup` (PR #2 is not merged yet); the
  M1 PRs target `main` and rebase after #2 merges.
- Python 3.12 (Ubuntu 24.04 system python), src layout, setuptools
  build backend, console script `gpubench`, argparse CLI. Runtime
  dependencies for M1: `nvidia-ml-py`, `PyYAML`. Dev: `pytest`, `ruff`.
- Images: `nvidia/cuda:12.8.1-devel-ubuntu24.04` builder,
  `nvidia/cuda:12.8.1-runtime-ubuntu24.04` runtime. CUDA 12.8 still
  targets Pascal (sm_60) and adds Blackwell (sm_100, sm_120).
- Tool pins: gpu-burn `3ead140` (master), cuda_memtest `e94e1ee`
  (dev). Both built for a fat binary list passed as build arg
  `CUDA_ARCHS` (default `61;70;75;80;86;89;90;100;120`).
- Profiles: `quick`, `consumer`, `workstation`, `datacenter`. Quick
  phase seconds: idle 10, burn warm-up 15, burn steady 30, cooldown
  10, VRAM 30, optional runner off. Full profiles follow DevSpec 4.1.
- Fixtures: `tests/fixtures/workstation/` captured idle from the two
  Quadro RTX 6000 (no heating); `consumer/` and `datacenter/` are
  synthetic, generated by a script in `claude_test/` and marked
  `"synthetic": true` in `sysinfo.json`.
- LICENSE file deferred to M8 together with third-party notices; the
  user chooses the license.

### Tasks
- [x] Issue for M1 (#3)
- [x] Branch `feat/m1-skeleton` from `chore/harness-setup`
- [x] `pyproject.toml` (ruff line-length 80, pytest config)
- [x] `src/gpubench/` package skeleton per DevSpec section 3 with
      `cli.py` (subcommand stubs exit 4) and `analysis/loader.py`
- [x] `config/default.yaml` and four profiles
- [x] Synthetic fixtures `consumer/`, `datacenter/` plus generator in
      `claude_test/`
- [x] `tests/test_loader.py`, `tests/test_config.py`, `tests/test_cli.py`
- [x] `.github/workflows/ci.yml` lint and test jobs
- [x] M1a verification: `ruff check`, `ruff format --check`, `pytest`;
      push, PR, CI green (PR #4, 31 tests, CI run 36434763671)
- [x] Branch `feat/m1-container` for M1b: `Dockerfile`,
      `compose.yaml`, `docker/entrypoint.sh`, CI build job that runs
      `gpu_burn -h` and `cuda_memtest --help` without a GPU
      (driver stubs in `/opt/cuda-stubs`; cuda_memtest exits 25 after
      printing usage, CI checks the output instead)
- [x] Capture idle NVML samples from the real GPUs into
      `tests/fixtures/workstation/` (script in `claude_test/`)
      (2026-09-28 14:21 UTC, 10 s, 2 GPUs, no load)
- [x] M1b verification: local `docker build`; `nvidia-smi -L` in the
      image with `--gpus all`; CI green; push, PR
- [x] `LearnedPatterns.md` additions, issue update, merge, branch
      cleanup

---

## 4. M2: detect, sysinfo, telemetry

### Background
User request (2026-09-29): continue with steps 1 and 2 (CommonClaude
hook fix PR, submodule pin, merges) and use the GPU. The CommonClaude
PR (coport-uni/CommonClaude#32) is open; merging it was refused by the
auto-mode classifier and is left to the operator. Item 4 of DevSpec
0.3 now passes with a real `Write` against the fixed hooks.
M2 is DevSpec section 6 row M2, verified per ToDo section 1 row M2.
Reference: DevSpec 4.1 (preflight, idle), 4.2, 4.3, 4.8.
Relevant patterns: LP E3 (null for unsupported NVML fields), E5
(`MSYS_NO_PATHCONV` for docker from Git Bash), W2 (no backslashes in
Bash commands).

### Decisions (2026-09-29)
- "Use the GPU" is read as the M2 hardware run: preflight and idle
  only, no load. Burn and VRAM runs (M3) still need an explicit
  operator confirmation in the session.
- NVML brand to class: GeForce, GeForce RTX, Titan, Titan RTX are
  consumer; Quadro RTX, NVIDIA RTX, and plain Quadro are workstation;
  everything else (Tesla, NVIDIA, GRID, ...) is datacenter. Titan and
  plain Quadro go beyond the M0 decision and are flagged to the user.
- Mixed GPU classes on one host require `--gpu-class`.
- `gpubench run` executes preflight and idle, then exits 3
  (INCOMPLETE) until the burn phases arrive in M3.
- Memory module layout needs dmidecode and root; the unprivileged
  container records `configuration: null`.

### Tasks
- [x] Issue for M2 (#6)
- [x] Branch `feat/m2-telemetry` from `feat/m1-container`
- [x] `detect.py`: brand to class table, class override, per-GPU
      probe of supported telemetry fields
- [x] `collectors/sysinfo.py`: `/proc/cpuinfo`, `/proc/meminfo`,
      `/etc/os-release`, `uname`, NVML GPU and driver details
- [x] `collectors/telemetry.py`: NVML sample in loader field order,
      `null` for unsupported fields, drift-free 1 s scheduler
- [x] `orchestrator.py` and `cli.py run`: result folder, preflight
      (leftover `gpu_burn` check, baseline sample), idle sampling
- [x] Fixture tests: brand table, proc parsers, fake NVML with
      unsupported fields, scheduler cadence, orchestrator dry run
- [x] Hardware run in the container: `gpubench run --profile quick`,
      check 1 s cadence, one line per GPU, `null` fields, compare
      `sysinfo.json` with `nvidia-smi -q`
- [x] Commit, push, PR, issue update

---

## 5. M3: gpu-burn and cuda_memtest runners

### Background
User request (2026-09-29): "continue with the phases that heat the
GPU as well". This is the operator confirmation required by CLAUDE.md
for burn and VRAM runs in this session. Runs use the `quick` profile
only; the 900 s profiles wait for release verification (M9).
Reference: DevSpec 4.1, 4.4 (gpu-burn OK, VRAM pattern errors), 4.8
(raw output only in `logs/`, process groups, leftover check).
Relevant patterns: LP E4 (driver stubs), E5 (`MSYS_NO_PATHCONV`), W4
(never reach NVML from unit tests).

### Decisions (2026-09-29)
- Parsers are built on raw logs captured from this host in a short
  heating run, plus synthetic failure logs marked as such.
- gpu_burn runs once for warm-up plus steady (`TIME` = sum); the
  orchestrator labels telemetry by elapsed time, so the tool is not
  restarted between the two phases.
- cuda_memtest runs one process per GPU (`--device N`) so a failing
  GPU is attributed without parsing interleaved output; each process
  runs `--stress` in a loop until the VRAM phase time is spent.
- Child processes start in their own process group; on interrupt the
  group gets SIGTERM, then SIGKILL after the gpu-burn default of 30 s.
- Cooldown samples telemetry only.
- M3 ends the run after VRAM with exit 3 (INCOMPLETE) because the
  verdict arrives in M4.

### Tasks
- [x] Issue for M3 (#8), branch `feat/m3-runners` from `feat/m2-telemetry`
- [x] Capture raw gpu_burn and cuda_memtest logs (short heating run)
- [x] `runners/base.py`: process group launch, log file, stop
- [x] `runners/gpu_burn.py`: command line, progress and result parser
- [x] `runners/cuda_memtest.py`: command line, pass and error parser
- [x] Orchestrator phases: burn_warmup, burn_steady, cooldown, vram
- [x] Parser tests on real and synthetic logs
- [x] Hardware run `gpubench run --profile quick` with GPU load;
      Gflop/s per GPU, raw output only in `logs/`, leftover check
- [x] Commit, push, PR, issue update
- [ ] Follow-up (M6): telemetry pauses while gpu_burn finishes after
      the sampling window (about 8 s with `-stts 5`); sample during
      that wait under a documented label

---

## 6. README skeleton

### Background
User question (2026-09-29): "is it right that there is no README for
this repository yet?" Confirmed: no branch has a root README. DevSpec
section 5 requires every README command to be executed, and PRs that
change CLI options or outputs to update the README; M2 and M3 did so
without a README to update. The full README stays in M8. PRs #2, #4,
#5, #7, #9 were merged in order on the user's request before this.

### Decisions (2026-09-29)
- All 16 DevSpec section 5 headings are present in order. Sections
  whose features do not exist yet say so and name the milestone.
- Every command is taken from a run in a fresh
  `git clone --recurse-submodules` of `main`; outputs are excerpts.
- `docker exec -it` (live mode) is not shown yet: the live console is
  M6 and cannot be exercised without a TTY from this session.
- LICENSE is still the user's decision; section 16 lists the
  third-party licenses only.

### Tasks
- [x] Issue (#10), branch `docs/readme-skeleton`
- [x] Fresh clone, build, start, quick run, results, cleanup executed
      exactly as written (heats the GPU for about 100 s; heating was
      confirmed by the operator in this session)
- [x] `README.md` with the 16 sections
- [ ] Commit, push, PR, merge after review
- [x] Fix found while checking README claims: `optional_s` sat at the
      top level of `workstation.yaml` and `datacenter.yaml` instead of
      under `phases`, so it was ignored; new config test catches it
- [x] Drop the stale "(M1 skeleton)" from the stub message
