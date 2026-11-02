#!/usr/bin/env python3
"""
WRC-style driver-input HUD renderer.

Reads a CSV data log (time + channels), draws a HUD for every video frame,
and encodes it as ProRes 4444 with a transparent background (alpha channel).
Drop the .mov on a track above your footage in Premiere: no chroma key.

HUD elements:
  - steering wheel that rotates with the logged angle
  - red brake bar and green throttle bar
  - gear indicator, speed readout
  - RPM bar with shift lights (flashes at the shift point)

Requires: Python 3.9+, Pillow, numpy, ffmpeg on PATH.

Examples:
  python render_overlay.py --csv run1.csv --config configs/horizontal_1080p.json --out run1_hud.mov
  python render_overlay.py --csv run1.csv --config configs/horizontal_1080p.json --preview 12.5 --preview-out frame.png
  python render_overlay.py --csv run1.csv --config configs/vertical_reels.json --width 1080 --height 1920 --out run1_hud_vertical.mov
"""

import argparse
import csv
import json
import math
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------- defaults

DEFAULT_CONFIG = {
    "time": {"col": "time"},                       # seconds, or ISO-8601 timestamps (UTC)
    "throttle": {"col": "throttle", "min": 0, "max": 100},
    "brake": {"col": "brake", "min": 0, "max": 100},
    "steering": {"col": "steering_deg", "invert": False, "max_display_deg": 540},
    "speed": {"col": "speed", "unit": "MPH", "scale": 1.0},
    "rpm": {"col": "rpm", "max": 7000, "shift": 6200, "segments": 20},
    "gear": {"col": "gear"},
    "layout": {
        "style": "panel",              # "panel" (box with big wheel) or "strip" (thin full-width bar)
        "anchor": "bottom-left",       # bottom-left | bottom-right | bottom-center | top-left | top-right
        "margin": 48,                  # px at 1080p, scales with output height
        "scale": 1.0,                  # overall HUD size multiplier
        "panel_opacity": 0.55,         # 0 = no background plate
        "center_at": None,             # e.g. [0.5, 0.31]: HUD centered at 50% across, 31% down (overrides anchor)
    },
    "colors": {
        "throttle": [40, 220, 90],
        "brake": [235, 45, 45],
        "text": [255, 255, 255],
        "dim": [255, 255, 255, 60],
        "panel": [10, 12, 16],
        "accent": [255, 196, 0],
    },
    "wheel_image": None,               # optional PNG of your own wheel (top of rim up, transparent background)
}

FONT_CANDIDATES = [
    # Windows
    "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf",
    # macOS
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
    # Linux
    "/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def deep_merge(base, override):
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_font(path, size):
    for p in ([path] if path else []) + FONT_CANDIDATES:
        if p and os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size=size)


# ---------------------------------------------------------------- data

def parse_time_value(s):
    """Return (seconds_float, is_absolute). Absolute = epoch seconds from ISO-8601."""
    s = s.strip()
    try:
        return float(s), False
    except ValueError:
        pass
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp(), True


class Log:
    def __init__(self, path, cfg):
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            sys.exit(f"{path}: no rows")
        tcol = cfg["time"]["col"]
        if tcol not in rows[0]:
            sys.exit(f"time column '{tcol}' not in CSV columns: {list(rows[0].keys())}")

        times, absolute = [], None
        for r in rows:
            t, a = parse_time_value(r[tcol])
            times.append(t)
            absolute = a if absolute is None else absolute
        self.t = np.array(times, dtype=float)
        order = np.argsort(self.t, kind="stable")
        self.t = self.t[order]
        rows = [rows[i] for i in order]
        self.absolute = absolute            # True if timestamps are real UTC times
        self.t0 = self.t[0]

        self.channels = {}
        for key in ("throttle", "brake", "steering", "speed", "rpm", "gear"):
            col = cfg[key].get("col")
            if not col or col not in rows[0]:
                print(f"note: channel '{key}' (column '{col}') not in CSV; it will show blank", file=sys.stderr)
                continue
            vals = []
            for r in rows:
                v = r[col].strip()
                try:
                    vals.append(float(v))
                except ValueError:
                    vals.append(np.nan)     # e.g. 'N' for neutral in a gear column
            arr = np.array(vals, dtype=float)
            self.channels[key] = arr

    def value(self, key, t, step=False):
        arr = self.channels.get(key)
        if arr is None:
            return None
        if step:   # gear: hold the last sample, no blending between gears
            i = np.searchsorted(self.t, t, side="right") - 1
            i = min(max(i, 0), len(arr) - 1)
            v = arr[i]
            return None if np.isnan(v) else v
        ok = ~np.isnan(arr)
        if not ok.any():
            return None
        return float(np.interp(t, self.t[ok], arr[ok]))


# ---------------------------------------------------------------- drawing

def rgba(c, a=255):
    return tuple(c[:3]) + ((c[3],) if len(c) > 3 else (a,))


def make_wheel(diam, image_path=None):
    """Steering wheel sprite, 12 o'clock = straight ahead."""
    if image_path:
        img = Image.open(image_path).convert("RGBA")
        return img.resize((diam, diam), Image.LANCZOS)
    ss = 4                      # supersample for smooth edges
    d = diam * ss
    img = Image.new("RGBA", (d, d), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    rim = int(d * 0.085)
    pad = rim // 2 + 2
    dr.ellipse([pad, pad, d - pad, d - pad], outline=(235, 235, 235, 255), width=rim)
    c = d / 2
    hub = d * 0.15
    # three spokes: 3, 9 and 6 o'clock
    sw = int(d * 0.07)
    for ang in (0, 180, 90):
        a = math.radians(ang)
        x = c + math.cos(a) * (c - pad - rim / 2)
        y = c + math.sin(a) * (c - pad - rim / 2)
        dr.line([c, c, x, y], fill=(200, 200, 200, 255), width=sw)
    dr.ellipse([c - hub, c - hub, c + hub, c + hub], fill=(60, 60, 60, 255), outline=(200, 200, 200, 255), width=sw // 2)
    # top-center marker: small red dot (RBR-style straight-ahead indicator)
    mr = d * 0.032
    mcy = pad + rim / 2
    dr.ellipse([c - mr, mcy - mr, c + mr, mcy + mr], fill=(230, 40, 30, 255))
    return img.resize((diam, diam), Image.LANCZOS)


class HUD:
    def __init__(self, cfg, short_side, font_path=None):
        self.cfg = cfg
        L = cfg["layout"]
        # size relative to the frame's short side: 1080 for both 1920x1080 and 1080x1920
        self.k = short_side / 1080.0 * float(L.get("scale", 1.0))
        k = self.k
        self.W = int(640 * k)
        self.H = int(300 * k)
        self.font_big = load_font(font_path, int(120 * k))
        self.font_med = load_font(font_path, int(54 * k))
        self.font_small = load_font(font_path, int(22 * k))
        self.wheel_d = int(200 * k)
        self.wheel = make_wheel(self.wheel_d, cfg.get("wheel_image"))
        self.col = cfg["colors"]

    def _bar(self, dr, x, y, w, h, frac, color, label):
        k = self.k
        frac = 0.0 if frac is None else max(0.0, min(1.0, frac))
        dr.rounded_rectangle([x, y, x + w, y + h], radius=int(6 * k), fill=rgba(self.col["dim"]))
        fh = int(h * frac)
        if fh > 0:
            dr.rounded_rectangle([x, y + h - fh, x + w, y + h], radius=int(6 * k), fill=rgba(color))
        tw = dr.textlength(label, font=self.font_small)
        dr.text((x + w / 2 - tw / 2, y + h + 8 * k), label, font=self.font_small, fill=rgba(self.col["text"]))

    def draw(self, v, flash_on):
        k, c = self.k, self.cfg
        img = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        dr = ImageDraw.Draw(img)

        # Background plate goes on its own layer; everything else is drawn on `img`
        # and alpha-composited over it, so semi-transparent elements don't punch holes.
        base = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        op = float(c["layout"].get("panel_opacity", 0))
        if op > 0:
            ImageDraw.Draw(base).rounded_rectangle([0, 0, self.W - 1, self.H - 1], radius=int(22 * k),
                                                   fill=rgba(self.col["panel"], int(255 * op)))

        # --- RPM bar with shift lights across the top
        rc = c["rpm"]
        segs = int(rc.get("segments", 20))
        rx0, ry0 = 24 * k, 20 * k
        rw, rh = self.W - 48 * k, 22 * k
        gap = 4 * k
        sw = (rw - gap * (segs - 1)) / segs
        rpm = v["rpm"]
        shift = float(rc.get("shift", rc["max"]))
        over = rpm is not None and rpm >= shift
        for i in range(segs):
            seg_rpm = rc["max"] * (i + 1) / segs
            pos = i / max(segs - 1, 1)
            if pos < 0.6:
                col = (40, 220, 90)
            elif pos < 0.85:
                col = (255, 200, 0)
            else:
                col = (235, 45, 45)
            lit = rpm is not None and rpm >= seg_rpm - rc["max"] / segs * 0.5
            if over:
                col = (60, 140, 255) if flash_on else (40, 40, 40)
                lit = True
            x = rx0 + i * (sw + gap)
            dr.rounded_rectangle([x, ry0, x + sw, ry0 + rh], radius=int(3 * k),
                                 fill=rgba(col, 255) if lit else rgba(self.col["dim"]))

        # --- steering wheel
        wx, wy = int(24 * k), int(64 * k)
        st = v["steering"]
        if st is not None:
            ang = -st if c["steering"].get("invert") else st
            ang = max(-c["steering"]["max_display_deg"], min(c["steering"]["max_display_deg"], ang))
            w = self.wheel.rotate(-ang, resample=Image.BICUBIC)   # positive angle = clockwise (right)
            img.alpha_composite(w, (wx, wy))
            txt = f"{st:+.0f}°"
        else:
            img.alpha_composite(self.wheel, (wx, wy))
            txt = "--"
        tw = dr.textlength(txt, font=self.font_small)
        dr.text((wx + self.wheel_d / 2 - tw / 2, wy + self.wheel_d + 2 * k), txt,
                font=self.font_small, fill=rgba(self.col["text"]))

        # --- pedal bars
        bx = wx + self.wheel_d + 28 * k
        by, bw, bh = 66 * k, 34 * k, 180 * k

        def norm(key, val):
            if val is None:
                return None
            lo, hi = float(c[key]["min"]), float(c[key]["max"])
            return (val - lo) / (hi - lo) if hi != lo else 0.0

        self._bar(dr, bx, by, bw, bh, norm("brake", v["brake"]), self.col["brake"], "BRK")
        self._bar(dr, bx + bw + 26 * k, by, bw, bh, norm("throttle", v["throttle"]), self.col["throttle"], "THR")

        # --- gear and speed
        gx = bx + 2 * bw + 58 * k
        gear = v["gear"]
        gtxt = "N" if gear is None or gear == 0 else ("R" if gear < 0 else str(int(gear)))
        dr.text((gx, 52 * k), gtxt, font=self.font_big, fill=rgba(self.col["accent"]))
        dr.text((gx + 4 * k, 182 * k), "GEAR", font=self.font_small, fill=rgba(self.col["text"], 180))

        sx = gx + 110 * k
        spd = v["speed"]
        stxt = "--" if spd is None else f"{spd * float(c['speed'].get('scale', 1.0)):.0f}"
        dr.text((sx, 92 * k), stxt, font=self.font_med, fill=rgba(self.col["text"]))
        dr.text((sx + 2 * k, 154 * k), c["speed"].get("unit", "MPH"), font=self.font_small,
                fill=rgba(self.col["text"], 180))
        rtxt = "--" if rpm is None else f"{rpm:,.0f} RPM"
        dr.text((sx + 2 * k, 214 * k), rtxt, font=self.font_small, fill=rgba(self.col["text"], 200))
        base.alpha_composite(img)
        return base


class StripHUD:
    """Thin full-width bar (RBR-style): brake grows left from center, throttle grows right,
    wheel / gear / speed / RPM in the middle."""

    def __init__(self, cfg, frame_w, short_side, font_path=None):
        self.cfg = cfg
        L = cfg["layout"]
        self.k = short_side / 1080.0 * float(L.get("scale", 1.0))
        k = self.k
        self.W = frame_w
        self.H = int(88 * k)
        self.font_gear = load_font(font_path, int(70 * k))
        self.font_num = load_font(font_path, int(30 * k))
        self.font_lbl = load_font(font_path, int(17 * k))
        self.wheel_d = int(62 * k)
        self.wheel = make_wheel(self.wheel_d, cfg.get("wheel_image"))
        self.col = cfg["colors"]

    def draw(self, v, flash_on):
        k, c, W, H = self.k, self.cfg, self.W, self.H
        base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        op = float(c["layout"].get("panel_opacity", 0))
        if op > 0:
            ImageDraw.Draw(base).rectangle([0, 0, W, H], fill=rgba(self.col["panel"], int(255 * op)))
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dr = ImageDraw.Draw(img)
        txt = rgba(self.col["text"])

        def norm(key, val):
            if val is None:
                return 0.0
            lo, hi = float(c[key]["min"]), float(c[key]["max"])
            return max(0.0, min(1.0, (val - lo) / (hi - lo))) if hi != lo else 0.0

        cw = int(330 * k)                    # center block width
        cx0 = (W - cw) // 2
        by0, by1 = int(40 * k), int(72 * k)  # bar band
        pad, gap = int(18 * k), int(14 * k)

        # brake: left of center, fills from the center outward (leftward)
        bl, br = pad, cx0 - gap
        dr.rectangle([bl, by0, br, by1], fill=rgba(self.col["dim"]))
        fw = int((br - bl) * norm("brake", v["brake"]))
        if fw > 0:
            dr.rectangle([br - fw, by0, br, by1], fill=rgba(self.col["brake"]))
        lw = dr.textlength("Brake", font=self.font_lbl)
        dr.text((br - lw, by0 - 24 * k), "Brake", font=self.font_lbl, fill=txt)

        # throttle: right of center, fills rightward
        tl, tr = cx0 + cw + gap, W - pad
        dr.rectangle([tl, by0, tr, by1], fill=rgba(self.col["dim"]))
        fw = int((tr - tl) * norm("throttle", v["throttle"]))
        if fw > 0:
            dr.rectangle([tl, by0, tl + fw, by1], fill=rgba(self.col["throttle"]))
        dr.text((tl, by0 - 24 * k), "Throttle", font=self.font_lbl, fill=txt)

        # center block: wheel, gear, speed / rpm
        dr.rectangle([cx0, 0, cx0 + cw, H], fill=(0, 0, 0, 110))
        st = v["steering"]
        wheel = self.wheel
        if st is not None:
            ang = -st if c["steering"].get("invert") else st
            ang = max(-c["steering"]["max_display_deg"], min(c["steering"]["max_display_deg"], ang))
            wheel = self.wheel.rotate(-ang, resample=Image.BICUBIC)
        img.alpha_composite(wheel, (int(cx0 + 14 * k), (H - self.wheel_d) // 2))

        rpm = v["rpm"]
        over = rpm is not None and rpm >= float(c["rpm"].get("shift", c["rpm"]["max"]))
        gear = v["gear"]
        gtxt = "N" if gear is None or gear == 0 else ("R" if gear < 0 else str(int(gear)))
        # red box behind the gear number is a rev-limiter warning (RBR-style) --
        # only shows (flashing) when over the shift point, plain text otherwise
        box_w = int(58 * k)
        box_h = int(64 * k)
        gx = cx0 + 14 * k + self.wheel_d + 16 * k
        gy = (H - box_h) / 2
        if over and flash_on:
            dr.rounded_rectangle([gx, gy, gx + box_w, gy + box_h], radius=int(6 * k), fill=rgba(self.col["brake"]))
            gear_fill = (255, 255, 255, 255)
        else:
            gear_fill = txt
        gb = dr.textbbox((0, 0), gtxt, font=self.font_gear)
        tw = gb[2] - gb[0]
        dr.text((gx + (box_w - tw) / 2 - gb[0], gy + (box_h - (gb[3] - gb[1])) / 2 - gb[1]),
                gtxt, font=self.font_gear, fill=gear_fill)

        nx = gx + box_w + 14 * k
        spd = v["speed"]
        stxt = "--" if spd is None else f"{spd * float(c['speed'].get('scale', 1.0)):.0f}"
        rtxt = "--" if rpm is None else f"{rpm:.0f}"
        ux = cx0 + cw - 74 * k
        for row, (val, unit) in enumerate(((stxt, c["speed"].get("unit", "MPH")), (rtxt, "RPM"))):
            y = 8 * k + row * 38 * k
            vw = dr.textlength(val, font=self.font_num)
            dr.text((ux - 10 * k - vw, y), val, font=self.font_num, fill=txt)
            dr.text((ux, y + 9 * k), unit, font=self.font_lbl, fill=rgba(self.col["text"], 200))

        # thin RPM line along the bottom of the center block (shift lights)
        rmax = float(c["rpm"]["max"])
        frac = 0.0 if rpm is None else max(0.0, min(1.0, rpm / rmax))
        lc = (rgba((60, 140, 255)) if flash_on else (0, 0, 0, 0)) if over else rgba(self.col["accent"])
        dr.rectangle([cx0, H - 5 * k, cx0 + cw * frac, H], fill=lc)

        base.alpha_composite(img)
        return base


def place(anchor, frame_w, frame_h, hud_w, hud_h, margin):
    left, right = margin, frame_w - hud_w - margin
    top, bottom = margin, frame_h - hud_h - margin
    cx = (frame_w - hud_w) // 2
    return {
        "bottom-left": (left, bottom), "bottom-right": (right, bottom), "bottom-center": (cx, bottom),
        "top-left": (left, top), "top-right": (right, top),
    }.get(anchor, (left, bottom))


# ---------------------------------------------------------------- timecode

def fps_parts(fps_str):
    if "/" in fps_str:
        n, d = fps_str.split("/")
        return float(n) / float(d), fps_str
    f = float(fps_str)
    named = {29.97: "30000/1001", 59.94: "60000/1001", 23.976: "24000/1001"}
    for k_, v_ in named.items():
        if abs(f - k_) < 0.01:
            return float(v_.split("/")[0]) / float(v_.split("/")[1]), v_
    return f, fps_str


def timecode_for(epoch, fps, tz_hours):
    dt = datetime.fromtimestamp(epoch, tz=timezone.utc) + timedelta(hours=tz_hours)
    nominal = round(fps)
    ff = int((dt.microsecond / 1e6) * nominal)
    sep = ";" if abs(fps - nominal) > 0.001 else ":"     # drop-frame for 29.97 / 59.94
    return f"{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}{sep}{ff:02d}"


# ---------------------------------------------------------------- main

def resolve_start(arg, log):
    if arg is None:
        return log.t0
    try:
        return log.t0 + float(arg)          # seconds from log start
    except ValueError:
        t, _ = parse_time_value(arg)        # absolute ISO time
        return t


def main():
    ap = argparse.ArgumentParser(description="Render a transparent WRC-style HUD from a CSV log.")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--config", help="JSON config (column names, ranges, layout)")
    ap.add_argument("--out", default="hud.mov")
    ap.add_argument("--fps", default="59.94", help="match your footage, e.g. 59.94, 29.97, 60, 30")
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--start", help="seconds after log start, or ISO time like 2026-11-08T15:42:10Z")
    ap.add_argument("--duration", type=float, help="seconds to render (default: to end of log)")
    ap.add_argument("--offset", type=float, default=0.0,
                    help="shift data vs video in seconds (+ = data appears later)")
    ap.add_argument("--timecode", default="auto",
                    help="'auto' (from ISO log times), 'none', or HH:MM:SS:FF")
    ap.add_argument("--tz-offset", type=float, default=0.0,
                    help="hours added to UTC for auto timecode (match your cameras' clock; CDT=-5, CST=-6)")
    ap.add_argument("--font", help="path to a .ttf/.otf font")
    ap.add_argument("--full-frame", action="store_true",
                    help="render a full --width x --height frame with the HUD placed by the config "
                         "(default: just the HUD panel, much faster; position it in Premiere)")
    ap.add_argument("--preview", type=float, help="render one frame at this many seconds after --start")
    ap.add_argument("--preview-out", default="hud_preview.png")
    ap.add_argument("--preview-bg", help="image to preview the HUD over (e.g. a screenshot of your edit)")
    args = ap.parse_args()

    cfg = DEFAULT_CONFIG
    if args.config:
        with open(args.config) as f:
            cfg = deep_merge(DEFAULT_CONFIG, json.load(f))

    log = Log(args.csv, cfg)
    fps, fps_ff = fps_parts(args.fps)
    start = resolve_start(args.start, log)
    end = log.t[-1] if args.duration is None else start + args.duration
    n_frames = max(1, int(math.floor((end - start) * fps)) + 1)

    short = min(args.width, args.height)
    style = cfg["layout"].get("style", "panel")
    hud = StripHUD(cfg, args.width, short, args.font) if style == "strip" else HUD(cfg, short, args.font)
    margin = int(cfg["layout"].get("margin", 48) * short / 1080)
    center_at = cfg["layout"].get("center_at")
    if center_at:   # [x_frac, y_frac] of the frame where the HUD's center goes
        px = int(args.width * center_at[0] - hud.W / 2)
        py = int(args.height * center_at[1] - hud.H / 2)
    else:
        px, py = place(cfg["layout"].get("anchor", "bottom-left"), args.width, args.height, hud.W, hud.H, margin)

    def values_at(t):
        td = t - args.offset
        return {
            "throttle": log.value("throttle", td),
            "brake": log.value("brake", td),
            "steering": log.value("steering", td),
            "speed": log.value("speed", td),
            "rpm": log.value("rpm", td),
            "gear": log.value("gear", td, step=True),
        }

    def flash(i):
        return (i // max(1, int(fps / 8))) % 2 == 0     # ~4 Hz shift-light flash

    # ---- single-frame preview (composited on gray so you can see it)
    if args.preview is not None:
        t = start + args.preview
        if args.preview_bg:
            frame = Image.open(args.preview_bg).convert("RGBA").resize((args.width, args.height), Image.LANCZOS)
        else:
            frame = Image.new("RGBA", (args.width, args.height), (70, 74, 80, 255))
        frame.alpha_composite(hud.draw(values_at(t), True), (px, py))
        frame.convert("RGB").save(args.preview_out)
        print(f"preview written: {args.preview_out}")
        return

    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found on PATH")

    tc = None
    if args.timecode == "auto" and log.absolute:
        tc = timecode_for(start, fps, args.tz_offset)
    elif args.timecode not in ("auto", "none"):
        tc = args.timecode

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{hud.W}x{hud.H}", "-r", fps_ff, "-i", "-",
    ]
    if not args.full_frame:
        cmd += ["-vf", "format=yuva444p10le"]          # small clip; position it in Premiere
    else:
        cmd += ["-vf", f"pad={args.width}:{args.height}:{px}:{py}:color=black@0,format=yuva444p10le"]
    cmd += ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le",
            "-alpha_bits", "16", "-vendor", "apl0"]
    if tc:
        cmd += ["-timecode", tc]
    cmd += [args.out]

    print(f"rendering {n_frames} frames @ {fps:.3f} fps ({n_frames / fps:.1f} s)"
          + (f", timecode {tc}" if tc else ""))
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    step = max(1, int(round(fps)) * 5)
    try:
        for i in range(n_frames):
            t = start + i / fps
            proc.stdin.write(hud.draw(values_at(t), flash(i)).tobytes())
            if i % step == 0:
                print(f"  {i / fps:6.1f} s / {n_frames / fps:.1f} s", flush=True)
    finally:
        proc.stdin.close()
        rc = proc.wait()
    if rc != 0:
        sys.exit(f"ffmpeg failed ({rc})")
    print(f"done: {args.out}")


if __name__ == "__main__":
    main()
