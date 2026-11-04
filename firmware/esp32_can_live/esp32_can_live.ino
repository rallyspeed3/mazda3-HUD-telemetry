// esp32_can_live.ino -- reads the same 6 confirmed Mazda3 signals using the
// ESP32-S3's BUILT-IN TWAI (CAN) controller and this board's onboard CAN
// transceiver. No MCP2515 module, no SPI, no extra library -- `driver/twai.h`
// ships with the ESP32 Arduino core.
//
// Board: UeeKKoo/Waveshare-style "ESP32-S3-RS485-CAN" industrial control
// board (Amazon ASIN B0H6QDQGPC -- same board is also sold under the
// Waveshare brand). Streams the exact same serial line format as
// firmware/can_live/can_live.ino (the Arduino Uno + MCP2515 version), so
// the same tools/ scripts work against either board unmodified.
//
// Pinout confirmed from Waveshare's own official demo firmware for this
// exact board (WS_GPIO.h, from the "Online Development Resources" link in
// the product listing -- not guessed):
//   CAN TX (TWAI TXD) -> GPIO15
//   CAN RX (TWAI RXD) -> GPIO16
// The onboard isolated CAN transceiver handles everything else (CAN-H/
// CAN-L go to the board's CAN screw terminal -- see the board's silkscreen
// / wiki for which terminal is which).
//
// *** IMPORTANT: "USB CDC On Boot" must be set to "Enabled" ***
// This board has native USB (no separate USB-serial chip), so the Arduino
// Serial object does NOT work over the USB cable unless USB CDC On Boot is
// turned on. In the Arduino IDE: Tools -> USB CDC On Boot -> "Enabled",
// before uploading. If you flash this and get nothing at all on any COM
// port, this is almost certainly why -- confirmed in Waveshare's own FAQ
// for this board.
#include "driver/twai.h"

const gpio_num_t CAN_TX_PIN = GPIO_NUM_15;
const gpio_num_t CAN_RX_PIN = GPIO_NUM_16;

// The 6 IDs this toolkit has confirmed decodes for -- see the original
// repo's docs/FINDINGS.md. Unlike the Uno + MCP2515 version, the ESP32-S3's
// TWAI controller has no small hardware-filter-bank limit, so we just
// accept everything off the bus and filter in software -- add or remove
// IDs here freely, no 6-ID cap.
const uint32_t TARGET_IDS[] = {0x201, 0x20F, 0x4B0, 0x231, 0x433, 0x082};
const int NUM_IDS = sizeof(TARGET_IDS) / sizeof(TARGET_IDS[0]);

bool is_target_id(uint32_t id) {
    for (int i = 0; i < NUM_IDS; i++) {
        if (TARGET_IDS[i] == id) return true;
    }
    return false;
}

void setup() {
    Serial.begin(1000000);
    while (!Serial);

    twai_general_config_t g_config =
        TWAI_GENERAL_CONFIG_DEFAULT(CAN_TX_PIN, CAN_RX_PIN, TWAI_MODE_NORMAL);
    twai_timing_config_t t_config = TWAI_TIMING_CONFIG_500KBITS();  // Mazda OEM bus speed
    twai_filter_config_t f_config = TWAI_FILTER_CONFIG_ACCEPT_ALL();

    if (twai_driver_install(&g_config, &t_config, &f_config) != ESP_OK) {
        Serial.println("ERROR: twai_driver_install failed");
        while (true) delay(1000);
    }
    if (twai_start() != ESP_OK) {
        Serial.println("ERROR: twai_start failed");
        while (true) delay(1000);
    }

    Serial.println("esp32_can_live ready.");
}

void loop() {
    twai_message_t msg;
    // Non-blocking: drain everything currently queued each pass.
    while (twai_receive(&msg, 0) == ESP_OK) {
        if (!is_target_id(msg.identifier)) continue;

        Serial.print(millis());
        Serial.print("  ");
        if (msg.identifier < 0x100) Serial.print("0");
        if (msg.identifier < 0x10) Serial.print("0");
        Serial.print(msg.identifier, HEX);
        Serial.print("  [");
        Serial.print(msg.data_length_code);
        Serial.print("]  ");
        for (int i = 0; i < msg.data_length_code; i++) {
            if (msg.data[i] < 0x10) Serial.print("0");
            Serial.print(msg.data[i], HEX);
            Serial.print(" ");
        }
        Serial.println();
    }
}
