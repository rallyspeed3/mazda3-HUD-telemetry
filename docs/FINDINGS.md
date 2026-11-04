# Confirmed CAN bus signals

Everything below was reverse-engineered by passively sniffing the CAN
bus on a specific car:

> **2013 Mazdaspeed3, BL platform (2nd-gen Mazda3, 2010-2013), 6-speed manual.**

It will very likely also work, unchanged, on other BL-platform Mazda3 /
Mazdaspeed3 cars (2010-2013). It may partially work on related platforms
(e.g. BK-platform, 2004-2009 Mazda3) but that has **not** been tested --
verify every signal against something you can see with your own eyes
(a passenger watching the speedometer, a known tire pressure, etc.)
before trusting any of it, especially anything you'd use while driving.

Bus: 500 kbps, standard 11-bit IDs, tapped at OBD2 pins 6 (CAN-H) and 14
(CAN-L).

All byte offsets below are 0-indexed into the 8-byte CAN data payload.

## Quick reference

| Signal | CAN ID | Bytes | Formula |
|---|---|---|---|
| RPM | `0x201` | 0-1 | `raw` (big-endian, unscaled -- RPM directly) |
| Accelerator pedal | `0x201` | 6 | `raw / 255 * 100` (%) |
| Brake force (analog) | `0x20F` | 0-1 | `raw - 30000`, clamped to 0 (range ~0-10000) |
| Speed (confirmed accurate) | `0x20F` | 2-3 | `(raw - 10000) / 100` km/h |
| Per-wheel speed (FL,FR,RL,RR) | `0x4B0` | 0-1, 2-3, 4-5, 6-7 | same formula as speed, one pair of bytes per wheel |
| Steering angle | `0x082` | 2-3 | signed 16-bit, `raw / 10` degrees (see caveat below) |
| Gear position | `0x231` | 0 | lookup table (see below) |
| Reverse gear | `0x433` | 3 | bit `0x02` set |
| Handbrake | `0x433` | 3 | bit `0x01` set |
| Brake switch (on/off only) | `0x205` | 2 | nonzero = pressed |
| Drivetrain engaged (in gear + clutch out) | `0x228` | 1 | `== 0x04` |

Both `firmware/can_live/can_live.ino` (Arduino Uno + MCP2515) and
`firmware/esp32_can_live/esp32_can_live.ino` (ESP32-S3, native CAN)
stream the same 6 IDs at a time: `0x201, 0x20F, 0x4B0, 0x231, 0x433,
0x082`. That's RPM/throttle, brake/speed, wheel speeds, gear,
reverse/handbrake, and steering -- everything `tools/record_drive.py`
and `tools/live_dashboard.py` use. On the Uno this 6-ID cap is a real
hardware limit (the MCP2515 chip's filter banks); on the ESP32 it isn't
-- its TWAI controller filters in software, so you could stream more
than 6 if you wanted, but both sketches use the same 6 for parity, so
either board's output is interchangeable. If you want the brake switch
(`0x205`) or drivetrain-engaged (`0x228`) signals instead, swap one of
the 6 IDs in `TARGET_IDS` in whichever `can_live` sketch you're using
(and update whichever Python tool you're using to decode the new one
instead).

## Gear position lookup table (`0x231` byte 0)

| Raw byte | Gear |
|---|---|
| `0x00` or `0x01` | Neutral |
| `0x11` | 1st |
| `0x20` | 2nd |
| `0x30` | 3rd |
| `0x40` | 4th |
| `0x50` | 5th |
| `0x60` | 6th |

**Important caveat:** this signal only updates while the car is actually
**moving**. At key-on-engine-off or while idling stationary, it stays
dead/unchanged no matter what gear you select. It was confirmed working
by watching it change correctly during real driving across all 6 gears.

## Steering angle caveat

`0x082` only starts reporting real values once the engine is running
(RPM above roughly 500) -- at key-on-engine-off it reads a stale/fixed
value. Confirmed via a hand-crank test (turning the wheel a known amount
with the engine running and checking the reported degrees matched).

## Known-wrong signal -- don't use

`0x201` bytes 4-5 looked like a second speed reading (same formula as the
confirmed one) but was confirmed **wrong** -- it read nonsense values at
standstill. Use `0x20F` bytes 2-3 for speed instead; that one was
confirmed to read exactly 0 while stationary and track real speed while
driving.

## Things that were investigated and found to be dead ends (on this car)

- `0x4DA` -- a commonly-cited steering angle ID for related Mazda
  platforms. Confirmed dead/unused on this car; use `0x082` instead.

## Beyond passive CAN signals

Everything above is read straight off broadcast CAN traffic. Some data
isn't broadcast at all and only exists behind an active UDS diagnostic
request -- `tools/discover_modules.py` and `tools/discover_dids.py`
explore that (see the README's "Going beyond the CAN bus" section).
Nothing from that exploration is documented here yet -- anything found
that way needs the same standard this file holds everything else to:
confirmed against something verifiable in the real world, not just "the
module answered with something."
