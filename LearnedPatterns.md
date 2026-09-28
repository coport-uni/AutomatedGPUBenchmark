# LearnedPatterns.md

> Patterns extracted from completed work. Consult the relevant sections
> before drafting new ToDo entries. Append new patterns after each task
> completes (see CommonClaude CLAUDE.md section 9).
>
> Last updated: 2026-09-28
> Total patterns: 9
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
