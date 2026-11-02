#!/usr/bin/env python3
"""
record_drive.py -- records a driving session straight to a CSV file in
the format hud_overlay/render_overlay.py expects
(time,throttle,brake,steering_deg,speed,rpm,gear,gear_raw).

Pairs with firmware/can_live.ino. Start it before you drive, stop it
(Ctrl+C) when you're done -- no need to watch the screen while moving.

Usage:
    python record_drive.py [--port PORT] [--rate HZ] [--out FILE.csv]

Example:
    python record_drive.py --port COM6 --rate 20 --out my_drive.csv

Decode formulas (see docs/FINDINGS.md for the full writeup):
    rpm:          0x201 bytes 0-1, raw = RPM directly
    throttle:     0x201 byte 6, raw/255*100 (0-100%)
    brake:        0x20F bytes 0-1, raw-30000 clamped to 0
    speed:        0x20F bytes 2-3, (raw-10000)/100 km/h -> mph
    steering_deg: 0x082 bytes 2-3, signed16/10 deg
    gear:         0x231 byte 0 via lookup table, overridden to -1
                  (reverse) when the 0x433 reverse bit is set
"""
import argparse
import re
import sys
import time

import serial

LINE_RE = re.compile(r"^\d+\s+([0-9A-Fa-f]{3})\s+\[\d+\]\s+([0-9A-Fa-f ]+)$")
KMH_TO_MPH = 0.621371

GEAR_LOOKUP = {
    0x00: 0, 0x01: 0,   # neutral (moving / stopped)
    0x11: 1, 0x20: 2, 0x30: 3, 0x40: 4, 0x50: 5, 0x60: 6,
}


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default="COM6",
                     help="serial port the Arduino is on (default: COM6; "
                          "on Linux/Mac it'll look like /dev/ttyUSB0 or /dev/tty.usbserial-...)")
    ap.add_argument("--rate", type=float, default=20.0, help="log rate in Hz (default: 20)")
    ap.add_argument("--out", default="drive_log.csv", help="output CSV path (default: drive_log.csv)")
    return ap.parse_args()


def main():
    args = parse_args()
    period = 1.0 / args.rate

    try:
        ser = serial.Serial(args.port, baudrate=1000000, timeout=0.05)
    except serial.SerialException as e:
        print(f"Couldn't open {args.port}: {e}", file=sys.stderr)
        sys.exit(1)

    rpm = 0
    throttle = 0.0
    brake = 0
    speed = 0.0
    steering_deg = 0.0
    gear = 0
    gear_raw = 0x01
    reverse = False

    print(f"Logging to {args.out} at {args.rate:.0f} Hz -- Ctrl+C to stop.")
    print("Drive your session now. No need to watch this screen while moving.\n")

    rows = 0
    unknown_gear_codes = set()
    t0 = time.time()
    next_tick = t0

    with open(args.out, "w", newline="") as f:
        f.write("time,throttle,brake,steering_deg,speed,rpm,gear,gear_raw\n")
        try:
            while True:
                deadline = next_tick
                while time.time() < deadline:
                    line = ser.readline()
                    if not line:
                        continue
                    text = line.decode(errors="replace").strip()
                    m = LINE_RE.match(text)
                    if not m:
                        continue
                    can_id = m.group(1).upper()
                    data = [int(b, 16) for b in m.group(2).split()]

                    if can_id == "201" and len(data) >= 7:
                        rpm = (data[0] << 8) | data[1]
                        throttle = round(data[6] / 255.0 * 100.0, 1)
                    elif can_id == "20F" and len(data) >= 4:
                        rawf = (data[0] << 8) | data[1]
                        brake = max(0, rawf - 30000)
                        raws = (data[2] << 8) | data[3]
                        speed = round((raws - 10000) / 100.0 * KMH_TO_MPH, 1)
                    elif can_id == "082" and len(data) >= 4:
                        rawst = (data[2] << 8) | data[3]
                        if rawst >= 32768:
                            rawst -= 65536
                        steering_deg = round(rawst / 10.0, 1)
                    elif can_id == "231" and len(data) >= 1:
                        gear_raw = data[0]
                        if gear_raw in GEAR_LOOKUP:
                            gear = GEAR_LOOKUP[gear_raw]
                        else:
                            unknown_gear_codes.add(gear_raw)
                            # keep last known gear rather than guessing
                    elif can_id == "433" and len(data) >= 4:
                        reverse = bool(data[3] & 0x02)

                display_gear = -1 if reverse else gear
                now = next_tick - t0
                f.write(f"{now:.3f},{throttle},{brake},{steering_deg},{speed},"
                        f"{rpm},{display_gear},0x{gear_raw:02X}\n")
                rows += 1
                if rows % int(args.rate) == 0:
                    f.flush()
                    sys.stdout.write(
                        f"\r{now:6.1f}s  RPM={rpm:5d}  speed={speed:5.1f}  "
                        f"gear={display_gear:+2d}  throttle={throttle:5.1f}%  "
                        f"brake={brake:5d}  steer={steering_deg:+7.1f}   "
                    )
                    sys.stdout.flush()
                next_tick += period
        except KeyboardInterrupt:
            pass
        finally:
            ser.close()

    print(f"\n\nstopped. {rows} rows written to {args.out} ({rows/args.rate:.1f}s of data).")
    if unknown_gear_codes:
        codes = ", ".join(f"0x{c:02X}" for c in sorted(unknown_gear_codes))
        print(f"NOTE: saw unrecognized gear_raw codes: {codes} -- check the gear_raw "
              f"column in the CSV, your car's gear table may differ (see docs/FINDINGS.md).")


if __name__ == "__main__":
    main()
