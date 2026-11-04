#!/usr/bin/env python3
"""discover_modules.py -- scans a range of CAN IDs with a safe, read-only
UDS TesterPresent request (0x3E 0x00) to find which modules on your car
respond to diagnostic requests at all, before you know their IDs.

Pairs with firmware/uds_bridge.ino. Only ever sends TesterPresent -- never
ECUReset, WriteDataByIdentifier, RoutineControl, or SecurityAccess.

Usage:
    python discover_modules.py --port COM6
    python discover_modules.py --port COM6 --start 700 --end 7FF

Run with the car KEY ON, ENGINE OFF (KOEO) -- modules respond to
diagnostics without the engine running, and KOEO means less bus traffic
to wade through while you're looking for responses.
"""
import argparse
import time

from uds_iso_tp import RawBridge

TESTER_PRESENT = bytes([0x3E, 0x00])


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default="COM6", help="serial port the Arduino is on (default: COM6)")
    ap.add_argument("--start", default="700", help="first CAN ID to try, hex, no 0x prefix (default: 700)")
    ap.add_argument("--end", default="7FF", help="last CAN ID to try, hex, no 0x prefix (default: 7FF)")
    ap.add_argument("--timeout", type=float, default=0.15,
                     help="seconds to wait for a response per ID (default: 0.15)")
    return ap.parse_args()


def main():
    args = parse_args()
    start = int(args.start, 16)
    end = int(args.end, 16)

    bridge = RawBridge(args.port)
    time.sleep(0.5)

    print(f"Scanning CAN IDs {start:03X}-{end:03X} with TesterPresent -- Ctrl+C to stop early.\n")

    hits = []
    t0 = time.time()
    try:
        for req_id in range(start, end + 1):
            bridge.send_frame_exact(req_id, bytes([len(TESTER_PRESENT)]) + TESTER_PRESENT, 8)
            deadline = time.time() + args.timeout
            frame = bridge.poll_frame(deadline)
            if frame is not None:
                resp_id, dlc, data = frame
                hits.append((req_id, resp_id, data))
                print(f"  HIT  request 0x{req_id:03X} -> response 0x{resp_id:03X}: {data.hex().upper()}",
                      flush=True)

            if (req_id - start) % 32 == 0 and req_id != start:
                elapsed = time.time() - t0
                rate = (req_id - start) / elapsed
                remaining = (end - req_id) / max(rate, 0.01)
                print(f"  ...scanned up to 0x{req_id:03X}  ({elapsed:.0f}s elapsed, ~{remaining:.0f}s left)",
                      flush=True)
    except KeyboardInterrupt:
        print("\nstopped early.")
    finally:
        bridge.close()

    print(f"\nDone in {time.time()-t0:.1f}s. {len(hits)} module(s) found:")
    for req_id, resp_id, data in hits:
        print(f"  request 0x{req_id:03X} -> response 0x{resp_id:03X}")
    if hits:
        print("\nAdd these to MODULES in uds_iso_tp.py to use them with discover_dids.py.")


if __name__ == "__main__":
    main()
