#!/usr/bin/env python3
"""Run one bounded S31 SPEC request and print coverage telemetry.

The device must be running the burst firmware and must not be owned by another
client. The script only uses the documented text/binary spectrum protocol.

Example:
    python3 spec_probe.py --port /dev/ttyACM0 --ms 5000
"""

import argparse
import json
import time
import zlib

import serial


def read_exact(port, count):
    data = bytearray()
    while len(data) < count:
        chunk = port.read(count - len(data))
        if not chunk:
            raise TimeoutError(f"short read: {len(data)}/{count}")
        data.extend(chunk)
    return bytes(data)


def command(port, text):
    port.write((text + "\n").encode("ascii"))
    return port.readline().decode("ascii", errors="replace").strip()


def sync_release(port):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        port.write(b"\nRELEASE\n")
        line = port.readline().strip()
        if line == b"OK":
            return
        if line:
            continue
        time.sleep(0.1)
    raise TimeoutError("could not acquire the serial lease")


def u16(buf, offset):
    return int.from_bytes(buf[offset:offset + 2], "little")


def u32(buf, offset):
    return int.from_bytes(buf[offset:offset + 4], "little")


def probe(args):
    port = serial.Serial(args.port, args.baud, timeout=5)
    try:
        sync_release(port)
        port.reset_input_buffer()

        identity = command(port, "INFO")
        transport = command(port, "TRANSPORT?")
        start = command(
            port,
            f"SPEC {args.ms} {args.stride} {args.units} {args.detector} "
            f"{args.rate} {args.nfft} {1 if args.stats else 0}",
        )
        if not start.startswith("SPEC "):
            raise RuntimeError(f"SPEC rejected: {start}")

        started = time.monotonic()
        frames = 0
        ffts = 0
        stats = []
        end = None

        while True:
            magic = read_exact(port, 4)
            if magic == b"SPEC":
                line = (magic + port.readline()).decode("ascii", errors="replace").strip()
                end = line.split()
                break
            if magic == b"SPS1":
                frame = magic + read_exact(port, 36)
                if zlib.crc32(frame[:-4]) != int.from_bytes(frame[-4:], "little"):
                    raise RuntimeError("SPS1 CRC mismatch")
                stats.append({
                    "core0": u16(frame, 4),
                    "core1": u16(frame, 6),
                    "coverage": u16(frame, 8),
                    "mode": u16(frame, 10),
                    "heap_free": u32(frame, 12),
                    "heap_largest": u32(frame, 16),
                    "abandoned": u32(frame, 20),
                    "drops": u32(frame, 24),
                    "late_max": u16(frame, 28),
                    "queue": u16(frame, 30),
                    "ffts_per_s": u32(frame, 32),
                })
                continue
            if magic == b"SPC1":
                frame = magic + read_exact(port, args.nfft + 28)
                if zlib.crc32(frame[:-4]) != int.from_bytes(frame[-4:], "little"):
                    raise RuntimeError("SPC1 CRC mismatch")
                frames += 1
                ffts += u16(frame, 20)
                continue
            raise RuntimeError(f"lost framing: {magic!r}")

        elapsed = time.monotonic() - started
        result = {
            "identity": identity,
            "transport": transport,
            "start": start,
            "elapsed_s": round(elapsed, 3),
            "frames": frames,
            "ffts": ffts,
            "fft_per_s": round(ffts / elapsed, 1) if elapsed else 0,
            "end": end,
            "stats": stats,
        }
        if stats:
            result["last_stats"] = stats[-1]
        return result
    finally:
        port.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=2000000)
    parser.add_argument("--ms", type=int, default=5000)
    parser.add_argument("--rate", type=int, default=0,
                        help="rate code: 0=80, 1=40, 2=20, 3=10, 4=8, 5=4 MSps")
    parser.add_argument("--nfft", type=int, default=2048)
    parser.add_argument("--stride", type=int, default=8)
    parser.add_argument("--units", type=int, default=64)
    parser.add_argument("--detector", type=int, choices=(0, 1), default=0,
                        help="0=mean, 1=max")
    parser.add_argument("--stats", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()
    print(json.dumps(probe(args), indent=2))


if __name__ == "__main__":
    main()
