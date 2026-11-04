#!/usr/bin/env python3
"""ISO-TP (ISO 15765-2) + UDS request/response over firmware/uds_bridge.ino.
The bridge just ferries raw CAN frames over serial; all protocol logic
(multi-frame reassembly, flow control) lives here.

Only implements what's needed: single-frame TX (requests are always
short -- a service byte plus up to 2 bytes of DID), and both single- and
multi-frame RX (responses, e.g. a VIN, can be long).

Used by discover_modules.py and discover_dids.py. Deliberately only ever
sends read-only, non-destructive UDS services (TesterPresent,
ReadDataByIdentifier) -- never ECUReset, WriteDataByIdentifier,
RoutineControl, SecurityAccess, or a non-default diagnostic session.
"""
import time

import serial

# module request-id -> response-id, discovered on this car during a
# discover_modules.py scan -- see docs/FINDINGS.md. Likely different on
# your car; re-run the scan rather than assuming these.
MODULES = {
    "720": "728",
    "726": "72E",
    "730": "738",
    "737": "73F",
    "760": "768",
    "7F1": "7F9",
}


class RawBridge:
    def __init__(self, port, baud=115200):
        self.ser = serial.Serial(port, baudrate=baud, timeout=0.05)
        time.sleep(0.3)
        self.ser.reset_input_buffer()
        self._buf = b""

    def send_frame_exact(self, can_id, data, dlc):
        data = bytes(data) + b"\x00" * (8 - len(data))
        line = f"T{can_id:03X}{dlc:01X}" + data.hex().upper() + "\n"
        self.ser.write(line.encode())

    def poll_frame(self, deadline):
        """Read one 'Rxxxyhhhh...' line if available before deadline, else None.
        Returns (can_id, dlc, data_bytes) or None."""
        while time.time() < deadline:
            n = self.ser.in_waiting
            if n:
                self._buf += self.ser.read(n)
            if b"\n" in self._buf:
                line, self._buf = self._buf.split(b"\n", 1)
                text = line.decode(errors="replace").strip()
                if text.startswith("R") and len(text) >= 1 + 3 + 1 + 16:
                    try:
                        can_id = int(text[1:4], 16)
                        dlc = int(text[4], 16)
                        data = bytes.fromhex(text[5:5 + 16])
                        return can_id, dlc, data[:dlc]
                    except ValueError:
                        continue
                continue
            time.sleep(0.001)
        return None

    def close(self):
        self.ser.close()


def uds_request(bridge, req_id_hex, resp_id_hex, payload, timeout=0.15):
    """Send a UDS request (payload = service byte + params, <=7 bytes) and
    return the full reassembled response payload (service byte onward), or
    None on timeout. Only looks at frames on resp_id_hex -- use this when
    you already know which module you're talking to (see discover_dids.py).
    For discovering unknown modules, poll_frame() directly instead (see
    discover_modules.py)."""
    req_id = int(req_id_hex, 16)
    resp_id = int(resp_id_hex, 16)

    assert len(payload) <= 7, "single-frame TX only"
    pci = len(payload)
    bridge.send_frame_exact(req_id, bytes([pci]) + bytes(payload), 8)

    deadline = time.time() + timeout
    result = None
    expected_len = None

    while time.time() < deadline:
        frame = bridge.poll_frame(deadline)
        if frame is None:
            break
        can_id, dlc, data = frame
        if can_id != resp_id or not data:
            continue
        pci_byte = data[0]
        frame_type = pci_byte >> 4

        if frame_type == 0x0:
            # single frame
            length = pci_byte & 0x0F
            return data[1:1 + length]

        elif frame_type == 0x1:
            # first frame: 12-bit length across low nibble + next byte
            expected_len = ((pci_byte & 0x0F) << 8) | data[1]
            result = bytearray(data[2:8])
            # send flow control: continue-to-send, block-size=0, STmin=0
            bridge.send_frame_exact(req_id, bytes([0x30, 0x00, 0x00]), 8)
            deadline = time.time() + timeout  # reset budget for the rest

        elif frame_type == 0x2:
            if result is None:
                continue
            result.extend(data[1:8])
            if len(result) >= expected_len:
                return bytes(result[:expected_len])

    return None
