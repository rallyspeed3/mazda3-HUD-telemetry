# Hardware setup

## What you need

- An **Arduino Uno** (or any ATmega328P-based Uno clone)
- An **MCP2515 CAN bus module** (the common cheap breakout board, usually
  sold with a TJA1050 transceiver already on it -- look for "MCP2515 CAN
  Bus Module" on Amazon/AliExpress, a few dollars each)
- A way to tap into your car's **OBD2 port**: an OBD2-to-screw-terminal
  breakout cable, or an OBD2 extension cable you don't mind cutting open
  to access CAN-H (pin 6) and CAN-L (pin 14) and ground (pin 4 or 5).
  **Do not splice directly into the OBD2 port's wiring if you want to
  keep using a normal OBD2 scan tool at the same time** -- use a
  breakout/splitter instead.
- Jumper wires, a breadboard (optional, makes prototyping easier)
- A USB cable to connect the Arduino to your computer

## Wiring: Arduino Uno <-> MCP2515

| MCP2515 pin | Arduino Uno pin |
|---|---|
| VCC | 5V |
| GND | GND |
| CS | D10 |
| SO (MISO) | D12 |
| SI (MOSI) | D11 |
| SCK | D13 |
| INT | not connected (unused by this toolkit) |

## Wiring: MCP2515 <-> car

| MCP2515 pin | OBD2 pin |
|---|---|
| CAN-H | pin 6 |
| CAN-L | pin 14 |
| GND | pin 4 or 5 |

Double-check your specific breakout board's silkscreen labels -- some
boards label the car-side terminals differently.

**This is passive listening only.** Nothing in this toolkit transmits
control messages onto the bus. Still, treat any direct connection to your car's CAN bus
with care: double-check your wiring before plugging into a running car,
and if anything behaves unexpectedly, disconnect the OBD2 tap first and
ask questions later.

## Software setup

1. Install the [Arduino IDE](https://www.arduino.cc/en/software) (or use
   [`arduino-cli`](https://arduino.github.io/arduino-cli/) if you prefer
   the command line).
2. Install the **`arduino-mcp2515`** library (by autowp) -- in the
   Arduino IDE: Tools -> Manage Libraries -> search "mcp2515" -> install
   the one by autowp.
3. Install Python 3.9 or newer from [python.org](https://www.python.org/downloads/)
   if you don't already have it.
4. From this repo's root folder, install the Python dependencies:
   ```
   pip install -r requirements.txt
   ```
5. For the HUD overlay renderer only, install
   [ffmpeg](https://ffmpeg.org/download.html) and make sure it's on your
   system `PATH` (test with `ffmpeg -version` in a terminal).

## Flashing a firmware sketch

Each sketch in `firmware/` is a standalone `.ino` file -- open the
`.ino` file for the one you want (e.g.
`firmware/can_live/can_live.ino`) in the Arduino IDE, select
**Tools -> Board -> Arduino Uno** and the correct **Port**, then click
**Upload**. You only have one Arduino, so you'll flash a different
sketch depending on which tool you're about to run -- see the table in
the main [README](../README.md) for which firmware pairs with which
Python tool.

## Finding your serial port

- **Windows**: Device Manager -> Ports (COM & LPT) -> look for something
  like "USB-SERIAL CH340 (COM6)" or "Arduino Uno (COM6)". That `COM6`
  (yours may be a different number) is what you pass as `--port`.
- **Mac**: run `ls /dev/tty.*` in a terminal -- look for something like
  `/dev/tty.usbserial-1420` or `/dev/tty.usbmodem1420`.
- **Linux**: run `ls /dev/ttyUSB*` or `ls /dev/ttyACM*` in a terminal.
