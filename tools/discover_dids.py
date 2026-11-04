#!/usr/bin/env python3
"""discover_dids.py -- exhaustive ReadDataByIdentifier (service 0x22) scan
across the known modules in MODULES (uds_iso_tp.py), looking for DIDs
your car responds to beyond whatever's already confirmed in
docs/FINDINGS.md.

Logs every positive response (0x62 prefix) and any negative response with
an unusual NRC (not the routine "DID doesn't exist here" codes) to a
per-module log file, with periodic progress printed to stdout.

Pairs with firmware/uds_bridge.ino. Only ever sends ReadDataByIdentifier
-- read-only, can't command or control anything on the car.

Don't know your car's module IDs yet? Run discover_modules.py first.

Usage:
    python discover_dids.py --port COM6
    python discover_dids.py --port COM6 --module 720
    python discover_dids.py --port COM6 --start 2A00 --end 2AFF

A full scan of all known modules across the whole 16-bit DID range takes
several hours -- narrow it with --module and/or --start/--end once you
have a specific hunch about where to look.
"""
import argparse
import sys
import time

from uds_iso_tp import RawBridge, uds_request, MODULES

# NRCs that just mean "this DID isn't implemented here" -- routine, not
# interesting. Anything else (e.g. securityAccessDenied) gets logged too,
# since it means the DID exists but is gated.
ROUTINE_NRC = {0x11, 0x12, 0x31}


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default="COM6", help="serial port the Arduino is on (default: COM6)")
    ap.add_argument("--module", default=None,
                     help="only scan this module's request ID, e.g. 720 (default: all known modules)")
    ap.add_argument("--start", default="0000", help="first DID to try, hex, no 0x prefix (default: 0000)")
    ap.add_argument("--end", default="FFFF", help="last DID to try, hex, no 0x prefix (default: FFFF)")
    return ap.parse_args()


def scan_module(bridge, req_id, resp_id, did_start, did_end, logfile, report_every=500):
    hits = []
    t0 = time.time()
    with open(logfile, "a") as f:
        for did in range(did_start, did_end + 1):
            payload = bytes([0x22, (did >> 8) & 0xFF, did & 0xFF])
            resp = uds_request(bridge, req_id, resp_id, payload, timeout=0.1)
            if resp is None:
                # one retry to rule out a transient miss
                resp = uds_request(bridge, req_id, resp_id, payload, timeout=0.15)

            if resp is None:
                continue
            if len(resp) >= 1 and resp[0] == 0x62:
                line = f"DID {did:04X}: POSITIVE {resp.hex().upper()}"
                hits.append((did, resp))
                print(f"  [{req_id}] {line}", flush=True)
                f.write(line + "\n")
                f.flush()
            elif len(resp) >= 3 and resp[0] == 0x7F and resp[2] not in ROUTINE_NRC:
                line = f"DID {did:04X}: NEG (unusual NRC 0x{resp[2]:02X}) {resp.hex().upper()}"
                hits.append((did, resp))
                print(f"  [{req_id}] {line}", flush=True)
                f.write(line + "\n")
                f.flush()

            if (did - did_start) % report_every == 0 and did != did_start:
                elapsed = time.time() - t0
                rate = (did - did_start) / elapsed
                remaining = (did_end - did) / max(rate, 0.01)
                print(f"  [{req_id}] {did:04X}/{did_end:04X}  "
                      f"({rate:.1f} did/s, ~{remaining/60:.1f} min left)", flush=True)
    return hits


def main():
    args = parse_args()
    did_start = int(args.start, 16)
    did_end = int(args.end, 16)

    if args.module and args.module not in MODULES:
        sys.exit(f"Unknown module {args.module!r}. Known: {', '.join(MODULES)} "
                  f"(run discover_modules.py to find others on your car).")

    modules = {args.module: MODULES[args.module]} if args.module else MODULES

    bridge = RawBridge(args.port)
    time.sleep(0.5)

    all_hits = {}
    for req_id, resp_id in modules.items():
        print(f"\n=== scanning module {req_id} (resp {resp_id}), DIDs {did_start:04X}-{did_end:04X} ===",
              flush=True)
        logfile = f"discover_dids_{req_id}.log"
        hits = scan_module(bridge, req_id, resp_id, did_start, did_end, logfile)
        all_hits[req_id] = hits
        print(f"  {len(hits)} hit(s) for module {req_id}", flush=True)

    bridge.close()

    print("\n=== summary ===")
    for req_id, hits in all_hits.items():
        print(f"{req_id}: {len(hits)} hit(s)")


if __name__ == "__main__":
    main()
