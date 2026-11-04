// esp32_uds_bridge.ino -- ESP32-S3 port of uds_bridge.ino. Bidirectional
// raw CAN <-> serial bridge used by tools/discover_modules.py and
// tools/discover_dids.py. Protocol logic (UDS request framing, ISO-TP
// multi-frame reassembly) lives in Python on the host (tools/uds_iso_tp.py);
// this sketch just transmits/receives raw frames over the same simple
// fixed-width text protocol the Arduino Uno version uses, so the same
// Python tools work against either board unmodified.
//
// Software-filtered to CAN IDs 0x700-0x7FF -- the conventional
// manufacturer diagnostic address block -- so normal bus broadcast
// traffic doesn't flood the 115200 baud serial link while scanning, but
// without hardcoding specific module IDs, so it works for discovering
// modules you don't already know about, not just querying known ones.
// (Done in software here, unlike the Uno/MCP2515 version's hardware
// filter banks -- the ESP32-S3's TWAI controller doesn't have an
// equivalent range-filter mechanism that's worth fighting with, and
// checking one `if` per received frame costs nothing.)
//
// Host -> ESP32 (transmit a request):
//   T<id:3hex><dlc:1hex><data:16hex padded>\n
//   e.g. T73003E800000000000000\n
//
// ESP32 -> Host (received frame):
//   R<id:3hex><dlc:1hex><data:16hex padded>\n
//
// See firmware/esp32_can_live/esp32_can_live.ino for the board/pinout
// this was built for, and docs/HARDWARE_SETUP.md for the full writeup
// including the "USB CDC On Boot" setting this needs.
#include "driver/twai.h"

const gpio_num_t CAN_TX_PIN = GPIO_NUM_15;
const gpio_num_t CAN_RX_PIN = GPIO_NUM_16;

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
    Serial.begin(115200);  // matches uds_iso_tp.py's RawBridge default baud
    while (!Serial) delay(10);

    twai_general_config_t g_config =
        TWAI_GENERAL_CONFIG_DEFAULT(CAN_TX_PIN, CAN_RX_PIN, TWAI_MODE_NORMAL);
    twai_timing_config_t t_config = TWAI_TIMING_CONFIG_500KBITS();
    twai_filter_config_t f_config = TWAI_FILTER_CONFIG_ACCEPT_ALL();

    if (twai_driver_install(&g_config, &t_config, &f_config) != ESP_OK) {
        Serial.println("ERROR: twai_driver_install failed");
        while (true) delay(1000);
    }
    if (twai_start() != ESP_OK) {
        Serial.println("ERROR: twai_start failed");
        while (true) delay(1000);
    }

    Serial.println("READY");
}

void handleLine() {
    if (lineLen < 1 || lineBuf[0] != 'T') return;
    if (lineLen < 1 + 3 + 1) return;

    uint32_t id = (hexNibble(lineBuf[1]) << 8) | (hexNibble(lineBuf[2]) << 4) | hexNibble(lineBuf[3]);
    uint8_t dlc = hexNibble(lineBuf[4]);
    if (dlc > 8) dlc = 8;

    twai_message_t msg = {};
    msg.identifier = id;
    msg.data_length_code = dlc;
    msg.extd = 0;
    for (uint8_t i = 0; i < dlc; i++) {
        uint8_t pos = 5 + i * 2;
        if (pos + 1 < lineLen) {
            msg.data[i] = hexByte(&lineBuf[pos]);
        } else {
            msg.data[i] = 0;
        }
    }
    twai_transmit(&msg, pdMS_TO_TICKS(10));
}

void loop() {
    // drain any pending RX from the TWAI controller, forwarding only
    // 0x700-0x7FF (the diagnostic address block) -- see header comment
    twai_message_t frame;
    while (twai_receive(&frame, 0) == ESP_OK) {
        if (frame.identifier < 0x700 || frame.identifier > 0x7FF) continue;

        Serial.print('R');
        if (frame.identifier < 0x100) Serial.print('0');
        if (frame.identifier < 0x10) Serial.print('0');
        Serial.print(frame.identifier, HEX);
        Serial.print(frame.data_length_code, HEX);
        for (uint8_t i = 0; i < 8; i++) {
            uint8_t v = (i < frame.data_length_code) ? frame.data[i] : 0;
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
