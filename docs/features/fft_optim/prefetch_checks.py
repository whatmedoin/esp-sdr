#!/usr/bin/env python3
"""Check bounded S31 runs, immediate/late host stops, and final private-window drain.

Disconnect other serial clients first. Uses only the existing serial protocol.
"""
import argparse
import json
import time
import zlib

import serial

from spec_probe import command, read_exact, sync_release, u16, u32


def capture(port_name, rate, nfft, detector, ms, stop_after, stats, dc):
    port = serial.Serial(port_name, 2000000, timeout=5)
    try:
        sync_release(port)
        port.reset_input_buffer()
        assert command(port, "INFO") == "S31SDR 6 burst 16380"
        saved_dc = command(port, "DC?").split()[1]
        assert command(port, f"DC {dc}") == "OK"
        start = command(port, f"SPEC {ms} 8 64 {detector} {rate} {nfft} {int(stats)}")
        assert start.startswith(f"SPEC {nfft} "), start
        unit = int(start.split()[3])
        started = time.monotonic()
        stop_sent = False
        frames = ffts = records = 0
        previous_index = -1
        while True:
            if stop_after is not None and not stop_sent and time.monotonic() - started >= stop_after:
                port.write(b"\n")
                stop_sent = True
            magic = read_exact(port, 4)
            if magic == b"SPEC":
                end = (magic + port.readline()).decode("ascii").strip().split()
                assert len(end) == 13 and end[:3] == ["SPECEND", "0", "0"], end
                break
            assert magic in (b"SPC1", b"SPS1"), magic
            frame = magic + read_exact(port, nfft + 28 if magic == b"SPC1" else 36)
            assert zlib.crc32(frame[:-4]) == u32(frame, len(frame) - 4)
            if magic == b"SPS1":
                assert stats
                records += 1
                continue
            assert u32(frame, 4) == frames and u16(frame, 24) == 0
            assert frame[26] == nfft.bit_length() - 1 and frame[27] == 2
            assert frame[22] & 1 == detector and not frame[22] & ~3
            index = int.from_bytes(frame[8:16], "little")
            assert index >= previous_index
            previous_index = index
            count = u16(frame, 20)
            assert count and count * nfft <= u32(frame, 16)
            frames += 1
            ffts += count
        assert frames and frames == int(end[8]) and ffts == int(end[11]), end
        assert end[9] == "0" and int(end[6]) <= 800, end
        assert ffts + int(end[10]) == int(end[3]) * (unit // nfft), end
        assert int(end[12]) == int(stop_after is not None and stop_sent), end
        assert command(port, "INFO") == "S31SDR 6 burst 16380"
        assert command(port, f"DC {saved_dc}") == "OK"
        return {"rate": rate, "nfft": nfft, "detector": detector, "ms": ms,
                "stop_after": stop_after, "stats": stats, "dc": dc,
                "frames": frames, "ffts": ffts, "stats_records": records, "end": end}
    finally:
        port.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    cases = []
    for rate in (0, 1, 3):
        for nfft in (256, 512, 1024, 2048):
            for k, stop in enumerate((None, 0, 0.025)):
                cases.append((rate, nfft, k % 2, 5 if stop is None else 0,
                              stop, k != 1, (rate + nfft // 256 + k) % 2))
    for nfft in (256, 512, 1024, 2048):
        for detector in (0, 1):
            cases.append((0, nfft, detector, 500, None, False, 1))
    results = []
    for case in cases:
        result = capture(args.port, *case)
        results.append(result)
        with open(args.output, "w") as out:
            json.dump(results, out, indent=2)
            out.write("\n")
        print(*case, "PASS", result["frames"], result["ffts"], flush=True)


if __name__ == "__main__":
    main()
