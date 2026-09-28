# LearnedPatterns.md

> Patterns extracted from completed work. Consult the relevant sections
> before drafting new ToDo entries. Append new patterns after each task
> completes (see CommonClaude CLAUDE.md section 9).
>
> Last updated: 2026-09-28
> Total patterns: 14
>
> Provenance format: `(from ToDo#N)` where N is the top-level `##`
> section number in `ToDo.md`, or `(from DevSpec 4.6.1)` for entries
> carried over from the specification prototype.

---

## §1. Recurring Issues

(none yet)

---

## §2. Solved Gotchas

### G1. Windows checkout turns shell scripts into CRLF

- **Problem**: `git submodule add` warned that LF would be replaced by CRLF; a CRLF `entrypoint.sh` or hook script fails inside a Linux container or Git Bash with `\r: command not found`.
- **Cause**: Git on Windows defaults to `core.autocrlf=true`, which rewrites text files on checkout.
- **Fix**: Added `.gitattributes` forcing `eol=lf` for `.sh`, `.py`, `.yaml`, `.json`, `.md`, `.toml`, and `Dockerfile`.
- **Rule**: Always commit `.gitattributes` with `eol=lf` rules before adding scripts that run in Linux containers. (from ToDo#1)

### G2. CommonClaude hook path guards do not match Windows paths

- **Problem**: A real `Write` of `tests/debug_x.py` from Claude Code on Windows was not blocked, although the same hook blocked a hand-written forward-slash payload.
- **Cause**: Claude Code passes `C:\...\tests\debug_x.py`; `pre-write-guard` and `post-write-debug-remind` match `*/tests/*` and `*/claude_test/*` with forward-slash globs, so backslash paths never match.
- **Fix**: Upstream fix in CommonClaude normalises `file_path` with `${file_path//\\//}` before the checks (CommonClaude issue #31, branch `fix/windows-hook-paths`); this repo bumps the submodule pin once it is merged.
- **Rule**: Always verify hooks with the payload the real tool sends on the current host (use the tool itself, not only a simulated JSON payload). (from ToDo#2)

---

## §3. Library Quirks

### L1. LibreOffice adds a space between Korean text and digits in PDF

- **Problem**: The PDF showed `0 건` where the docx had `0건`.
- **Cause**: LibreOffice DOCX import ignores `w:autoSpaceDE` and `w:autoSpaceDN`, so Asian autospace stays on.
- **Fix**: Convert through UNO instead of `soffice --convert-to`: open the document headless, set `ParaIsCharacterDistance` to False on every paragraph style and paragraph, then export with `writer_pdf_Export`.
- **Rule**: Always convert docx to PDF through UNO with autospace disabled; never rely on `soffice --convert-to` for Korean text. (from DevSpec 4.6.1)

### L2. python-docx table widths ignored, report spills to page 2

- **Problem**: Table columns rendered with widths different from the ones set on the cells, pushing the report past one A4 page.
- **Cause**: Only cell widths were set; `tblGrid` and `tblW` were missing, so the renderer autofit the table.
- **Fix**: Set `gridCol` widths, `tblW`, and fixed table layout together with the cell widths.
- **Rule**: Always specify `tblGrid`, `tblW`, and `tblLayout type="fixed"` when a table must keep exact column widths. (from DevSpec 4.6.1)

### L3. OOXML schema validation fails on element order

- **Problem**: Schema validation of the generated docx failed on `tcPr`, `tblPr`, and `tblBorders`.
- **Cause**: Child elements were appended in an order different from the schema sequence.
- **Fix**: Insert children through a helper that respects the schema order.
- **Rule**: Always insert OOXML property children in schema order; never append blindly to `tcPr`, `tblPr`, or `tblBorders`. (from DevSpec 4.6.1)

### L4. python-docx default template fails schema validation on `w:zoom`

- **Problem**: Schema validation reported a missing attribute on `w:zoom` in `settings.xml`.
- **Cause**: The default python-docx template omits `w:percent` on `w:zoom`.
- **Fix**: Set `w:percent="100"` on `w:zoom` before saving.
- **Rule**: Always patch `w:zoom` with `w:percent="100"` before validating a python-docx document. (from DevSpec 4.6.1)

---

## §4. Workflow Lessons

### W1. Long multi-file heredoc commands fail silently on quoting

- **Problem**: One Bash call writing seven files through nested heredocs aborted with `unexpected EOF while looking for matching quote` and wrote nothing.
- **Cause**: Nested heredoc delimiters plus shell-expanded parameter expansions inside one very long command are hard to keep balanced.
- **Fix**: Wrote each file with the dedicated Write tool instead.
- **Rule**: Never batch more than one or two files into a single heredoc command; write files individually. (from ToDo#1)

### W2. The Bash tool collapses doubled backslashes on this host

- **Problem**: Text written through Bash heredocs or inline Python arrived with one backslash where two were typed; `\\t` became a tab in a Markdown file and a JSON payload became invalid.
- **Cause**: The Claude Code Bash tool layer unescapes backslash pairs before Git Bash sees the command, so every quoting level below it is off by one.
- **Fix**: Wrote backslash-bearing content with the Write tool, or built it in Python from `chr(92)` so the command string holds no backslashes at all.
- **Rule**: Never put backslashes in a Bash command string on this host; use Write or `chr(92)`. (from ToDo#2)

### W3. `cd` into the submodule inside a compound Bash command is not honoured

- **Problem**: `cd external/CommonClaude && git add ...` staged and pushed against the superproject, and `cat ToDo.md` after such a `cd` printed the superproject file.
- **Cause**: The Bash tool tracks the working directory itself and applies a leading `cd` to later calls (visible as the "Primary working directory" toggling), not to the rest of the same command.
- **Fix**: Addressed the submodule with `git -C external/CommonClaude ...` and absolute file paths.
- **Rule**: Always use `git -C <path>` and absolute paths for the submodule; never rely on `cd` inside a compound command. (from ToDo#2)

---

## §5. Environment Specifics

### E1. WSL2 containers have no NVIDIA Vulkan ICD

- **Problem**: `vulkaninfo` inside a `--gpus all` container lists only `llvmpipe`, so memtest_vulkan cannot test the real GPU.
- **Cause**: WSL2 exposes the GPU through `/dev/dxg` (dxgkrnl paravirtualisation). NVIDIA provides CUDA and a subset of NVML to Linux this way but no Linux Vulkan ICD; the WSL Vulkan path goes through Mesa dozen to D3D12, and Docker Desktop does not mount `/usr/lib/wsl/lib` into containers.
- **Fix**: memtest_vulkan runner is verified on a native Linux host only.
- **Rule**: Never plan Vulkan-based GPU tests on a Docker Desktop or WSL2 host; require native Linux with `NVIDIA_DRIVER_CAPABILITIES=graphics`. (from ToDo#1)

### E2. DCGM diag fails its software plugin under WSL2

- **Problem**: `nv-hostengine` starts and `dcgmi discovery -l` lists both GPUs, but `dcgmi diag -r 1` reports `software: Fail`, "number of devices NVML returns is different than the number of devices in /dev".
- **Cause**: The container `/dev` has only `dxg`; there are no `/dev/nvidia*` nodes under WSL2. NVIDIA lists WSL as unsupported for DCGM.
- **Fix**: dcgm_diag runner is verified on a native Linux host only.
- **Rule**: Never treat DCGM discovery on WSL2 as proof that `dcgmi diag` works; verify diag levels on native Linux. (from ToDo#1)

### E3. NVML on this host: most fields work, ECC and remap do not

- **Problem**: Uncertainty about which telemetry fields would be available inside the WSL2 container.
- **Cause**: Measured with `nvidia-ml-py` in the container on Quadro RTX 6000, driver 596.72: temperature, slowdown and shutdown thresholds (91 and 94 C), fan speed, power, clocks, utilisation, memory, pstate, clocks event reasons, PCIe, VBIOS, retired pages all return values. `nvmlDeviceGetTotalEccErrors` and `nvmlDeviceGetRemappedRows` return `Not Supported` because ECC is disabled and Turing uses page retirement rather than row remapping.
- **Fix**: Telemetry stores `null` for unsupported fields; ECC and remap rules evaluate to N/A on this host.
- **Rule**: Always probe NVML field support per GPU at preflight and store `null` rather than failing; never assume ECC or remap counters exist. (from ToDo#1)

### E4. Tool binaries need driver libraries even for `--help`

- **Problem**: `gpu_burn -h` and `cuda_memtest --help` failed in the runtime image without `--gpus`: `error while loading shared libraries: libcuda.so.1` (and `libnvidia-ml.so.1`).
- **Cause**: Both binaries link the driver libraries directly; the NVIDIA container toolkit mounts them only when a GPU is attached, so a CI runner has none.
- **Fix**: Copied the CUDA toolkit stubs into `/opt/cuda-stubs` (outside the default search path) and run the smoke test with `LD_LIBRARY_PATH=/opt/cuda-stubs`. `cuda_memtest --help` prints usage and exits 25, so CI greps the output instead of trusting the status.
- **Rule**: Never assume a CUDA tool runs without a GPU; use the stubs for `--help` checks and match on output, not exit code. (from ToDo#3)

### E5. Git Bash rewrites container paths passed to docker

- **Problem**: `docker run ... ls /opt/gpu-burn/` reported `C:/Program Files/Git/opt/gpu-burn/: No such file`.
- **Cause**: MSYS path conversion turns leading-slash arguments into Windows paths before docker sees them.
- **Fix**: `export MSYS_NO_PATHCONV=1` for docker commands, and pass volume sources as `$(cygpath -w "$PWD")`.
- **Rule**: Always set `MSYS_NO_PATHCONV=1` when a docker command carries container-side paths from Git Bash. (from ToDo#3)
