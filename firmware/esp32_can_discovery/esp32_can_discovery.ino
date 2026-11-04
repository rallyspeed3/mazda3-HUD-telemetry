// esp32_can_discovery.ino -- ESP32-S3 port of can_discovery.ino. Accepts
// EVERY ID on the bus and keeps a running table of the latest 8 data
// bytes seen per ID, so you can find new, unmapped signals on your own
// car. Pairs with tools/discover_ids.py -- same snapshot protocol as the
// Arduino Uno version, so the same Python tool works against either
// board unmodified.
//
// Uses the ESP32-S3's built-in TWAI (CAN) controller -- see
// firmware/esp32_can_live/esp32_can_live.ino for the board/pinout this
// was built for (UeeKKoo/Waveshare "ESP32-S3-RS485-CAN"), and
// docs/HARDWARE_SETUP.md for the full writeup including the
// "USB CDC On Boot" setting this needs.
#include "driver/twai.h"

const gpio_num_t CAN_TX_PIN = GPIO_NUM_15;
const gpio_num_t CAN_RX_PIN = GPIO_NUM_16;

const int MAX_IDS = 80;
uint16_t table_id[MAX_IDS];
uint8_t table_dlc[MAX_IDS];
uint8_t table_data[MAX_IDS][8];
int table_count = 0;

// IDs this toolkit already has a confirmed decode for (see
// docs/FINDINGS.md) -- skipped here so the grid only shows what's still
// unknown on your car. Remove entries (or add your own finds) as you go.
const uint16_t SKIP_IDS[] = {
    0x201,  // accelerator pedal + RPM
    0x205,  // brake switch
    0x20F,  // brake force + speed
    0x228,  // drivetrain engaged (in gear + clutch out)
    0x231,  // gear position
    0x433,  // reverse + handbrake
    0x082,  // steering angle
    0x4B0,  // per-wheel speed
};
const int NUM_SKIP_IDS = 8;

bool is_skipped(uint16_t id) {
    for (int i = 0; i < NUM_SKIP_IDS; i++) {
        if (SKIP_IDS[i] == id) return true;
    }
    return false;
}

unsigned long last_dump = 0;
const unsigned long DUMP_INTERVAL_MS = 180;

void setup() {
    Serial.begin(115200);  // matches discover_ids.py's fixed baud -- not the 1Mbaud streaming sketches use
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

    Serial.println("esp32_can_discovery ready.");
}

void upsert(uint16_t id, uint8_t dlc, uint8_t *data) {
    if (is_skipped(id)) return;
    for (int i = 0; i < table_count; i++) {
        if (table_id[i] == id) {
            table_dlc[i] = dlc;
            memcpy(table_data[i], data, 8);
            return;
        }
    }
    if (table_count < MAX_IDS) {
        table_id[table_count] = id;
        table_dlc[table_count] = dlc;
        memcpy(table_data[table_count], data, 8);
        table_count++;
    }
    // table full: silently drop new IDs, keep tracking ones we already have
}

void dump_table() {
    Serial.println("===SNAPSHOT===");
    for (int i = 0; i < table_count; i++) {
        if (table_id[i] < 0x100) Serial.print("0");
        if (table_id[i] < 0x10) Serial.print("0");
        Serial.print(table_id[i], HEX);
        Serial.print(" ");
        Serial.print(table_dlc[i]);
        Serial.print(" ");
        for (int b = 0; b < 8; b++) {
            if (table_data[i][b] < 0x10) Serial.print("0");
            Serial.print(table_data[i][b], HEX);
            if (b < 7) Serial.print(" ");
        }
        Serial.println();
    }
    Serial.println("===END===");
}

void loop() {
    twai_message_t msg;
    while (twai_receive(&msg, 0) == ESP_OK) {
        upsert(msg.identifier, msg.data_length_code, msg.data);
    }
    unsigned long now = millis();
    if (now - last_dump >= DUMP_INTERVAL_MS) {
        last_dump = now;
        dump_table();
    }
}
