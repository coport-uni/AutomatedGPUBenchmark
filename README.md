# AutomatedGPUBenchmark

> **Status: early development (0.1.0.dev0).** This README is a skeleton.
> Every command in it was executed from a fresh clone of `main`, and the
> outputs are excerpts from those runs. Sections for features that do
> not exist yet say so and name the milestone that adds them
> (`docs/DevSpec.md` section 6).

## 1. Overview

AutomatedGPUBenchmark runs a burn-in test on every NVIDIA GPU in a host
from a single container. It records telemetry once per second, loads
the GPUs with [gpu-burn](https://github.com/wilicc/gpu-burn), tests
their memory with
[cuda_memtest](https://github.com/ComputationalRadiationPhysics/cuda_memtest),
and writes the raw results to a folder per run.

| GPU class | Detected from NVML brand | Optional extra test |
|---|---|---|
| consumer | GeForce, GeForce RTX, Titan, Titan RTX | memtest_vulkan (M7) |
| workstation | Quadro, Quadro RTX, NVIDIA RTX | none |
| datacenter | everything else (Tesla, NVIDIA, ...) | `dcgmi diag -r 3` (M7) |

A run goes through these phases:

| Phase | Full profiles | `quick` profile | What happens |
|---|---|---|---|
| preflight | a few seconds | a few seconds | GPU detection, class, leftover-tool check, baseline sample |
| idle | 60 s | 10 s | telemetry only |
| burn_warmup | 300 s | 15 s | gpu_burn |
| burn_steady | 600 s | 30 s | gpu_burn continues |
| cooldown | 120 s | 10 s | telemetry only |
| vram | 600 s | 30 s | cuda_memtest `--stress` on every GPU |

Available today: the phases above, the PASS/WARN/FAIL verdict and its
exit status, `telemetry.jsonl`, `sysinfo.json`, `summary.json`, and
the raw tool logs. **Not yet available:** charts and the one-page A4
report in `report.docx` and `report.pdf` (M5), and the live console
(M6).
`example/GPU_Burn-in_Report_Sample.pdf` shows the planned report. It
was generated from synthetic data during specification.

## 2. Requirements

| Item | Requirement |
|---|---|
| Host | Linux with an NVIDIA driver, or Windows 11 with Docker Desktop (WSL2 backend). Verified so far only on Windows 11 with Docker Desktop 28.5.2 |
| GPU | NVIDIA, compute capability 6.1 (Pascal) or newer |
| Docker | Docker Engine or Docker Desktop with GPU support (NVIDIA Container Toolkit on Linux) |
| Disk | 5.67 GB for the `gpubench` image, plus the CUDA 12.8.1 devel and runtime base images during the build (the runtime base image alone is 5.58 GB) |

Check the driver and GPU access from a container:

```bash
nvidia-smi --query-gpu=name,driver_version --format=csv
```
```
name, driver_version
Quadro RTX 6000, 596.72
Quadro RTX 6000, 596.72
```

```bash
docker run --rm --gpus all nvidia/cuda:12.8.1-runtime-ubuntu24.04 nvidia-smi -L
```
```
GPU 0: Quadro RTX 6000 (UUID: GPU-34a52002-1cb4-55c1-dbe6-1c5ec554e856)
GPU 1: Quadro RTX 6000 (UUID: GPU-45994475-78d8-499b-00a1-65696b061259)
```

On Docker Desktop (WSL2) the GPU has no Vulkan driver and no
`/dev/nvidia*` nodes, so memtest_vulkan and DCGM diagnostics cannot run
there (see `LearnedPatterns.md` section 5).

## 3. Get the Code

```bash
git clone --recurse-submodules https://github.com/coport-uni/AutomatedGPUBenchmark.git
cd AutomatedGPUBenchmark
```

If you cloned without `--recurse-submodules`:

```bash
git submodule update --init --recursive
```

`git submodule status` then prints the pinned CommonClaude commit:

```
 43901471b9939f5e1813d263c351f732d026d77a external/CommonClaude (heads/main)
```

## 4. Build the Image

```bash
docker build -t gpubench .
```

The first build downloads the CUDA 12.8.1 base images and compiles
gpu-burn and cuda_memtest for every supported GPU architecture. It
takes 5 to 10 minutes on the GitHub Actions runners. Later builds
reuse the cache.

| Build arg | Default | Meaning |
|---|---|---|
| `CUDA_VERSION` | `12.8.1` | CUDA base image version |
| `CUDA_ARCHS` | `61;70;75;80;86;89;90;100;120` | GPU architectures compiled into the tools |
| `GPU_BURN_REF` | `3ead140...` | gpu-burn commit |
| `CUDA_MEMTEST_REF` | `e94e1ee...` | cuda_memtest commit |

Check the image:

```bash
docker run --rm gpubench gpubench --version
docker run --rm --gpus all gpubench nvidia-smi -L
```
```
gpubench 0.1.0.dev0
GPU 0: Quadro RTX 6000 (UUID: GPU-34a52002-1cb4-55c1-dbe6-1c5ec554e856)
GPU 1: Quadro RTX 6000 (UUID: GPU-45994475-78d8-499b-00a1-65696b061259)
```

## 5. Start the Container

The container stays running and tests are started with `docker exec`.

```bash
mkdir -p results
docker run -d --name gpubench --hostname "$(hostname)" --init --gpus all \
    -v "$PWD/results:/results" gpubench
```

| Option | Why |
|---|---|
| `-d` | Keeps the container resident; its command is `sleep infinity` |
| `--hostname "$(hostname)"` | Result folders are named after the host instead of the container ID |
| `--init` | Runs `docker-init` as PID 1 to reap processes the test tools leave behind |
| `--gpus all` | The GPUs are fixed when the container starts; restart it to change them |
| `-v "$PWD/results:/results"` | Result folders appear in `./results` on the host |

No `--privileged` is needed. `compose.yaml` describes the same container.

## 6. Run a Test

This loads the GPUs. Watch the temperatures on the first run.

```bash
docker exec gpubench gpubench run --profile quick
```

Output excerpt (the console prints one line per second):

```
preflight: 2 GPU(s), class workstation, profile quick, results /results/gpubench-dev_20260929-002048
preflight: gpu0 Quadro RTX 6000 (Quadro RTX), unsupported: temp_mem, ecc_corr, ecc_uncorr, remap_corr, remap_uncorr, remap_pending, remap_failure
[idle 1/10] gpu0 29 C 20.91 W 300 MHz | gpu1 29 C 12.29 W 300 MHz
burn: gpu_burn for 45 s, log /results/gpubench-dev_20260929-002048/logs/gpu_burn.log
[burn_steady 1/30] gpu0 43 C 260.36 W 1605 MHz | gpu1 44 C 255.5 W 1590 MHz
[burn_steady 30/30] gpu0 60 C 255.66 W 1545 MHz | gpu1 61 C 252.62 W 1530 MHz
burn: gpu0 13923.0 Gflop/s max, 0 errors, verdict OK
burn: gpu1 13979.0 Gflop/s max, 0 errors, verdict OK
vram: cuda_memtest on 2 GPU(s)
[vram 30/30] gpu0 66 C 197.14 W 1890 MHz | gpu1 67 C 204.92 W 1875 MHz
vram: gpu0 1 tests, 0 pattern errors
vram: gpu1 2 tests, 0 pattern errors
verdict: Compute errors: gpu0 PASS (OK, 0 errors), gpu1 PASS (OK, 0 errors)
verdict: VRAM pattern errors: gpu0 PASS (0 errors in 1 tests), gpu1 PASS (0 errors in 2 tests)
verdict: ECC uncorrectable increase: gpu0 N/A (ECC not reported), gpu1 N/A (ECC not reported)
verdict: HW slowdown, HW thermal, power brake: gpu0 PASS (0 s), gpu1 PASS (0 s)
verdict: SW thermal slowdown: gpu0 PASS (0 s), gpu1 PASS (0 s)
verdict: Maximum temperature: gpu0 PASS (66 C (limit 91 C)), gpu1 PASS (67 C (limit 91 C))
verdict: GPU-to-GPU throughput: gpu0 PASS (99.9% of fastest (13333 Gflop/s)), gpu1 PASS (100.0% of fastest (13345 Gflop/s))
run: finished in 102 s; verdict PASS
```

The exit status of `docker exec` is the verdict (section 8); this run
exited with 0.

The `quick` profile took 102 s on this host. `--profile auto`, the
default, picks the profile named after the detected class. Its phases
add up to 1680 s, about 30 minutes; the optional tests of M7 will add
300 s (consumer) or 900 s (datacenter). `--gpu-class` overrides the
detected class.
The live TTY console for `docker exec -it` arrives in M6.

## 7. Long Runs over SSH

Not available yet (M6): `status`, `attach`, and `stop` currently exit
with status 4.

## 8. Scripted and CI Use

`docker exec` without `-t` prints plain lines, as shown in section 6.
JSON console output arrives in M6.

| Exit status | Meaning |
|---|---|
| 0 | PASS |
| 1 | WARN |
| 2 | FAIL |
| 3 | INCOMPLETE: interrupted, or a tool result is missing (for example gpu_burn printed no verdict) |
| 4 | Error, for example a leftover `gpu_burn`, no GPU, or a usage error |

## 9. Results

Each run writes `results/<hostname>_<YYYYMMDD-HHMMSS>/`:

```
logs/
    cuda_memtest_gpu0.log
    cuda_memtest_gpu1.log
    gpu_burn.log
summary.json
sysinfo.json
telemetry.jsonl
```

| File | Content |
|---|---|
| `telemetry.jsonl` | One JSON line per GPU per second: phase, temperatures, power, clocks, utilisation, memory, fan, pstate, clocks event reasons, ECC and row-remap counters, PCIe. Unsupported fields are `null` |
| `sysinfo.json` | GPUs (brand, class, VBIOS, ECC mode, slowdown and shutdown temperatures, power limit, maximum clocks, PCIe), driver, CUDA, CPU, memory, OS, and the profile used |
| `summary.json` | Verdict and exit code, the grade of every rule per GPU, per-GPU metrics, incomplete reasons, and the raw runner results |
| `logs/*.log` | Raw tool output; it never reaches the console |

`report.docx`, `report.pdf`, `report.html`, `report.md`,
`dashboard.html`, and `charts/` arrive in M5.

## 10. Reading the Report

The printed report arrives in M5. The verdict already exists in
`summary.json` and on the console.

Only thresholds documented by NVIDIA or by the tool in use are graded.
Grades follow DCGM error severity: ISOLATE and RESET become FAIL,
MONITOR becomes WARN. The run verdict is the worst grade of any GPU;
N/A never lowers it.

| Rule | Criterion | Grade if violated | Source |
|---|---|---|---|
| Compute errors | gpu_burn reports OK | FAIL | gpu-burn verdict |
| VRAM pattern errors | 0 errors | FAIL | DCGM memtest: any error fails |
| ECC uncorrectable increase | 0 | FAIL | DCGM: DBE error is ISOLATE |
| HW slowdown, HW thermal, power brake | never active | WARN | NVML clocks event reasons; DCGM clocks event is MONITOR |
| SW thermal slowdown | never active | WARN | same |
| Maximum temperature | below the GPU slowdown temperature the GPU reports | WARN | nvidia-smi; DCGM temperature violation is MONITOR |
| GPU-to-GPU throughput | at least 90 % of the fastest GPU (mean Gflop/s) | FAIL | gpu-fryer default tolerance 10 % |

Only `burn_steady` and `vram` samples are graded; warm-up, idle, and
cooldown are context. A rule is N/A when the GPU does not report the
value (ECC on boards with ECC disabled, for example) or cannot apply
(the GPU ratio with one GPU).

Reported but never graded: SM clock retention (steady mean over rated
maximum), steady mean temperature, maximum power, and time at the SW
power cap. The Quadro RTX 6000 pair above spends all of `burn_steady`
at its 260 W power cap, which is expected under gpu_burn.

A run is INCOMPLETE when a tool result is missing: gpu_burn printed no
verdict, a GPU has no samples in the graded phases, or cuda_memtest
finished no test or reported an error without a pattern count.

## 11. Re-rendering and Comparing

Not available yet (M5): `plot` and `compare` currently exit with
status 4.

## 12. Configuration

`config/default.yaml` holds every setting. A profile in
`config/profiles/` overrides only the keys it lists.

| Profile | Differences from `default.yaml` |
|---|---|
| `quick` | Short phases (table in section 1), no optional test. For development only |
| `consumer` | Optional test memtest_vulkan (M7) |
| `workstation` | No optional test |
| `datacenter` | Optional test `dcgmi diag -r 3` (M7) |

Useful keys: `phases.*_s` (phase lengths), `gpu_burn.memory_percent`
(`-m N%`, default 90), `gpu_burn.use_doubles`, `gpu_burn.use_tensor_cores`,
and `cuda_memtest.stress`.

## 13. Troubleshooting

| Symptom | Action |
|---|---|
| `preflight: gpu_burn still running as pid N`, exit status 4 | A previous run left a test tool behind. Wait for it to finish, or restart the container |
| `preflight: GPUs of different classes ...` | Choose one with `--gpu-class` |

The remaining entries of `docs/DevSpec.md` section 5 are added with the
features they describe.

## 14. Cleanup

```bash
docker stop gpubench && docker rm gpubench
docker rmi gpubench
```

Result folders stay in `./results` until you delete them.

## 15. Development

The repository follows the CommonClaude conventions, which are pinned
as a submodule in `external/CommonClaude`. `CLAUDE.md` imports them and
adds the project rules. Run `bash scripts/setup_harness.sh` to check
the Claude Code harness; it needs `jq`, `ruff`, and the MCP servers
serena, context7, and fetch.

Every task follows the same steps: an append-only `ToDo.md` entry, a
GitHub issue, a branch, verification, then a pull request. Code that
drives the GPU counts as verified only after a run on a real GPU with
the operator present. Heating runs (burn, VRAM) need the operator's
confirmation, and the output goes into the pull request.

Lint and tests:

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
ruff check .
ruff format --check .
pytest -q
```
```
All checks passed!
30 files already formatted
86 passed in 1.39s
```

## 16. License and Third-party

The license of this repository has not been chosen yet. The image
contains:

| Component | License |
|---|---|
| [gpu-burn](https://github.com/wilicc/gpu-burn) | BSD 2-Clause |
| [cuda_memtest](https://github.com/ComputationalRadiationPhysics/cuda_memtest) | Illinois Open Source License (NCSA) |
| [NVIDIA CUDA base images](https://hub.docker.com/r/nvidia/cuda) | NVIDIA Deep Learning Container License |
| [nvidia-ml-py](https://pypi.org/project/nvidia-ml-py/), [PyYAML](https://pypi.org/project/PyYAML/) | BSD, MIT |
