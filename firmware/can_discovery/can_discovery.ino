// can_discovery.ino -- accepts EVERY ID on the bus (no hardware filter)
// and keeps a running table of the latest 8 data bytes seen per ID, so
// you can find new, unmapped signals on your own car. Pairs with
// tools/discover_ids.py.
//
// Streaming every single raw frame over serial at 115200 baud can't keep
// up with real bus traffic, so instead of printing per-frame, this
// periodically dumps a full snapshot of the table (every ID, latest
// value) a few times a second. discover_ids.py renders that as a live
// grid and highlights whichever bytes just changed -- press a pedal or
// turn the wheel and watch which ID lights up.
//
// Wiring: same as can_live.ino -- see docs/HARDWARE_SETUP.md.
#include <mcp2515.h>
#include <SPI.h>

const int SPI_CS_PIN = 10;
MCP2515 mcp2515(SPI_CS_PIN);

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
    Serial.begin(115200);
    while (!Serial);
    SPI.begin();

    mcp2515.reset();
    // No filter/mask calls -- the MCP2515's power-on default masks are
    // 0x000 ("don't care"), so every valid frame on the bus passes through.
    mcp2515.setBitrate(CAN_500KBPS, MCP_8MHZ);
    mcp2515.setNormalMode();

    Serial.println("can_discovery ready.");
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
    struct can_frame frame;
    while (mcp2515.readMessage(&frame) == MCP2515::ERROR_OK) {
        upsert(frame.can_id, frame.can_dlc, frame.data);
    }
    unsigned long now = millis();
    if (now - last_dump >= DUMP_INTERVAL_MS) {
        last_dump = now;
        dump_table();
    }
}
