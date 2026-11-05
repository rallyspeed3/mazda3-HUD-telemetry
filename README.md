# Mazda3 HUD Telemetry

Tools for reading real-time driving data (RPM, speed, throttle, brake,
steering angle, gear) straight off a 2013 Mazdaspeed3's CAN bus -- no
paid scan tool, no dealer software. Works with **either an Arduino Uno +
a $10 MCP2515 module, or an ESP32-S3 board with CAN built in** -- pick
whichever you've already got. Built for recording driving data and
turning it into a transparent video overlay (throttle/brake bars, a
rotating steering wheel, gear indicator) to drop onto dash-cam or
track-day footage; the ESP32 path can also run fully standalone in the
car, no laptop required.

**I (the repo owner) take zero credit for the code itself -- this whole
project, every script and every microcontroller sketch in this repo, was
written by [Claude](https://claude.com) (Anthropic's AI) through a
series of conversations where I described what I wanted and we tested it
together against my actual car. I'm sharing it in case it's useful to
anyone else with the same car, or as a reference for reverse-engineering
CAN buses on other cars.**

## ⚠️ Read before using

- Confirmed working on a **2013 Mazdaspeed3 (BL platform, 6-speed
  manual)**. Likely works unchanged on other 2010-2013 BL-platform
  Mazda3/Mazdaspeed3 cars. **Not tested on anything else.** Verify every
  signal against something you can see with your own eyes before
  trusting it -- especially anything you'd rely on while driving.
- Most of this toolkit only **listens** to the CAN bus. The exception is
  the UDS exploration tools (`discover_modules.py`, `discover_dids.py`),
  which send standard **read-only** diagnostic requests (TesterPresent,
  ReadDataByIdentifier) -- they can't command or control anything on the
  car, but they do put frames on the bus, unlike everything else here.
- You are wiring a hobby electronics board directly to your car's data
  network. Double-check your connections before plugging into a running
  car. If you're not comfortable with that, don't do it.
- This is a hobby reverse-engineering project, not an official Mazda
  product, and isn't affiliated with Mazda Motor Corporation in any way.

## Which hardware do I need?

Either works with every tool in this repo -- see the comparison table in
[`docs/HARDWARE_SETUP.md`](docs/HARDWARE_SETUP.md) if you're deciding
between them. Short version: Arduino Uno + MCP2515 is cheaper and
simpler if you just want to log drives with a laptop; the ESP32-S3 board
has CAN built in (no extra module) and can run standalone with its own
WiFi web UI and onboard logging, no laptop needed once it's set up.

## What's in here

```
firmware/        Microcontroller sketches -- Arduino Uno + MCP2515 ones,
                 and esp32_-prefixed ones for the ESP32-S3 (flash ONE at a time)
tools/           Python scripts that talk to either board over serial
hud_overlay/     Turns a recorded drive into a transparent overlay video
scripts/         Double-click Windows tools -- no typing required
docs/            Setup guide (both boards), confirmed signal reference, GitHub guide
examples/        A real (short) sample drive log to test the renderer with
```

## Easiest way to use this (Windows, no typing)

If you're on Windows and don't want to type any commands, double-click
these in the [`scripts/`](scripts/) folder instead:

| Double-click this | What it does |
|---|---|
| `watch_live.bat` | Connects to your board and shows live data on screen -- good for checking your wiring before you drive. Nothing is saved. |
| `start_logging.bat` | Connects to your board and records your drive to a timestamped CSV in a new `recordings/` folder. Press Ctrl+C in the window when you're done driving. |
| `render_video.bat` | Picks a recording from `recordings/` (or any CSV you point it at) and turns it into a transparent overlay video, horizontal or vertical. |

Each one finds your board's COM port automatically, or asks you to pick
it if there's more than one device plugged in. You still need to have
flashed `firmware/can_live/can_live.ino` (Arduino) or
`firmware/esp32_can_live/esp32_can_live.ino` (ESP32) first, and run
`pip install -r requirements.txt` once (see
[`docs/HARDWARE_SETUP.md`](docs/HARDWARE_SETUP.md)) -- the scripts will
tell you if something's missing.

## Doing it from the command line instead

The scripts above are just thin wrappers around these -- use them
directly if you'd rather type commands or you're not on Windows.

## The tools, at a glance

| I want to... | Flash this firmware | Run this |
|---|---|---|
| Find NEW, unmapped signals on my own car (passive) | `can_discovery/can_discovery.ino` (Arduino) or `esp32_can_discovery/esp32_can_discovery.ino` (ESP32) | `python tools/discover_ids.py --port COM6` |
| Watch everything this toolkit already knows, live | `can_live/can_live.ino` (Arduino) or `esp32_can_live/esp32_can_live.ino` (ESP32) | `python tools/live_dashboard.py --port COM6` |
| Record a drive to a CSV file | same as above | `python tools/record_drive.py --port COM6 --out my_drive.csv` |
| Find which diagnostic modules exist on my car | `uds_bridge/uds_bridge.ino` (Arduino) or `esp32_uds_bridge/esp32_uds_bridge.ino` (ESP32) | `python tools/discover_modules.py --port COM6` |
| Hunt for new DIDs on a known module | same as above | `python tools/discover_dids.py --port COM6` |
| Turn a recorded CSV into an overlay video | *(no board needed)* | `python hud_overlay/render_overlay.py --csv my_drive.csv --config hud_overlay/configs/horizontal_1080p.json --out my_drive_hud.mov` |
| Log standalone, no laptop, with a web UI | `esp32_web_logger/esp32_web_logger.ino` (**ESP32 only**) | nothing -- it's a web page, see below |

All `firmware/` sketches live in `firmware/<name>/<name>.ino` (e.g.
`firmware/can_live/can_live.ino`). Your board can only run one sketch at
a time -- re-flash it with the Arduino IDE when you want to switch
tools. See [`docs/HARDWARE_SETUP.md`](docs/HARDWARE_SETUP.md) for
wiring, library installation, and how to flash a sketch on either board.

Every Python script supports `--help` for the full list of options, and
`--port` defaults to `COM6` (Windows) -- pass your own if yours is
different (see "Finding your serial port" in the hardware guide). The
Python tools don't know or care which board is on the other end of the
serial port -- both boards' firmware speak the identical line format.

## Quick start

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Flash can_live.ino (Arduino) or esp32_can_live.ino (ESP32) to your board
#    (see docs/HARDWARE_SETUP.md for your specific board)

# 3. Record a drive (Ctrl+C when you're done driving)
python tools/record_drive.py --port COM6 --rate 20 --out my_drive.csv

# 4. Render it as a transparent overlay video (needs ffmpeg on PATH)
python hud_overlay/render_overlay.py \
    --csv my_drive.csv \
    --config hud_overlay/configs/horizontal_1080p.json \
    --out my_drive_hud.mov

# Drop my_drive_hud.mov on a track above your dash-cam footage in
# Premiere (or any editor that supports alpha-channel video)
```

Want to try the renderer right now without any hardware? There's a real
sample recording included:

```bash
python hud_overlay/render_overlay.py \
    --csv examples/sample_drive_log.csv \
    --config hud_overlay/configs/horizontal_1080p.json \
    --out sample_hud.mov
```

### Digital cluster style

A game-style cluster: gradient RPM line that blinks at the 6500 RPM rev
limiter, an ABS lamp and steering wheel on the left, MPH in the middle,
gear on the right, and a curved band of brake (red) / throttle (green)
segments below.

The ABS lamp lights when a front wheel locks up: while you're off the
throttle and above 10 mph, a front wheel turning 25% slower than the fastest
wheel counts. Rear lockups (handbrake turns) are ignored on purpose; the rears
still count toward the reference speed, so locking both fronts is caught.
It needs the `wheel_fl,wheel_fr,wheel_rl,wheel_rr` columns, which
`tools/record_drive.py` now logs (older recordings just leave the lamp off).
Thresholds are in the `abs` section of the config.

```bash
python hud_overlay/render_overlay.py \
    --csv my_drive.csv \
    --config hud_overlay/configs/cluster_1080p.json \
    --out my_drive_hud_cluster.mov
```


### Vertical video (Instagram Reels/Stories)

```bash
python hud_overlay/render_overlay.py \
    --csv my_drive.csv \
    --config hud_overlay/configs/vertical_reels.json \
    --width 1080 --height 1920 \
    --out my_drive_hud_vertical.mov
```

## What each overlay looks like

One preview frame per config in `hud_overlay/configs/` (same data in each:
58 mph, 3rd gear, 5,400 RPM, 62% throttle, wheel turned 22° left), so you
can pick one before rendering a whole video.

| `panel_default.json` | `horizontal_1080p.json` |
|---|---|
| ![panel_default](docs/overlays/panel_default.png) | ![horizontal_1080p](docs/overlays/horizontal_1080p.png) |
| **`cluster_1080p.json`** | **`vertical_reels.json`** (1080x1920) |
| ![cluster_1080p](docs/overlays/cluster_1080p.png) | <img src="docs/overlays/vertical_reels.png" width="240" alt="vertical_reels"> |

To preview your own drive with any config, render a single frame:

```bash
python hud_overlay/render_overlay.py --csv my_drive.csv \
    --config hud_overlay/configs/cluster_1080p.json \
    --preview 12.5 --preview-out frame.png
```

## How the signals were found

See [`docs/FINDINGS.md`](docs/FINDINGS.md) for the full reference: every
CAN ID, byte offset, and formula this toolkit decodes, how each one was
confirmed, and a couple of dead ends that are worth knowing about if you
go exploring further with `discover_ids.py`.

## Going beyond the CAN bus: UDS diagnostic exploration

Everything above works by passively listening -- it only sees signals
the car already broadcasts on its own. Some data (this project went
looking for tire pressure, for one) isn't broadcast at all; it only
exists behind an active diagnostic request (UDS, the same protocol a
dealer's scan tool uses). Two tools for exploring that, read-only, on
either board:

1. **`discover_modules.py`** -- you don't start by knowing which modules
   exist or what their CAN IDs are. This sends a safe TesterPresent
   request across a range of IDs (0x700-0x7FF by default, the
   conventional manufacturer diagnostic block) and reports which ones
   answer. Run this first.
2. **`discover_dids.py`** -- once you know a module's request/response
   ID pair, this sweeps `ReadDataByIdentifier` across the DID range
   looking for anything that responds. A full 16-bit sweep of one module
   takes hours; narrow it with `--start`/`--end` once you have a hunch,
   or `--module` to focus on just one.

Flash `firmware/uds_bridge/uds_bridge.ino` (Arduino) or
`firmware/esp32_uds_bridge/esp32_uds_bridge.ino` (ESP32) -- both are a
raw CAN-to-serial bridge; all the UDS/ISO-TP protocol logic lives in
Python, in `tools/uds_iso_tp.py`, so the same two scripts work against
either. Both firmware variants only ever forward TesterPresent or
ReadDataByIdentifier requests -- never ECUReset, WriteDataByIdentifier,
RoutineControl, or SecurityAccess, so there's nothing here that can
command or control anything on the car.

This is slower, more exploratory, and less immediately useful than the
passive tools above -- expect a lot of "nothing here" responses before
finding something real. Run it with the car **key on, engine off**.

## ESP32-only: standalone WiFi logging (`esp32_web_logger`)

This one has no Arduino Uno equivalent -- it needs the ESP32's WiFi and
flash storage. No laptop, no USB tether needed once it's flashed. The
ESP32 hosts its own WiFi network and a web page served straight off the
board.

**What it does:**
- Live telemetry (RPM, speed, gear, throttle, brake, steering) updating
  a few times a second, viewable from any phone or laptop browser.
- A **Start Recording** / **Stop Recording** button -- no need to plug in
  anything to begin a log.
- Logs are saved as CSV straight to the board's own flash (9.9MB of
  storage, no SD card -- SD cards turned out to be unreliable in this
  project's earlier standalone-logging attempts, so this avoids that
  entirely).
- From the same page: see every saved log with its size, **rename** it,
  **download** it, or **delete** it.
- Downloaded logs are in the exact same CSV format `record_drive.py`
  produces -- run them straight through `hud_overlay/render_overlay.py`
  unmodified.

**Flashing it:** same as Option B in `docs/HARDWARE_SETUP.md`, plus the
Partition Scheme / Flash Size settings noted there (only this sketch
needs those).

**Using it:**

1. On your phone or laptop, join the WiFi network **`Mazda3-Telemetry`**
   (password `mazda3can` -- change `AP_SSID`/`AP_PASS` at the top of the
   `.ino` if you want your own).
2. Open `http://192.168.4.1/` in a browser.
3. Hit **Start Recording** before you drive, **Stop Recording** after.
4. Rename it to something you'll recognize later, or just download it
   and go render the video.

No internet connection involved anywhere in this -- the page and all its
code are served directly from the ESP32's flash.

## License

MIT -- see [`LICENSE`](LICENSE). Use it, modify it, share it, just keep
the copyright notice.
