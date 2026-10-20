# ESP32-S31 FFT compatibility validation

## Scope and recorded outcome

This summarizes checks already performed during the FFT optimization work, through the retained multi-window prefetch implementation. No tests, builds, flashing, or firmware changes were performed for the documentation cleanup. The consolidated implementation and performance results are in [README_NEW.md](README_NEW.md).

The final host suite passed all 60 tests. On-device numeric comparisons, controlled native-USB spectrum matrices, short captures, host-stop/drain checks, and subsequent command access passed. These establish the compatibility described below, not a claim that every receiver feature was physically retested on every board or transport.

## Host unit and regression tests

The existing suite initially contained 59 tests; the prefetch regression added one test containing 1,279 ownership/bounds scenarios. The following command was used during implementation and was not rerun for this documentation update:

```sh
python3 -m unittest discover -s tests
```

| Area | Checks performed | Relevant existing sources |
|---|---|---|
| Prefetch ownership and bounds | All supported FFT sizes and fitting batch lengths; both banks; phases/strides; bank wrap; revocation at every chunk check and during a reader hold; exclusion of incomplete windows; valid copies surviving source reclamation; destination/timing canaries and window accounting | `tests/test_s31_prefetch.py` |
| FFT, power, and DC math | Complex tones, bin order, power-code quantization, mean/max accumulation, fixed-point overflow cases, DC-tracker behavior, saturation, and comparison with the established arithmetic | `tests/test_spectrum_math.py`, `tests/test_snapshot_spectrum.py` |
| Ring ownership | Retirement at processing boundaries, wrapped sentinel regions, and untouched neighboring memory | `tests/test_ring_retirement.py`, `tests/test_ring_sentinels.py` |
| Serial commands and parsing | Existing target command harnesses, strict argument validation, malformed/random inputs, capture packing, and S31-related production-parser checks | `tests/test_burst_commands.py`, `tests/test_burst_parse.py`, `tests/test_burst_capture.py`, `tests/test_tuning.py` |
| Receiver controls | Gain surviving receiver preparation, tuning/bandwidth handling, AGC/manual-gain restoration, and existing calibration state/rollback behavior in host harnesses | `tests/test_s31_gain.py`, `tests/test_rx_controls.py`, `tests/test_rx_recalibration.py`, `tests/test_rx_calibration_state.py`, `tests/test_dc_calibration.py` |
| Other existing regressions | GPIO, version/metadata, firmware export/collection, and other target-specific command and recovery checks | The remaining tests under `tests/` |

The prefetch helper was compiled with AddressSanitizer and UndefinedBehaviorSanitizer; all 1,279 scenarios passed. Its simulated reader/revocation events exercised the actual helper code, including poisoning reclaimed source memory before consuming complete copies. Other tests retained their existing host harnesses; passing them is host-level regression evidence rather than physical validation of another chip.

## On-device numerical compatibility

`S31_FFT_VERIFY=ON` enabled assertion-based checks on core 1 before capture work was accepted. Assertions were required; the verifier rejected `NDEBUG`. The reference was the original project FFT, including its final-stage and rounding corrections, not the unmodified vendor replacement.

| Check | Recorded cases | Inputs and comparisons |
|---|---:|---|
| Complete FFT equivalence | 288 | All four sizes; zeros, signed extrema, alternating extrema, a last-eight-sample impulse, a complex tone, and deterministic random IQ; every output compared bit-for-bit |
| Power-buffer equivalence | 256 | Mean and maximum across all sizes; unsigned power up to 2^31 and nonzero prior accumulators; exact float-buffer comparison |
| SIMD unpack equivalence | 160 | Four source word alignments; 1/2/4/8/16 groups; signed samples, upper metadata bits, full-scale/random windows; comparison with scalar IQ10/window arithmetic |
| Complete prefetched batches | 336 | 256/512/1024 points, all fitting batch lengths, both banks, wrap positions, both DC modes, and both detectors |
| Already-revoked prefetch | 336 | No complete window accepted and reader ownership released |
| Ordered prefetched DSP | 1,176 windows | Source banks overwritten before DSP; windowed samples, corrected FFT output, DC state, and accumulated powers compared with sequential scalar windowing plus the preserved FFT kernel |

All numerical comparisons passed. The verifier reused existing FFT/window/power workspaces rather than adding large static buffers. The normal configuration used for final performance and protocol checks had verification OFF; the reference and verification routines were excluded from that configuration.

The relevant sources are `tests/s31_fft_reference.S`, `tests/s31_fft_verify.h`, and `tests/s31_prefetch_verify.h`. Equivalence applies to identical input windows processed in identical order; increased coverage intentionally changes which live-RF windows contribute to an emitted mean/max result, so live packets need not be byte-identical to packets from the slower receiver.

## Native-USB integration and protocol compatibility

Earlier optimization stages used 24-case matrices covering all sizes at 80/10 MSps and 2048 points at the remaining rates, with both detectors. The final prefetch comparison expanded this to every combination of six sample rates, four sizes, and two detectors: 48 two-second requests on the preceding implementation and 48 on the retained implementation.

The final comparison explicitly matched 2412 MHz, manual gain 40, LPF AUTO, and DC tracker mode 1 on both implementations. This replaced preliminary performance comparisons whose RF settings were not all controlled. Both implementations accepted the same control commands and returned matching gain/filter settings.

The stream checks verified:

- Successful SPEC start replies and normal SPECEND status/detail.
- Valid SPC1 and SPS1 CRC32 values with the existing packet layouts.
- Frame/FFT totals matching the final end report, with zero transport drops.
- Selected-window accounting: completed plus abandoned work matched the tested capture units, including queue skips and final drain.
- Optional statistics remaining optional, including requests with statistics disabled.
- Healthy bank timing: final matrix lateness did not exceed 14 samples.

The retained [prefetch_checks.py](prefetch_checks.py) performed a further 44 hardware requests. These comprised 24 immediate/delayed host stops and 20 finite requests, including five-millisecond captures and eight statistics-disabled 500 ms captures. It exercised all four sizes at representative rates, both detectors, and both DC modes.

Those 44 checks verified sequential packet numbering, detector/gap flags, FFT-size and power-step fields, CRCs, monotonic sample indices, valid sample spans, completed-FFT counts, correct stop reason, zero drops, and final window accounting. Complete private windows drained after stop or bank reclamation, incomplete copies were not counted, and INFO worked immediately after every run. The script restored the saved DC mode after each successful request.

Additional checks during the optimization work exercised INFO, TRANSPORT?, RELEASE, SPECINFO?, invalid SPEC argument rejection, and INFO recovery after rejection. The final controlled setup also exercised FREQ, GAIN MANUAL, GAIN?, LPF AUTO, LPF?, DC, and DC?. The INFO identity remained `S31SDR 6 burst 16380`; no new diagnostic command or repurposed SPC1/SPS1 field was introduced.

## Repeated and longer captures

The short-stage implementation passed 12 additional five-second 2048-point requests at 80/10 MSps with both detectors. Prefetch testing added 18 five-second stress requests covering both detectors at 256 points across 80/40/20 MSps and 512/1024/2048 points at 80 MSps; CRC, status, drop, and count checks passed.

Six final controlled five-second mean requests repeated the 256-point measurement twice at 80/40/20 MSps. They confirmed approximately 41,700, 41,850, and 42,750 FFT/s respectively, with valid streams and exact final window accounting. Across the controlled 48-case comparison, no material throughput regression was observed; the largest negative difference was 0.24%.

## Compatibility boundaries

The physical validation focused on continuous S31 spectra over native USB. UART snapshots, Ethernet streaming, every raw-IQ capture format, every analog gain/bandwidth setting, and other ESP32 boards were not exhaustively retested on hardware as part of this optimization. Existing host regressions for parsers, packing, snapshot math, receiver controls, calibration, and other targets continued to pass, but do not substitute for that hardware coverage.

Valid-stream CRC checking was performed; this is not a claim that corrupted-stream injection, arbitrary USB disconnects, or every host-stall recovery path was newly tested. Failed assistance/allocation prototypes were reverted and are not covered by the final implementation's passing results.

All test results above are historical. Reproduction tools remain available in this directory, but none were run during this documentation-only update.
