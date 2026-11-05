#include "can_task.h"
#include "driver/twai.h"
#include "FFat.h"

static const gpio_num_t CAN_TX_PIN = GPIO_NUM_15;
static const gpio_num_t CAN_RX_PIN = GPIO_NUM_16;

// Same 6 IDs as the plain esp32_can_live.ino -- see docs/FINDINGS.md.
static const uint32_t TARGET_IDS[] = {0x201, 0x20F, 0x4B0, 0x231, 0x433, 0x082};
static const int NUM_IDS = sizeof(TARGET_IDS) / sizeof(TARGET_IDS[0]);
static const float KMH_TO_MPH = 0.621371f;
static const float LOG_RATE_HZ = 20.0f;   // matches tools/record_drive.py's default --rate

static bool is_target_id(uint32_t id) {
    for (int i = 0; i < NUM_IDS; i++) {
        if (TARGET_IDS[i] == id) return true;
    }
    return false;
}

// gear_raw -> gear lookup, same table as the original toolkit.
static int gear_from_raw(uint8_t raw, bool* known) {
    *known = true;
    switch (raw) {
        case 0x00: case 0x01: return 0;
        case 0x11: return 1;
        case 0x20: return 2;
        case 0x30: return 3;
        case 0x40: return 4;
        case 0x50: return 5;
        case 0x60: return 6;
        default: *known = false; return 0;
    }
}

// ---- shared state (written by the CAN task, read by the web server) ----
static portMUX_TYPE telemetryMux = portMUX_INITIALIZER_UNLOCKED;
static Telemetry g_telemetry;

static volatile bool g_recording = false;
static File g_logFile;
static String g_logName = "";
static volatile uint32_t g_logRows = 0;
static uint32_t g_nextLogId = 1;

// ---- filename handling ----
static String makeLogName(uint32_t id) {
    char buf[24];
    snprintf(buf, sizeof(buf), "/log_%05u.csv", (unsigned)id);
    return String(buf);
}

static void scanNextLogId() {
    uint32_t maxId = 0;
    File root = FFat.open("/");
    if (!root) return;
    File f = root.openNextFile();
    while (f) {
        String name = f.name();                     // "log_00007.csv" (no leading '/')
        if (name.startsWith("log_") && name.endsWith(".csv")) {
            uint32_t id = (uint32_t)name.substring(4, name.length() - 4).toInt();
            if (id > maxId) maxId = id;
        }
        f = root.openNextFile();
    }
    g_nextLogId = maxId + 1;
}

// ---- recording control (called from the web server task -- core 1) ----
String CANTask_StartRecording() {
    if (g_recording) return g_logName;

    String name = makeLogName(g_nextLogId);
    File f = FFat.open(name, FILE_WRITE);
    if (!f) return "";

    f.print("time,throttle,brake,steering_deg,speed,rpm,gear,gear_raw,"
            "wheel_fl,wheel_fr,wheel_rl,wheel_rr\n");

    g_logFile = f;
    g_logName = name;
    g_logRows = 0;
    g_nextLogId++;
    g_recording = true;
    return name;
}

void CANTask_StopRecording() {
    if (!g_recording) return;
    g_recording = false;
    g_logFile.flush();
    g_logFile.close();
    g_logName = "";
}

bool CANTask_IsRecording() { return g_recording; }
String CANTask_CurrentLogName() { return g_recording ? g_logName : ""; }
uint32_t CANTask_CurrentLogRows() { return g_logRows; }

Telemetry CANTask_GetTelemetry() {
    Telemetry copy;
    portENTER_CRITICAL(&telemetryMux);
    copy = g_telemetry;
    portEXIT_CRITICAL(&telemetryMux);
    return copy;
}

// ---- the task itself ----
static void canTaskLoop(void* pvParameters) {
    int last_gear = 0;
    uint64_t t0_ms = 0;
    uint64_t next_tick_ms = 0;
    const uint32_t period_ms = (uint32_t)(1000.0f / LOG_RATE_HZ);
    bool was_recording = false;

    while (true) {
        twai_message_t msg;
        while (twai_receive(&msg, 0) == ESP_OK) {
            if (!is_target_id(msg.identifier)) continue;
            uint8_t* d = msg.data;

            portENTER_CRITICAL(&telemetryMux);
            switch (msg.identifier) {
                case 0x201:
                    if (msg.data_length_code >= 7) {
                        g_telemetry.rpm = (d[0] << 8) | d[1];
                        g_telemetry.throttle = d[6] / 255.0f * 100.0f;
                    }
                    break;
                case 0x20F:
                    if (msg.data_length_code >= 4) {
                        int32_t rawf = (d[0] << 8) | d[1];
                        g_telemetry.brake = rawf > 30000 ? (rawf - 30000) : 0;
                        int32_t raws = (d[2] << 8) | d[3];
                        g_telemetry.speed = (raws - 10000) / 100.0f * KMH_TO_MPH;
                    }
                    break;
                case 0x082:
                    if (msg.data_length_code >= 4) {
                        int16_t raw = (int16_t)((d[2] << 8) | d[3]);
                        g_telemetry.steering_deg = raw / 10.0f;
                    }
                    break;
                case 0x231:
                    if (msg.data_length_code >= 1) {
                        g_telemetry.gear_raw = d[0];
                        bool known;
                        int g = gear_from_raw(d[0], &known);
                        if (known) {
                            g_telemetry.gear = g;
                            last_gear = g;
                        } else {
                            g_telemetry.gear = last_gear;  // keep last known, same as record_drive.py
                        }
                    }
                    break;
                case 0x433:
                    if (msg.data_length_code >= 4) {
                        g_telemetry.handbrake = d[3] & 0x01;
                        g_telemetry.reverse = d[3] & 0x02;
                    }
                    break;
                case 0x4B0:
                    if (msg.data_length_code >= 8) {
                        g_telemetry.wheel_fl = (((d[0] << 8) | d[1]) - 10000) / 100.0f * KMH_TO_MPH;
                        g_telemetry.wheel_fr = (((d[2] << 8) | d[3]) - 10000) / 100.0f * KMH_TO_MPH;
                        g_telemetry.wheel_rl = (((d[4] << 8) | d[5]) - 10000) / 100.0f * KMH_TO_MPH;
                        g_telemetry.wheel_rr = (((d[6] << 8) | d[7]) - 10000) / 100.0f * KMH_TO_MPH;
                    }
                    break;
            }
            g_telemetry.updates++;
            portEXIT_CRITICAL(&telemetryMux);
        }

        // Started recording just now -- (re)sync the tick clock.
        if (g_recording && !was_recording) {
            t0_ms = millis();
            next_tick_ms = t0_ms;
        }
        was_recording = g_recording;

        if (g_recording && millis() >= next_tick_ms) {
            Telemetry t = CANTask_GetTelemetry();
            int display_gear = t.reverse ? -1 : t.gear;
            float row_time = (next_tick_ms - t0_ms) / 1000.0f;

            char line[200];
            snprintf(line, sizeof(line),
                      "%.3f,%.1f,%u,%.1f,%.1f,%u,%d,0x%02X,%.1f,%.1f,%.1f,%.1f\n",
                      row_time, t.throttle, (unsigned)t.brake, t.steering_deg,
                      t.speed, (unsigned)t.rpm, display_gear, t.gear_raw,
                      t.wheel_fl, t.wheel_fr, t.wheel_rl, t.wheel_rr);
            g_logFile.print(line);
            g_logRows++;
            if (g_logRows % (uint32_t)LOG_RATE_HZ == 0) {
                g_logFile.flush();   // once a second -- bounds data loss on power loss without wearing flash every row
            }
            next_tick_ms += period_ms;
        }

        vTaskDelay(1);  // yield -- keeps the watchdog happy, still effectively a tight poll loop
    }
}

void CANTask_Init() {
    if (!FFat.begin(true)) {   // true = format if mount fails (first boot / corruption)
        Serial.println("ERROR: FFat mount failed even after format attempt");
    }
    scanNextLogId();

    twai_general_config_t g_config =
        TWAI_GENERAL_CONFIG_DEFAULT(CAN_TX_PIN, CAN_RX_PIN, TWAI_MODE_NORMAL);
    twai_timing_config_t t_config = TWAI_TIMING_CONFIG_500KBITS();
    twai_filter_config_t f_config = TWAI_FILTER_CONFIG_ACCEPT_ALL();

    if (twai_driver_install(&g_config, &t_config, &f_config) != ESP_OK) {
        Serial.println("ERROR: twai_driver_install failed");
        return;
    }
    if (twai_start() != ESP_OK) {
        Serial.println("ERROR: twai_start failed");
        return;
    }

    xTaskCreatePinnedToCore(canTaskLoop, "CANTask", 4096, NULL, 2, NULL, 0);
}
