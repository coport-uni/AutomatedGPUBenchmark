# Test fixtures

Each directory holds a `sysinfo.json` and a `telemetry.jsonl` in the
layout that `gpubench.analysis.loader` validates. `sysinfo.json` carries
`"synthetic": true` when the data was generated, so no report can pass
generated numbers off as a measurement (DevSpec section 4.6).

| Directory | Origin | Notes |
|---|---|---|
| `consumer/` | Synthetic, `claude_test/make_synthetic_fixtures.py` | One GeForce-class GPU; ECC and memory temperature are `null` |
| `datacenter/` | Synthetic, `claude_test/make_synthetic_fixtures.py` | Two H100-class GPUs; ECC and row-remap counters present, fan `null` |
| `workstation/` | Measured, `claude_test/capture_idle_fixture.py` | Two Quadro RTX 6000, idle only, 10 s, captured 2026-09-28 inside the runtime image on the Windows 11 / WSL2 development host |

Notes on the measured fixture:

- `memory.total_mib` and `os` describe the WSL2 virtual machine and the
  container, not the Windows host. This is what the tool sees at run time.
- `temp_mem`, `ecc_*`, and `remap_*` are `null` because ECC is disabled
  on these boards and Turing uses page retirement (LearnedPatterns E3).
- `clk_event_reasons` is `1`, the NVML "GPU idle" bit.

## Tool logs (`logs/`)

| File | Origin |
|---|---|
| `gpu_burn_quadro_rtx6000_x2_ok.log` | Measured: `gpu_burn 20` on both GPUs, 2026-09-28 |
| `cuda_memtest_quadro_rtx6000_dev0_ok.log` | Measured: `--device 0 --stress --num_passes 1 --num_iterations 20` |
| `cuda_memtest_quadro_rtx6000_dev1_terminated.log` | Measured: default tests on GPU 1, stopped by `timeout 300` during Test6 |
| `synthetic_gpu_burn_faulty.log` | Synthetic: written from the printf formats in gpu_burn-drv.cpp (3ead140); errors, a dead worker, FAULTY verdict, and a lost carriage return |
| `synthetic_cuda_memtest_errors.log` | Synthetic: written from the FPRINTF formats in tests.cpp (e94e1ee); block pattern errors |
