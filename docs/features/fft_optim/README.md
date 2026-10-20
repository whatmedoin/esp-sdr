# ESP32-S31 FFT optimization

## Summary

Improve on-chip FFT coverage without changing the serial protocol or power calculations. At 80 MSps, 2048-point throughput increased from about 3,083 to 4,350 FFT/s, while 256-point throughput reached about 41,500 FFT/s with 13.2% coverage. The main retained improvements are larger capture-bank units, exact power/unpack scheduling, specialized FFT stages, and multi-window prefetch using the existing workspace; numeric and compatibility checks passed.

## Test setup

- Hardware: ESP32-S31 Function-CoreBoard v0.0, dual-core 320 MHz, 16 MB physical flash, native USB Serial/JTAG connection through USB-DBG.
- Host: EndeavourOS; ESP-IDF Python environment using Python 3.12.13.
- Toolchain: ESP-IDF 6.2 preview, commit `26dd2948925d44f41e3bb614fb044b7a0839a242`, with the repository's ESP-DSP submodule.
- Firmware profile: ESP32-S31 burst receiver with `sdkconfig.defaults.esp32s31`.
- Supported measurements: 256/512/1024/2048 FFT points at 80/40/20/10/8/4 MSps, with mean and maximum detectors.

Core 0 rotates capture banks and handles USB. Core 1 unpacks and windows samples, computes the fixed-point FFT, applies DC correction, and accumulates power. All retained DSP work remains on core 1.

The final controlled comparisons fixed both implementations to 2412 MHz, manual gain 40, LPF AUTO, and the DC tracker enabled. Earlier exploratory measurements did not all record or control the RF settings, so their values describe individual experiments rather than a single fully controlled comparison across the entire investigation.

Initialize the dependency and build the normal configuration from the repository root:

```sh
git submodule update --init --recursive
docs/features/fft_optim/build_s31.sh -DS31_FFT_VERIFY=OFF
```

A representative five-second, 80 MSps, 2048-point mean request with statistics enabled is:

```text
SPEC 5000 8 64 0 0 2048 1
```

The fields are duration, legacy stride, legacy units-per-frame, detector, rate code, FFT size, and statistics flag. Rate codes 0-5 select 80/40/20/10/8/4 MSps; detector 0 selects mean and 1 selects maximum. The S31 processes as many windows as bank ownership permits, forces stride 1, and emits accumulated results when output is available; the legacy stride and units fields do not determine its processing rate.

Reported FFT/s comes from in-run `SPS1` telemetry, excluding final USB-drain time. Coverage is the fraction of captured samples analyzed, quantized in per mille; processing-load counters measure capture-processing work rather than general RTOS CPU usage. `work_max` measures maximum CPU work for one completed window; with prefetch, copy and DSP durations are summed rather than including time spent waiting inside a private batch.

Protocol details are documented in [On-chip spectra](../../spectrum.md). The historical validation and its limits are summarized in [TESTS.md](TESTS.md).

## Initial state

The reference source revision was `f86da81807b7f6e850742f6b789d9468c190ad41`, reporting `S31SDR 6 burst 16380`. Continuous capture was already working, but the CPU analyzed only a small part of the incoming stream.

| Sample rate | FFT points | Initial FFT/s | Initial coverage |
|---:|---:|---:|---:|
| 80 MSps | 2048 | 3,083 | 7.8% |
| 40 MSps | 2048 | 3,251 | 16.6% |
| 20 MSps | 2048 | 3,795 | 38.8% |
| 10 MSps | 2048 | 3,796 | 77.7% |
| 8 MSps | 2048 | 3,901 | 99.8% |
| 4 MSps | 2048 | 1,952 | 99.9% |
| 80 MSps | 1024 | 6,218 | 7.9% |
| 80 MSps | 256 | 25,980 | 8.3% |

A 2048-point window required roughly 78,000-80,000 cycles. Core-1 processing load was about 85% at 80 MSps and nearly saturated at lower, compute-limited rates. The initial diagnostic attributed about 27,500 cycles per 2048-point window to power accumulation; that figure predates the optimized assembly and is not a current stage measurement.

The low coverage was not explained by transport loss: output queues were generally short, no transport drops were observed, and capture lateness was small. Reducing FFT size increased the number of transforms per second but did not proportionally increase the number of analyzed samples.

## Flashing procedure and recovery

Disconnect the Web-UI and any other serial client before flashing or using the measurement scripts. Set the port to the currently enumerated native USB device; `/dev/ttyACM0` and `/dev/ttyACM1` below are examples, not fixed assignments.

1. Build the current source with `build_s31.sh`.
2. Hold BOOT, tap RESET, release BOOT, and reconnect if needed to enter download mode.
3. Run the flash helper with the current port. It uses the S31 ROM downloader with `--no-stub`, leaves download mode active after writing, and then starts the application with a watchdog reset.
4. Rescan the port after reset before reconnecting the viewer or running a probe.

```sh
docs/features/fft_optim/flash_s31.sh /dev/ttyACM0
```

If only a restart from download mode is needed, activate the ESP-IDF environment and use:

```sh
python -m esptool --chip esp32s31 -p /dev/ttyACM0 --before no-reset --after watchdog-reset run
```

Do not use `--after hard-reset`, `--after soft-reset`, or a USB-level reset as substitutes. Hard reset produced a native-USB protocol error, soft reset was unsupported on this S31 setup, and USB-level reset could disconnect the board without re-enumeration.

If the application boot-loops or stops responding, re-enter download mode with BOOT and RESET, revert the failed source change, rebuild, and flash again. Do not depend on an old build remaining available. `ERR spectrum_memory` indicates allocation failure: check memory capabilities and placement rather than assuming that total free heap guarantees a suitable fast-memory block.

## Changes tested and impact

### 1. Bypass power accumulation - diagnostic only

**Impact:** Throughput rose from 3,083 to 5,575 FFT/s and coverage from 7.8% to 14.5%, but emitted powers were invalid. The change was not retained.

**Change:** Temporarily omit power calculation to identify how much processing time it consumed.

**Details:** `work_max` fell from 80,127 to 52,626 cycles for 2048 points, isolating accumulation as a major initial cost. This was a timing experiment, not a usable optimization.

### 2. Static 64-bit accumulator - rejected

**Impact:** Adding a 16 KiB static accumulator caused a boot loop. The change was reverted.

**Change:** Store accumulated powers in a larger, statically allocated array.

**Details:** The array shifted the static memory layout. The exact failure cause was not established, so large static additions should not be treated as safe without checking placement and boot behavior.

### 3. Low-power SRAM accumulator - rejected

**Impact:** Throughput collapsed to about 86 FFT/s and 0.2% coverage. The change was reverted.

**Change:** Allocate the larger accumulator dynamically instead of placing it in static storage.

**Details:** An internal-memory allocation landed in low-power SRAM, where this access pattern was prohibitively slow. Internal memory alone is not a sufficient allocation requirement for the hot path.

### 4. DMA-capable SRAM accumulator - rejected

**Impact:** The working variant reached about 3,008 FFT/s, with no throughput improvement. The change was not retained.

**Change:** Require fast DMA-capable memory and use a smaller accumulator if the larger allocation failed.

**Details:** A 16 KiB allocation failed, while an 8 KiB scaled 32-bit buffer succeeded. Periodic flushing and extra memory traffic offset the cheaper accumulation operations.

### 5. Scaled integer mean accumulation - rejected

**Impact:** Throughput remained about 3,097 FFT/s despite lower reported work per FFT. Reduced mean-power precision made the tradeoff unsuitable.

**Change:** Reuse the existing power workspace for a smaller integer representation.

**Details:** The experiment scaled powers down by four bits and limited accumulation to short batches. The final implementation instead retains exact squares and floating-point mean accumulation.

### 6. Fixed frame-batch target - rejected

**Impact:** A 16-FFT emission target produced about 3,101 FFT/s, effectively unchanged, and increased latency. The original emission policy was restored.

**Change:** Accumulate a fixed number of transforms before sending another spectrum packet.

**Details:** Changing packet batching did not materially improve this tested configuration. Packet rate is not itself the coverage metric, and the retained firmware still batches according to output availability.

### 7. Unmodified vendor FFT kernel - rejected

**Impact:** Throughput increased to about 3,233 FFT/s, but output compatibility was not established. The project kernel was retained.

**Change:** Substitute the vendor SIMD FFT for the project's corrected version.

**Details:** The project kernel includes final-stage coverage and rounding corrections. A replacement cannot be accepted on speed alone without preserving those guarantees and checking every output bin.

### 8. Higher compiler optimization for accumulation - rejected

**Impact:** Applying `-O3` to accumulation produced about 3,085 FFT/s, with no meaningful gain. The original compiler settings were restored.

**Change:** Ask the compiler to optimize the existing C accumulation loop more aggressively.

**Details:** This did not resolve the loop's costs; the later explicitly scheduled assembly implementation did.

### 9. Dynamic bank-processing unit - retained

**Impact:** At 80 MSps and 2048 points, throughput increased from 3,083 to about 3,421 FFT/s and coverage from 7.8% to 8.9%. Per-FFT work was essentially unchanged.

**Change:** Hand the worker a slightly larger portion of each capture bank.

**Details:** The retained unit is 14,336 samples, except at 1024 points where 12,288 samples performed better. This reduces rotation/job overhead without changing the bank deadline rules; the unit size and first-unit iteration counter remain separate variables.

### 10. Separate SIMD power passes - rejected

**Impact:** The tested variants reached about 3,286 and 3,334 FFT/s, below the then-current 3,421 FFT/s baseline. Neither was retained.

**Change:** Square several IQ values at once, then combine their powers in C.

**Details:** Eight-bin and 64-bin chunks were tested. Pair reduction, temporary storage, and call/scheduling overhead consumed the vector gain; the tested precision/performance tradeoff was not accepted.

### 11. Core-0 whole-FFT assistance - rejected

**Impact:** The first 20 MSps run hung without producing frames. The change was reverted.

**Change:** Let the capture core compute one complete FFT while core 1 worked on another.

**Details:** The prototype used a private copy and a small state-based handoff. The exact deadlock was not proven; scheduling, ownership, and run-end handling were not sufficiently safe to retain the design.

### 12. Non-blocking core-0 FFT assistance - rejected

**Impact:** Removing core-1 waits did not prevent the hang. The change was reverted.

**Change:** Allow core 1 to continue locally rather than wait for an assisted FFT.

**Details:** This showed that the explicit wait loop was not the only possible cause. Concurrent use of the FFT path and capture-core scheduling were not established as safe; no unproven hardware explanation is relied on by the retained implementation.

### 13. Core-0 power assistance with two fast buffers - not activated

**Impact:** The second allocation failed, so assistance stayed disabled and throughput remained near the existing baseline. The prototype was removed.

**Change:** Keep FFTs on core 1 and move only power calculation to core 0.

**Details:** The design required two 8 KiB DMA-capable buffers. Available total heap did not imply that both suitably placed blocks could be allocated.

### 14. Core-0 power assistance with low-power storage - rejected

**Impact:** The activated path produced about 185 FFT/s and exited with bank-boundary mismatch status 4. It was not retained.

**Change:** Use ordinary internal memory for one assist buffer when fast memory was insufficient.

**Details:** The slow-memory fallback and cross-core handoff did not provide a usable path. Capture timing and correct ownership take precedence over activating assistance.

### 15. Split assist allocations - not activated

**Impact:** Splitting the power storage still did not fully activate assistance or improve throughput. The prototype was removed.

**Change:** Replace one large allocation with smaller DMA-capable blocks.

**Details:** Fast-memory availability remained insufficient for the complete design. The eventual successful prefetch instead reused already allocated workspace and introduced no cross-core DSP handoff.

### 16. Exact core-1 pipeline scheduling - retained

**Impact:** The combined changes increased 80 MSps/2048-point throughput from about 3,471 to 3,953 FFT/s, approximately 14%. Numeric comparisons passed bit-for-bit.

**Change:** Compute the same results with less memory traffic and better instruction scheduling.

**Details:** The last two FFT stages are fused in registers, unpack shift setup is shared across eight samples, and a four-bin assembly loop schedules integer squares and floating-point accumulation independently. FFT fusion alone had little measured effect; unpack scheduling reached roughly 3,570 FFT/s, and the exact power loop supplied most of the remaining gain. Original Q15 rounding, unsigned power up to 2^31, and mean/max behavior are preserved without another workspace.

### 17. Streaming short FFT stages - retained

**Impact:** At 80 MSps and 2048 points, throughput increased from about 3,953 to 4,349 FFT/s, another 10%. At 10 MSps, 2048-point coverage rose from 90.4% to 95.2%, while 512/1024-point modes reached essentially full coverage.

**Change:** Give the smallest remaining general-loop stages a simpler, direct processing path.

**Details:** Dedicated N2=8 and N2=4 loops stream through data and twiddles instead of rebuilding every group's addresses and repeatedly setting up short inner loops. Butterfly arithmetic, rounding, and the fused final stages are unchanged.

### 18. Bounded multi-window prefetch - retained

**Impact:** Controlled 80 MSps throughput increased by 24.3% at 256 points, 23.7% at 512 points, and 35.9% at 1024 points relative to the preceding implementation. The 2048-point path was effectively unchanged, with no material regression across the controlled matrix.

**Change:** Copy several small windows while their capture bank is readable, then process those private copies even after the bank is reclaimed.

**Details:** The existing 8 KiB FFT workspace holds 8/4/2/1 windows at 256/512/1024/2048 points. Copying keeps the original 128-sample ownership checks and wrap guards; complete windows are processed in order, incomplete windows are excluded, and final private batches drain on stop. Exploratory depths two and four did not preserve the observed depth-eight gains, although those sweeps were not fully RF-controlled. The retained capacity-based depth was separately validated with identical RF settings, no extra heap/static buffer, and no core-0 DSP.

## Conclusion

The retained changes improve both arithmetic efficiency and capture-bank utilization while preserving the original serial protocol, FFT scaling, DC correction, and mean/max calculations. All DSP remains on core 1; rejected memory and assistance experiments are not part of the final implementation.

Final controlled mean-detector results were:

| Sample rate | FFT points | Final FFT/s | Final coverage |
|---:|---:|---:|---:|
| 80 MSps | 256 | 41,541 | 13.22% |
| 80 MSps | 512 | 19,818 | 12.61% |
| 80 MSps | 1024 | 8,996 | 11.49% |
| 80 MSps | 2048 | 4,350 | 11.10% |
| 40 MSps | 256 | 41,878 | 26.76% |
| 40 MSps | 2048 | 4,377 | 22.36% |
| 20 MSps | 256 | 42,738 | 54.66% |
| 20 MSps | 2048 | 4,598 | 47.07% |
| 10 MSps | 256 | 39,015 | 99.81% |
| 10 MSps | 512 | 19,506 | 99.81% |
| 10 MSps | 1024 | 9,753 | 99.81% |
| 10 MSps | 2048 | 4,644 | 95.07% |
| 8 MSps | 2048 | 3,901 | 99.79% |
| 4 MSps | 2048 | 1,950 | 99.80% |

Two controlled five-second runs confirmed roughly 41,700 FFT/s for 256 points at 80 MSps. The final prefetch comparison passed all 48 rate/size/detector combinations on both implementations; its largest negative throughput difference was 0.24%, within the observed small run-to-run variation. No transport drops or bank failures occurred in those checks.

Coverage is approximately `FFTs/s * FFT_points / sample_rate`, not the viewer's `spectra/s` packet count. A packet can represent many transforms, and smaller packets can arrive much more often without a proportional coverage increase. Full 80 MSps coverage at 2048 points would require 39,062.5 FFT/s, so it remains far beyond the final measured rate; 10 MSps is effectively fully covered at smaller FFT sizes, while 2048 points remain near 95%.

The final configuration uses `S31_FFT_VERIFY=OFF`. Validation results and the boundaries of the compatibility claims are recorded in [TESTS.md](TESTS.md).

## Files modified

- `main/targets/esp32s31/burst/s31_spectrum.h`: dynamic bank units, scheduled accumulation integration, bounded prefetch/drain, and optional verification hooks.
- `main/targets/esp32s31/burst/s31_prefetch.h`: bounded window copying into the existing private FFT workspace.
- `main/targets/esp32s31/burst/s31_fft_rnd.S`: fused final stages and streaming N2=8/N2=4 stages.
- `main/targets/esp32s31/burst/s31_unpack.S`: shared shift setup across pairs of vectors.
- `main/targets/esp32s31/burst/s31_power.S`: exact scheduled mean/max power accumulation.
- `main/targets/esp32s31/burst/linker.lf`: hot assembly placement in fast internal SRAM.
- `main/CMakeLists.txt`: assembly sources and the optional `S31_FFT_VERIFY` configuration.
- `tests/s31_fft_reference.S`: preserved pre-optimization project FFT source for comparison.
- `tests/s31_fft_verify.h`: on-device FFT, power, and unpack comparisons.
- `tests/s31_prefetch_verify.h`: on-device ordered prefetch/DC/detector comparisons after bank reclamation.
- `tests/test_s31_prefetch.py`: host ownership, revocation, wrap, bounds, and accounting checks.

## Scripts

All commands below are examples for later use, not tests run during the documentation cleanup. Build/flash helpers activate the configured ESP-IDF environment; Python serial tools require `pyserial` and exclusive access to the board. For the last command, set `REPORT` to a new destination for its generated JSON report.

- [build_s31.sh](build_s31.sh): builds the S31 burst profile and accepts additional CMake arguments. Set `IDF_PATH`, `IDF_TOOLS_PATH`, or `BUILD_DIR` when the defaults do not match the local installation; explicitly select verification OFF for normal measurements because CMake caches options.
- [flash_s31.sh](flash_s31.sh): flashes the current build to a board already in download mode, then starts it with a watchdog reset. `IMAGE_DIR` can select another current build directory; do not assume that an old build is usable.
- [spec_probe.py](spec_probe.py): performs one bounded SPEC request, checks packet CRCs, and prints FFT/frame totals, coverage, load, drops, and the end report. Its top-level wall-clock FFT/s includes output drain; use in-run statistics for comparisons with the tables above.
- [prefetch_checks.py](prefetch_checks.py): exercises short captures, immediate/delayed stops, both detectors/DC modes, statistics-disabled requests, packet fields/CRCs, final window accounting, and command access after capture. It requires an output path for a newly generated report.

```sh
docs/features/fft_optim/build_s31.sh -DS31_FFT_VERIFY=OFF
python3 docs/features/fft_optim/spec_probe.py --port /dev/ttyACM0 --ms 5000 --rate 0 --nfft 256 --detector 0
python3 docs/features/fft_optim/spec_probe.py --port /dev/ttyACM0 --ms 5000 --nfft 2048 --no-stats
python3 docs/features/fft_optim/prefetch_checks.py --port /dev/ttyACM0 --output "$REPORT"
```
