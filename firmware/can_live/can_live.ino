// can_live.ino -- streams the 6 confirmed signals from this toolkit's
// FINDINGS.md live over serial, as fast as the bus allows.
//
// This is the "main" firmware: every Python tool in tools/ (except
// discover_ids.py) talks to this sketch.
//
// Hardware filtering (not a software/library filter -- the MCP2515 chip
// itself drops anything that doesn't match) keeps the serial link from
// getting flooded, since the full bus has far more traffic than just
// these 6 IDs.
//
// Wiring: MCP2515 module -- VCC=5V, GND=GND, CS=10, SO(MISO)=12,
// SI(MOSI)=11, SCK=13. CAN-H/CAN-L go to your OBD2 tap. See
// docs/HARDWARE_SETUP.md for the full wiring + parts list.
//
// Each serial line looks like:
//   <millis>  <id hex>  [<dlc>]  <data bytes, space separated hex>
// e.g.
//   1830  201  [8]  00 00 40 00 00 00 01 00
//
// Needs the autowp/arduino-mcp2515 library (Library Manager: "mcp2515"
// by autowp works too).
#include <mcp2515.h>
#include <SPI.h>

const int SPI_CS_PIN = 10;
MCP2515 mcp2515(SPI_CS_PIN);

// The 6 IDs this toolkit has confirmed decodes for -- see docs/FINDINGS.md.
// Edit this list (max 6, that's a hardware limit of the MCP2515's filter
// banks) if you want to swap one out for something you're investigating.
const uint32_t TARGET_IDS[] = {0x201, 0x20F, 0x4B0, 0x231, 0x433, 0x082};
const int NUM_IDS = 6;

void setup() {
    // 1,000,000 baud, not the usual 115200: at 115200 a single Serial.print()
    // line takes long enough to transmit that a burst of frames arriving
    // close together (e.g. during a gear shift) can overflow the MCP2515's
    // 2-frame hardware RX buffer while we're still busy printing the
    // previous line, silently dropping frames. 1Mbaud shrinks that window
    // enough that it stops happening in practice.
    Serial.begin(1000000);
    while (!Serial);
    SPI.begin();

    mcp2515.reset();

    // exact-match filters (0x7FF mask = all 11 bits must match)
    mcp2515.setFilterMask(MCP2515::MASK0, false, 0x7FF);
    mcp2515.setFilterMask(MCP2515::MASK1, false, 0x7FF);

    MCP2515::RXF slots[] = {
        MCP2515::RXF0, MCP2515::RXF1, MCP2515::RXF2,
        MCP2515::RXF3, MCP2515::RXF4, MCP2515::RXF5
    };
    for (int i = 0; i < NUM_IDS && i < 6; i++) {
        mcp2515.setFilter(slots[i], false, TARGET_IDS[i]);
    }
    // unused slots: filter on an ID that will never appear, so they don't
    // default to passing everything through
    for (int i = NUM_IDS; i < 6; i++) {
        mcp2515.setFilter(slots[i], false, 0x7FF);
    }

    mcp2515.setBitrate(CAN_500KBPS, MCP_8MHZ);
    mcp2515.setNormalMode();

    Serial.println("can_live ready.");
}

void loop() {
    struct can_frame frame;
    // Drain every pending frame each pass instead of reading just one --
    // see the baud-rate comment above for why that matters.
    while (mcp2515.readMessage(&frame) == MCP2515::ERROR_OK) {
        Serial.print(millis());
        Serial.print("  ");
        if (frame.can_id < 0x100) Serial.print("0");
        if (frame.can_id < 0x10) Serial.print("0");
        Serial.print(frame.can_id, HEX);
        Serial.print("  [");
        Serial.print(frame.can_dlc);
        Serial.print("]  ");
        for (int i = 0; i < frame.can_dlc; i++) {
            if (frame.data[i] < 0x10) Serial.print("0");
            Serial.print(frame.data[i], HEX);
            Serial.print(" ");
        }
        Serial.println();
    }
}
