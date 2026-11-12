#!/usr/bin/env python3
"""
csv_to_vbo.py -- converts a recorded CSV log into a RaceLogic .vbo file, so
the GPS track can be opened in free lap-analysis tools (Track Data Analysis,
Harry's LapTimer / onTrackTools, Trackday Plot, ...) instead of only this
project's own HUD overlay renderer.

Kept as a separate converter rather than a firmware change: the CSV stays
the simple source-of-truth format the ESP32 writes to flash/SD; this just
re-encodes it afterward.

.vbo format, confirmed against two real files (not guessed from memory):
Racelogic's own support article (en.racelogic.support, ".VBO Files") and a
RaceChrono-generated sample (github.com/Theintrepid1/RaceOverlay, tests/data/
racechrono_vir_trimmed.vbo):
  - plain space-delimited text, sections in [brackets]
  - [header]: one channel's descriptive name per line (not parsed by most
    readers -- informational only)
  - [channel units]: free text, but NOT safe to leave empty -- at least
    TrackDataAnalysis's reader (data/racelogic.py's VBOX()) expects one
    entry per non-GPS channel in [column names] order, INCLUDING "time"
    (its value is unused, but it still consumes a units slot), and groups
    channels sharing an axis by matching unit string -- leaving it blank
    piles every custom channel onto one shared, badly-scaled axis
  - [comments]: free text, can be empty
  - [column names]: ONE space-separated line of short tokens, in the same
    order as each [data] row's columns -- this is what readers actually key
    off of
  - time: UTC time-of-day as HHMMSS.SS (no colons)
  - latitude: decimal degrees x60 (minutes), +N
  - longitude: decimal degrees x -60 (minutes) -- the format is POSITIVE WEST
  - velocity: km/h. heading: degrees from North (0-360)

What this logger's CSV doesn't give us, so these are left out of the
[column names] line rather than faked: satellite count, altitude, vertical
velocity, DGPS/brake-trigger flags. Heading is DERIVED from consecutive GPS
fixes (initial bearing between them), since nothing logs it directly.

brake is written as a 0-100% value (raw CSV value / 100), matching the
min=0/max=10000 calibration every real render config in hud_overlay/configs/
uses for its own gauge fill -- the raw CSV column is an uncalibrated CAN
signal (can_task.cpp: rawf - 30000), not a percentage.

Timestamp caveat: this logger's CSV 'time' column is normally seconds-since-
boot, not a real clock (see Log's reset-stitching in
hud_overlay/render_overlay.py). The only real-world UTC anchor available
without a firmware change is the recording's START time, which:
  - comes for free if the CSV's own 'time' column is ISO-8601 timestamps,
  - otherwise is parsed from the CSV's filename, IF the ESP32 had its wall
    clock set when the recording started (filenames look like
    "11-11-2026-05.30PM.csv" -- LOCAL time, minute resolution only, no
    seconds -- see firmware/esp32_web_logger/can_task.cpp's makeLogName()),
    converted to UTC with --tz-offset (same convention as render_overlay.py:
    hours added to UTC to get local time, e.g. CST = -6),
  - otherwise must be supplied explicitly with --start-utc.
Minute-resolution filenames mean row timestamps can be off by up to ~30s
against true UTC even in the working case -- fine for lap splits (only
*relative* timing matters there), not for syncing against another
independently-timestamped data source.

Usage:
    python csv_to_vbo.py --csv "30 Min drive.csv"
    python csv_to_vbo.py --csv run1.csv --start-utc 2026-11-11T23:05:00Z
    python csv_to_vbo.py --csv run1.csv --tz-offset -5   # CDT instead of CST
"""
import argparse
import calendar
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hud_overlay"))
from render_overlay import DEFAULT_CONFIG, Log  # noqa: E402

EARTH_RADIUS_M = 6371000.0

# firmware/esp32_web_logger/can_task.cpp's makeLogName(): "%m-%d-%Y-%I.%M%p",
# optionally followed by " (2)" etc. for a second recording in the same minute.
FILENAME_RE = re.compile(r"^(\d{2})-(\d{2})-(\d{4})-(\d{2})\.(\d{2})(AM|PM)", re.IGNORECASE)

# token -> (CSV channel key in Log.channels, format, scale applied before formatting,
#           unit string, clamp-to-[0, this] or None)
# brake's raw CSV value isn't a percentage -- it's a raw CAN signal (see
# can_task.cpp: rawf - 30000, no further scaling); every real render config
# in hud_overlay/configs/*.json calibrates it as min=0 max=10000 for its 0-100%
# gauge fill, so /100 here matches that same established calibration. The raw
# signal can still exceed that ceiling (observed up to 355% unclamped) since
# 10000 is a practical "visually full" threshold, not the sensor's true max --
# clamped to 100 so it doesn't blow out a shared 0-100% axis with throttle in
# a lap-analysis tool (same failure mode the empty-units bug caused).
EXTRA_CHANNELS = [
    ("throttle", "throttle", "{:.2f}", 1.0, "%", None),
    ("brake", "brake", "{:.2f}", 0.01, "%", 100.0),
    ("steering", "steering", "{:.2f}", 1.0, "deg", None),
    ("speed_mph", "speed", "{:.2f}", 1.0, "mph", None),
    ("rpm", "rpm", "{:.0f}", 1.0, "rpm", None),
    ("gear", "gear", "{:.0f}", 1.0, "gear", None),
]
HEADER_NAMES = {
    "throttle": "throttle pct", "brake": "brake pct", "steering": "steering deg",
    "speed_mph": "speed mph (can bus)", "rpm": "rpm", "gear": "gear",
}


def start_utc_from_filename(csv_path, tz_offset_hours):
    m = FILENAME_RE.match(Path(csv_path).stem)
    if not m:
        return None
    mo, day, year, hour12, minute, ampm = m.groups()
    hour = int(hour12) % 12
    if ampm.upper() == "PM":
        hour += 12
    local_naive = datetime(int(year), int(mo), int(day), hour, int(minute))
    # Mirrors can_task.cpp: it formats (utcNow + tz_offset_seconds) with gmtime_r,
    # i.e. the filename's fields ARE utc_epoch + tz_offset when read back as if UTC.
    local_as_epoch = calendar.timegm(local_naive.timetuple())
    return local_as_epoch - tz_offset_hours * 3600.0


def bearing_deg(lat1, lon1, lat2, lon2):
    """Initial bearing from point 1 to point 2, degrees from North, 0-360."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlon)
    return math.degrees(math.atan2(x, y)) % 360.0


def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def hhmmss(epoch):
    t = datetime.fromtimestamp(epoch, tz=timezone.utc)
    sec = t.second + t.microsecond / 1e6
    return f"{t.hour:02d}{t.minute:02d}{sec:05.2f}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out", help="default: --csv with a .vbo extension")
    ap.add_argument("--start-utc", help="ISO-8601 UTC time the recording started, e.g. 2026-11-11T23:05:00Z -- "
                         "overrides filename/--tz-offset guessing")
    ap.add_argument("--tz-offset", type=float, default=-6.0,
                    help="hours added to UTC to get local time, for reading the CSV filename's wall-clock "
                         "start time (match the firmware's LOCAL_TZ_OFFSET_SEC; CST=-6, CDT=-5). Default -6")
    args = ap.parse_args()

    log = Log(args.csv, DEFAULT_CONFIG)
    if log.gps_lat is None:
        sys.exit(f"{args.csv}: no usable GPS fixes (gps_lat/gps_lon/gps_valid) -- nothing to convert")

    start_utc_epoch = None
    if not log.absolute:
        if args.start_utc:
            s = args.start_utc[:-1] + "+00:00" if args.start_utc.endswith("Z") else args.start_utc
            start_utc_epoch = datetime.fromisoformat(s).timestamp()
        else:
            start_utc_epoch = start_utc_from_filename(args.csv, args.tz_offset)
            if start_utc_epoch is None:
                sys.exit(f"{args.csv}: filename doesn't encode a start time (looks like a plain "
                         f"'log_NNNNN.csv' -- the ESP32's wall clock was never set for this recording) "
                         f"and no --start-utc was given. Pass --start-utc to proceed.")
            print(f"note: start time read from filename, local (tz-offset {args.tz_offset:+g}h) -- "
                  f"minute precision only", file=sys.stderr)

    lat, lon, ok = log.gps_lat, log.gps_lon, log.gps_ok
    changed = np.ones(len(lat), dtype=bool)
    changed[1:] = (lat[1:] != lat[:-1]) | (lon[1:] != lon[:-1])
    fix_idx = np.flatnonzero(ok & changed)
    if len(fix_idx) < 2:
        sys.exit(f"{args.csv}: fewer than 2 distinct GPS fixes -- nothing to convert")
    fix_t = log.t[fix_idx]
    fix_lat = lat[fix_idx]
    fix_lon = lon[fix_idx]
    fix_heading = [bearing_deg(fix_lat[i], fix_lon[i], fix_lat[i + 1], fix_lon[i + 1])
                   for i in range(len(fix_idx) - 1)]
    fix_heading.append(fix_heading[-1] if fix_heading else 0.0)

    # Velocity from the GPS fixes themselves (distance/time between
    # consecutive fixes) -- the CSV's 'gps_speed' column isn't one of the
    # channels Log loads, and this is just as direct a measurement.
    fix_velocity_kmh = []
    for i in range(len(fix_idx) - 1):
        dt = fix_t[i + 1] - fix_t[i]
        dist = haversine_m(fix_lat[i], fix_lon[i], fix_lat[i + 1], fix_lon[i + 1])
        fix_velocity_kmh.append((dist / dt) * 3.6 if dt > 0 else 0.0)
    fix_velocity_kmh.append(fix_velocity_kmh[-1] if fix_velocity_kmh else 0.0)

    extras = [(token, log.channels.get(key), fmt, scale, unit, clamp)
              for token, key, fmt, scale, unit, clamp in EXTRA_CHANNELS]
    extras = [row for row in extras if row[1] is not None]

    tokens = ["time", "lat", "long", "velocity", "heading"] + [token for token, *_ in extras]
    header_lines = ["time", "latitude", "longitude", "velocity kmh", "heading"] + \
        [HEADER_NAMES[token] for token, *_ in extras]
    # lat/long/velocity/heading are builtin channels to most VBO readers and don't need
    # a units entry; everything else does, and per a real-world reader's parser (TrackDataAnalysis's
    # VBOX() -- see data/racelogic.py), that INCLUDES "time" even though its unit is unused/discarded.
    # An empty [channel units] section (the previous behavior) made every extra channel fall back to
    # the same blank unit string, so a lap-analysis tool that groups channels onto a shared axis by
    # matching unit piled throttle/brake/steering/rpm/gear onto one axis -- confirmed against a real
    # session testing this file in TrackDataAnalysis.
    channel_unit_lines = ["s"] + [unit for _, _, _, _, unit, _ in extras]

    in_range = np.flatnonzero((log.t >= fix_t[0]) & (log.t <= fix_t[-1]))
    data_lines = []
    for i in in_range:
        t = log.t[i]
        row_lat = float(np.interp(t, fix_t, fix_lat))
        row_lon = float(np.interp(t, fix_t, fix_lon))
        n = max(0, min(int(np.searchsorted(fix_t, t, side="right")) - 1, len(fix_heading) - 1))
        heading = fix_heading[n]
        kmh = fix_velocity_kmh[n]

        epoch = t if log.absolute else start_utc_epoch + (t - log.t[0])

        fields = [hhmmss(epoch), f"{row_lat * 60.0:+.5f}", f"{-row_lon * 60.0:+.5f}",
                  f"{kmh:.3f}", f"{heading:.2f}"]
        for _, arr, fmt, scale, _, clamp in extras:
            v = arr[i]
            v = 0.0 if np.isnan(v) else v * scale
            if clamp is not None:
                v = max(0.0, min(clamp, v))
            fields.append(fmt.format(v))
        data_lines.append(" ".join(fields))

    out_path = args.out or str(Path(args.csv).with_suffix(".vbo"))
    created = datetime.now(timezone.utc)
    with open(out_path, "w", newline="\r\n") as f:
        f.write(f"File created on {created:%d/%m/%Y} at {created:%H:%M:%S}\n\n")
        f.write("[header]\n")
        f.write("\n".join(header_lines) + "\n\n")
        f.write("[channel units]\n")
        f.write("\n".join(channel_unit_lines) + "\n\n")
        f.write("[comments]\n")
        f.write(f"Generated by csv_to_vbo.py from {Path(args.csv).name}\n")
        f.write("mazda3-HUD-telemetry\n\n")
        f.write("[column names]\n")
        f.write(" ".join(tokens) + "\n\n")
        f.write("[data]\n")
        f.write("\n".join(data_lines) + "\n")

    print(f"wrote {len(data_lines)} rows -> {out_path}")


if __name__ == "__main__":
    main()
