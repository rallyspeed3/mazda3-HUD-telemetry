#!/usr/bin/env python3
"""
live_dashboard.py -- live terminal readout of every signal this toolkit
has confirmed (see docs/FINDINGS.md), for verifying your own car matches
before you trust any of it.

Pairs with firmware/can_live.ino.

Usage:
    python live_dashboard.py [--port PORT]

Example:
    python live_dashboard.py --port COM6

Ctrl+C to stop.
"""
import argparse
import re
import sys
import time

import serial

RED = "\x1b[31m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
CYAN = "\x1b[36m"
DIM = "\x1b[2m"
RESET = "\x1b[0m"
BOLD = "\x1b[1m"
CLEAR_LINE = "\x1b[2K"

LINE_RE = re.compile(r"^\d+\s+([0-9A-Fa-f]{3})\s+\[\d+\]\s+([0-9A-Fa-f ]+)$")

BAR_WIDTH = 24
NUM_LINES = 10
KMH_TO_MPH = 0.621371

GEAR_LOOKUP = {
    0x00: "N", 0x01: "N",
    0x11: "1", 0x20: "2", 0x30: "3", 0x40: "4", 0x50: "5", 0x60: "6",
}


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default="COM6",
                     help="serial port the Arduino is on (default: COM6; "
                          "on Linux/Mac it'll look like /dev/ttyUSB0 or /dev/tty.usbserial-...)")
    return ap.parse_args()


def bar(frac, width=BAR_WIDTH):
    frac = max(0.0, min(1.0, frac))
    filled = int(round(frac * width))
    return "#" * filled + "-" * (width - filled)


def on_off(active, label_on="ON", label_off="off"):
    if active:
        return f"{RED}{BOLD}{label_on}{RESET}"
    return f"{GREEN}{DIM}{label_off}{RESET}"


def main():
    args = parse_args()
    try:
        ser = serial.Serial(args.port, baudrate=1000000, timeout=1)
    except serial.SerialException as e:
        print(f"Couldn't open {args.port}: {e}", file=sys.stderr)
        sys.exit(1)

    accel = 0
    rpm = 0
    brake_force = 0
    speed = 0.0
    steer_deg = 0.0
    gear_raw = 0x01
    reverse = False
    handbrake = False
    wheel = [0.0, 0.0, 0.0, 0.0]

    count = 0
    t0 = time.time()
    first_draw = True
    last_draw = 0.0
    DRAW_INTERVAL = 0.08  # ~12 fps -- fast enough to feel live, slow enough
                          # that the terminal doesn't fall behind and drift

    print(f"{CYAN}{BOLD}Live dashboard -- every confirmed signal (see docs/FINDINGS.md){RESET}")
    print("Ctrl+C to stop.\n")

    try:
        while True:
            line = ser.readline()
            if not line:
                continue
            text = line.decode(errors="replace").strip()
            m = LINE_RE.match(text)
            if not m:
                continue
            can_id = m.group(1).upper()
            data = [int(b, 16) for b in m.group(2).split()]

            updated = False
            if can_id == "201" and len(data) >= 7:
                rpm = (data[0] << 8) | data[1]
                accel = data[6]
                updated = True
            elif can_id == "20F" and len(data) >= 4:
                raw_f = (data[0] << 8) | data[1]
                brake_force = max(0, raw_f - 30000)
                raw_s = (data[2] << 8) | data[3]
                speed = (raw_s - 10000) / 100.0 * KMH_TO_MPH
                updated = True
            elif can_id == "082" and len(data) >= 4:
                raw = (data[2] << 8) | data[3]
                if raw >= 32768:
                    raw -= 65536
                steer_deg = raw / 10.0
                updated = True
            elif can_id == "231" and len(data) >= 1:
                gear_raw = data[0]
                updated = True
            elif can_id == "433" and len(data) >= 4:
                b3 = data[3]
                handbrake = bool(b3 & 0x01)
                reverse = bool(b3 & 0x02)
                updated = True
            elif can_id == "4B0" and len(data) >= 8:
                wheel = [((data[i] << 8) | data[i + 1]) - 10000
                         for i in (0, 2, 4, 6)]
                wheel = [round(w / 100.0 * KMH_TO_MPH, 1) for w in wheel]
                updated = True

            if not updated:
                continue
            count += 1

            now = time.time()
            if now - last_draw < DRAW_INTERVAL:
                continue
            last_draw = now

            accel_frac = accel / 255.0
            force_frac = brake_force / 10000.0
            steer_frac = (steer_deg + 500) / 1000.0  # -500..+500 -> 0..1
            gear_label = GEAR_LOOKUP.get(gear_raw, f"? (0x{gear_raw:02X})")
            if reverse:
                gear_label = "R"

            if not first_draw:
                sys.stdout.write(f"\x1b[{NUM_LINES}A")
            first_draw = False

            rate = count / max(now - t0, 0.001)

            sys.stdout.write(f"{CLEAR_LINE}ACCEL [{bar(accel_frac)}] {accel:3d}/255   RPM {rpm:5d}\n")
            sys.stdout.write(f"{CLEAR_LINE}BRAKE [{bar(force_frac)}] {brake_force:5d}/10000"
                              f"   SPEED {speed:5.1f} mph\n")
            sys.stdout.write(f"{CLEAR_LINE}STEERING [{bar(steer_frac)}] {steer_deg:+7.1f} deg "
                              f"{YELLOW}(needs engine running){RESET}\n")
            sys.stdout.write(f"{CLEAR_LINE}GEAR = {BOLD}{gear_label}{RESET}   "
                              f"REVERSE = {on_off(reverse)}   HANDBRAKE = {on_off(handbrake)}\n")
            sys.stdout.write(f"{CLEAR_LINE}WHEEL SPEED (mph)  FL={wheel[0]:+6.1f}  FR={wheel[1]:+6.1f}"
                              f"  RL={wheel[2]:+6.1f}  RR={wheel[3]:+6.1f}\n")
            sys.stdout.write(f"{CLEAR_LINE}\n")
            sys.stdout.write(f"{CLEAR_LINE}{DIM}{count} updates, {rate:5.1f} fps{RESET}\n")
            sys.stdout.write(f"{CLEAR_LINE}\n")
            sys.stdout.write(f"{CLEAR_LINE}\n")
            sys.stdout.write(f"{CLEAR_LINE}\n")
            sys.stdout.flush()
    except KeyboardInterrupt:
        pass
    finally:
        ser.close()
        print(f"\nstopped. {count} updates in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
