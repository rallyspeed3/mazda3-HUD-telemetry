# Hardware setup

This toolkit works with **either** of two boards -- pick whichever you
already have lying around, or whichever fits what you want to build:

| | Arduino Uno + MCP2515 | ESP32-S3-RS485-CAN |
|---|---|---|
| Cost | ~$15 (Uno + MCP2515 module) | ~$25-30 (one board, CAN built in) |
| Extra module needed | Yes (MCP2515) | No -- CAN is built into the board |
| WiFi / standalone logging | No -- needs a laptop tethered the whole time | Yes -- `esp32_web_logger.ino` logs to its own flash and serves a web UI, no laptop needed |
| Good first choice if... | you already have an Uno, or want the simplest possible setup | you want to eventually run this standalone in the car |

Every tool in this repo has a firmware sketch for both boards -- see the
table in the main [README](../README.md). Jump to whichever option
below matches your hardware; the **Software setup**, **Finding your
serial port**, and most of **Troubleshooting** at the bottom apply to
both.

## Option A: Arduino Uno + MCP2515

### What you need

- An **Arduino Uno** (or any ATmega328P-based Uno clone)
- An **MCP2515 CAN bus module** (the common cheap breakout board, usually
  sold with a TJA1050 transceiver already on it -- look for "MCP2515 CAN
  Bus Module" on Amazon/AliExpress, a few dollars each)
  - **Check which crystal it uses -- this trips people up.** These boards
    come with either an **8MHz** or a **16MHz** crystal (look for a small
    silver can near the MCP2515 chip, usually printed "8.000" or
    "16.000"). The firmware in this repo is set for **8MHz**, which is
    what most of these boards ship with. If yours is 16MHz and you don't
    change anything, you'll get **no data at all, with no error message**
    -- see Troubleshooting below.
- A way to tap into your car's **OBD2 port**: an OBD2-to-screw-terminal
  breakout cable, or an OBD2 extension cable you don't mind cutting open
  to access CAN-H (pin 6) and CAN-L (pin 14) and ground (pin 4 or 5).
  **Do not splice directly into the OBD2 port's wiring if you want to
  keep using a normal OBD2 scan tool at the same time** -- use a
  breakout/splitter instead.
- Jumper wires, a breadboard (optional, makes prototyping easier)
- A USB cable to connect the Arduino to your computer

### Wiring: Arduino Uno <-> MCP2515

| MCP2515 pin | Arduino Uno pin |
|---|---|
| VCC | 5V |
| GND | GND |
| CS | D10 |
| SO (MISO) | D12 |
| SI (MOSI) | D11 |
| SCK | D13 |
| INT | not connected (unused by this toolkit) |

### Wiring: MCP2515 <-> car

| MCP2515 pin | OBD2 pin |
|---|---|
| CAN-H | pin 6 |
| CAN-L | pin 14 |
| GND | pin 4 or 5 |

Double-check your specific breakout board's silkscreen labels -- some
boards label the car-side terminals differently.

### Arduino-specific software setup

1. Install the [Arduino IDE](https://www.arduino.cc/en/software) (or use
   [`arduino-cli`](https://arduino.github.io/arduino-cli/) if you prefer
   the command line).
2. Install the **`arduino-mcp2515`** library (by autowp) -- in the
   Arduino IDE: Tools -> Manage Libraries -> search "mcp2515" -> install
   the one by autowp.
3. Open the sketch you want (e.g. `firmware/can_live/can_live.ino`),
   select **Tools -> Board -> Arduino Uno** and the correct **Port**,
   then **Upload**. You only have one Arduino, so you'll flash a
   different sketch depending on which tool you're about to run -- see
   the table in the main [README](../README.md).

## Option B: ESP32-S3-RS485-CAN

### What you need

- An **ESP32-S3-RS485-CAN** industrial control board (sold under a few
  brand names -- "UeeKKoo" on Amazon, also branded Waveshare; same
  board). Has CAN built in -- **no MCP2515 module, no SPI wiring at
  all.**
- The same OBD2 tap as Option A, to reach CAN-H (pin 6) and CAN-L (pin
  14).
- A USB-C cable.

### Wiring

CAN-H / CAN-L go straight to the board's onboard CAN screw terminal
(check the board's silkscreen for which terminal is which) -- that's it,
there's no module to wire up. The CAN TX/RX pins (GPIO15/GPIO16) are
fixed by the board's own internal wiring and confirmed from Waveshare's
official demo firmware; you don't need to touch them.

Passive listening only, same as Option A -- nothing in this toolkit
transmits control messages onto the bus (except the UDS exploration
tools, see the README -- same on either board).

### ESP32-specific software setup

1. Install the [Arduino IDE](https://www.arduino.cc/en/software).
2. Add ESP32 board support: File -> Preferences -> Additional Board
   Manager URLs ->
   `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json`,
   then Tools -> Board -> Boards Manager -> search "esp32" -> install the
   one by Espressif Systems (no other library needed -- the CAN driver
   ships with this board package).
3. Open the sketch you want (e.g.
   `firmware/esp32_can_live/esp32_can_live.ino`), select your ESP32-S3
   board under Tools -> Board.
4. **Tools -> USB CDC On Boot -> set to "Enabled".** This board has
   native USB (no separate USB-serial chip), so the Arduino `Serial`
   object won't work over the USB cable at all unless this is turned on
   -- if you flash a sketch and get nothing on any COM port, this
   setting is almost certainly why (confirmed in Waveshare's own FAQ for
   this board).
5. For `firmware/esp32_web_logger/esp32_web_logger.ino` only: also set
   **Tools -> Partition Scheme -> "16M Flash (3MB APP/9.9MB FATFS)"**
   and **Tools -> Flash Size -> 16MB**. The other ESP32 sketches don't
   need this. (This assumes a 16MB flash chip, confirmed on this exact
   board by flashing a one-line test sketch that prints
   `ESP.getFlashChipSize()` -- if you're using a different ESP32-S3
   board, check yours the same way rather than trusting the Tools menu's
   default, which doesn't measure your actual chip.)
6. Select the correct Port and **Upload**.

See the main [README](../README.md) for `esp32_web_logger.ino`'s
standalone WiFi logging feature -- ESP32-only, no Arduino Uno
equivalent.

## Software setup (both boards)

1. Install Python 3.9 or newer from
   [python.org](https://www.python.org/downloads/) if you don't already
   have it.
2. From this repo's root folder, install the Python dependencies:
   ```
   pip install -r requirements.txt
   ```
3. For the HUD overlay renderer only, install
   [ffmpeg](https://ffmpeg.org/download.html) and make sure it's on your
   system `PATH` (test with `ffmpeg -version` in a terminal).

The Python tools in `tools/` don't know or care which board they're
talking to -- they just read lines over a serial port, and both boards'
firmware speak the identical format. Point `--port` at whichever board
you've got plugged in.

## Finding your serial port

- **Windows**: Device Manager -> Ports (COM & LPT) -> look for something
  like "USB-SERIAL CH340 (COM6)" (Arduino Uno) or "USB Serial Device
  (COM6)" (ESP32-S3's native USB). That `COM6` (yours may be a different
  number) is what you pass as `--port`.
- **Mac**: run `ls /dev/tty.*` in a terminal -- look for something like
  `/dev/tty.usbserial-1420` or `/dev/tty.usbmodem1420`.
- **Linux**: run `ls /dev/ttyUSB*` or `ls /dev/ttyACM*` in a terminal.

## Troubleshooting

### Arduino Uno + MCP2515

**No data at all -- dashboard/log just sits empty, no errors:**

- **Wrong crystal frequency (most common cause).** This repo's firmware
  assumes an 8MHz crystal on the MCP2515 board (see the note in Option
  A's "What you need" above). If your board is 16MHz, every Arduino
  sketch in `firmware/` will silently receive nothing. Fix: open the
  `.ino` file you flashed, find the line
  `mcp2515.setBitrate(CAN_500KBPS, MCP_8MHZ);`, change `MCP_8MHZ` to
  `MCP_16MHZ`, and re-upload.
- **CAN-H and CAN-L swapped.** Double-check against the wiring table
  above -- an easy mix-up since both wires usually look identical.
- **Loose OBD2 tap.** Reseat the breakout cable in the OBD2 port and
  check your screw terminals are actually clamped on the wire, not just
  resting against it.

**Some data, but it looks like garbage or cuts in and out:**

- **Flaky USB-serial chip at 1,000,000 baud.** `can_live.ino` and
  `esp32_can_live.ino` both intentionally run the serial link at 1Mbaud
  instead of the usual 115200 (see the comment in either sketch for
  why). Most USB-serial chips handle this fine, but some very cheap
  CH340 clones are unreliable at that speed. Try a different USB cable
  first (cheap cables are a common culprit), then a different
  Arduino/USB-serial adapter if that doesn't help.
- **Wrong `--port`.** Re-check with the steps above -- it's easy to pick
  a leftover COM port from a different device.

**Arduino IDE won't compile the sketch:**

- Almost always a missing library. Tools -> Manage Libraries -> search
  "mcp2515" -> install the one **by autowp** (there are a few similarly
  named libraries; this repo's firmware is written against that one
  specifically).

### ESP32-S3-RS485-CAN

**Nothing shows up on any COM port after flashing:**

- Almost always **USB CDC On Boot** not being set to Enabled (see Option
  B's software setup above). This is the single most common ESP32
  gotcha in this repo.

**`esp32_web_logger.ino` won't boot, or logs don't save:**

- Check the Partition Scheme and Flash Size settings (see Option B
  above) -- the default partition scheme only gives the log storage
  ~1.5MB and can behave oddly on a 16MB chip if the Flash Size setting
  doesn't match the real hardware.

**Car isn't actually on (applies to either board):**

- Most signals (and always `steering_deg`) need the engine running, not
  just key-on. Try key-on-engine-running, not just accessory mode.
