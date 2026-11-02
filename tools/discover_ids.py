#!/usr/bin/env python3
"""
discover_ids.py -- live hex-grid viewer for finding NEW, unmapped CAN
signals on your own car.

Pairs with firmware/can_discovery.ino, which streams a periodic snapshot
of every CAN ID seen on the bus. This renders that as a live grid and
highlights whichever bytes just changed, so you can press a pedal, flip a
switch, or turn the wheel and watch which ID lights up in real time.

Usage:
    python discover_ids.py [--port PORT]

Example:
    python discover_ids.py --port COM6
    python discover_ids.py --port /dev/ttyUSB0

Controls:
    q       quit

Bright red   = a byte that changed in the last 0.4s
Dim yellow   = a byte that changed in the last 1.5s
"""
import argparse
import curses
import sys
import time

import serial

RECENT_HOT = 0.4     # seconds: bright highlight
RECENT_WARM = 1.5    # seconds: dim highlight


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default="COM6",
                     help="serial port the Arduino is on (default: COM6; "
                          "on Linux/Mac it'll look like /dev/ttyUSB0 or /dev/tty.usbserial-...)")
    return ap.parse_args()


def read_snapshot(ser, buf):
    """Reads lines until a full ===SNAPSHOT===...===END=== block is seen.
    Returns (dict{id: (dlc, [8 bytes])}, buf) or (None, buf) if not ready."""
    while True:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
        if b"\n" not in buf:
            return None, buf
        line, buf = buf.split(b"\n", 1)
        text = line.decode(errors="replace").strip()
        if text == "===SNAPSHOT===":
            rows = {}
            while True:
                n2 = ser.in_waiting
                if n2:
                    buf += ser.read(n2)
                if b"\n" not in buf:
                    time.sleep(0.005)
                    continue
                line2, buf = buf.split(b"\n", 1)
                t2 = line2.decode(errors="replace").strip()
                if t2 == "===END===":
                    return rows, buf
                parts = t2.split()
                if len(parts) >= 10:
                    try:
                        can_id = int(parts[0], 16)
                        dlc = int(parts[1])
                        data = [int(x, 16) for x in parts[2:10]]
                        rows[can_id] = (dlc, data)
                    except ValueError:
                        continue


def main(stdscr, port):
    curses.curs_set(0)
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_RED)    # hot (just changed)
    curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_YELLOW)  # warm (recently changed)
    curses.init_pair(3, curses.COLOR_GREEN, -1)                  # id column
    curses.init_pair(4, curses.COLOR_CYAN, -1)                   # header
    stdscr.nodelay(True)

    ser = serial.Serial(port, baudrate=115200, timeout=0.05)
    buf = b""

    last_values = {}       # id -> [8 bytes]
    last_changed = {}      # (id, byte_idx) -> timestamp
    update_count = 0
    t0 = time.time()

    while True:
        ch = stdscr.getch()
        if ch in (ord('q'), ord('Q')):
            break

        rows, buf = read_snapshot(ser, buf)
        if rows is not None:
            update_count += 1
            now = time.time()
            for can_id, (dlc, data) in rows.items():
                prev = last_values.get(can_id)
                if prev is not None:
                    for i in range(8):
                        if prev[i] != data[i]:
                            last_changed[(can_id, i)] = now
                last_values[can_id] = data

            # render -- spread IDs across as many side-by-side columns as
            # fit, so a short terminal window doesn't silently truncate rows
            stdscr.erase()
            h, w = stdscr.getmaxyx()
            sorted_ids = sorted(last_values.keys())
            COL_WIDTH = 42  # "ID  B0 B1 B2 B3 B4 B5 B6 B7" + gap

            num_cols = max(1, min(len(sorted_ids) or 1, w // COL_WIDTH))
            rows_per_col = -(-len(sorted_ids) // num_cols) if sorted_ids else 1  # ceil div

            header_one = f"{'ID':>4}  " + "  ".join(f"B{i}" for i in range(8))
            for c in range(num_cols):
                x0 = c * COL_WIDTH
                if x0 + len(header_one) < w:
                    stdscr.addstr(0, x0, header_one, curses.color_pair(4) | curses.A_BOLD)
                    stdscr.addstr(1, x0, "-" * len(header_one))

            for idx, can_id in enumerate(sorted_ids):
                col_num = idx // rows_per_col
                row_in_col = idx % rows_per_col
                row_y = 2 + row_in_col
                x0 = col_num * COL_WIDTH
                if row_y >= h - 1 or x0 >= w:
                    continue
                data = last_values[can_id]
                stdscr.addstr(row_y, x0, f"{can_id:04X}", curses.color_pair(3) | curses.A_BOLD)
                col = x0 + 6
                for i in range(8):
                    age = now - last_changed.get((can_id, i), -999)
                    text = f"{data[i]:02X}"
                    if age < RECENT_HOT:
                        attr = curses.color_pair(1) | curses.A_BOLD
                    elif age < RECENT_WARM:
                        attr = curses.color_pair(2)
                    else:
                        attr = curses.A_NORMAL
                    if col + 2 < w:
                        stdscr.addstr(row_y, col, text, attr)
                    col += 4

            rate = update_count / max(now - t0, 0.001)
            shown = min(len(sorted_ids), num_cols * rows_per_col)
            footer = f"{len(last_values)} IDs tracked, {rate:.1f} snapshots/s -- press q to quit"
            if shown < len(sorted_ids):
                footer += f"  [only {shown} fit, widen/shorten terminal]"
            if h - 1 >= 0:
                stdscr.addstr(h - 1, 0, footer[:w - 1], curses.A_DIM)
            stdscr.refresh()
        else:
            time.sleep(0.01)

    ser.close()


if __name__ == "__main__":
    args = parse_args()
    try:
        curses.wrapper(main, args.port)
    except serial.SerialException as e:
        print(f"Couldn't open {args.port}: {e}", file=sys.stderr)
        sys.exit(1)
