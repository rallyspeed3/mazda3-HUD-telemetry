// uds_bridge.ino -- bidirectional raw CAN <-> serial bridge, used by
// tools/discover_modules.py and tools/discover_dids.py (not by anything
// in the passive-logging side of this toolkit). Protocol logic (UDS
// request framing, ISO-TP multi-frame reassembly) lives in Python on the
// host; this sketch just transmits/receives raw frames as fast as
// possible over a simple fixed-width text protocol.
//
// Hardware-filtered to CAN IDs 0x700-0x7FF -- the conventional
// manufacturer diagnostic address block -- so normal bus broadcast
// traffic doesn't flood the 115200 baud serial link while scanning, but
// without hardcoding specific module IDs, so it works for discovering
// modules you don't already know about, not just querying known ones.
//
// Host -> Arduino (transmit a request):
//   T<id:3hex><dlc:1hex><data:16hex padded>\n
//   e.g. T73003E800000000000000\n
//
// Arduino -> Host (received frame):
//   R<id:3hex><dlc:1hex><data:16hex padded>\n
//
// Wiring: same as the other sketches -- see docs/HARDWARE_SETUP.md.
#include <mcp2515.h>
#include <SPI.h>

const int SPI_CS_PIN = 10;
MCP2515 mcp2515(SPI_CS_PIN);

char lineBuf[64];
uint8_t lineLen = 0;

uint8_t hexNibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return 0;
}

uint8_t hexByte(const char *s) {
    return (hexNibble(s[0]) << 4) | hexNibble(s[1]);
}

void setup() {
    Serial.begin(115200);
    while (!Serial);
    SPI.begin();

    mcp2515.reset();

    // mask=0x700, filter=0x700 on every RX buffer: accepts any ID whose
    // top 3 bits are 111 -- i.e. the whole 0x700-0x7FF range (256 IDs) --
    // and rejects everything else, including the TARGET_IDS signals
    // can_live.ino streams.
    mcp2515.setFilterMask(MCP2515::MASK0, false, 0x700);
    mcp2515.setFilterMask(MCP2515::MASK1, false, 0x700);
    mcp2515.setFilter(MCP2515::RXF0, false, 0x700);
    mcp2515.setFilter(MCP2515::RXF1, false, 0x700);
    mcp2515.setFilter(MCP2515::RXF2, false, 0x700);
    mcp2515.setFilter(MCP2515::RXF3, false, 0x700);
    mcp2515.setFilter(MCP2515::RXF4, false, 0x700);
    mcp2515.setFilter(MCP2515::RXF5, false, 0x700);

    mcp2515.setBitrate(CAN_500KBPS, MCP_8MHZ);
    mcp2515.setNormalMode();

    Serial.println("READY");
}

void handleLine() {
    if (lineLen < 1 || lineBuf[0] != 'T') return;
    if (lineLen < 1 + 3 + 1) return;

    uint32_t id = (hexNibble(lineBuf[1]) << 8) | (hexNibble(lineBuf[2]) << 4) | hexNibble(lineBuf[3]);
    uint8_t dlc = hexNibble(lineBuf[4]);
    if (dlc > 8) dlc = 8;

    struct can_frame frame;
    frame.can_id = id;
    frame.can_dlc = dlc;
    for (uint8_t i = 0; i < dlc; i++) {
        uint8_t pos = 5 + i * 2;
        if (pos + 1 < lineLen) {
            frame.data[i] = hexByte(&lineBuf[pos]);
        } else {
            frame.data[i] = 0;
        }
    }
    mcp2515.sendMessage(&frame);
}

void loop() {
    // drain any pending RX from the MCP2515
    struct can_frame frame;
    while (mcp2515.readMessage(&frame) == MCP2515::ERROR_OK) {
        Serial.print('R');
        if (frame.can_id < 0x100) Serial.print('0');
        if (frame.can_id < 0x10) Serial.print('0');
        Serial.print(frame.can_id, HEX);
        Serial.print(frame.can_dlc, HEX);
        for (uint8_t i = 0; i < 8; i++) {
            uint8_t v = (i < frame.can_dlc) ? frame.data[i] : 0;
            if (v < 0x10) Serial.print('0');
            Serial.print(v, HEX);
        }
        Serial.println();
    }

    // drain any pending TX commands from serial
    while (Serial.available()) {
        char c = Serial.read();
        if (c == '\n' || c == '\r') {
            if (lineLen > 0) {
                handleLine();
                lineLen = 0;
            }
        } else if (lineLen < sizeof(lineBuf) - 1) {
            lineBuf[lineLen++] = c;
        }
    }
}
