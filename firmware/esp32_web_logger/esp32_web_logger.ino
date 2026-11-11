// esp32_web_logger.ino -- CAN reading + on-device CSV logging + a web UI
// for viewing live telemetry and managing logs (rename/delete/download),
// all served from the ESP32-S3 itself over its own WiFi access point.
// No laptop, no USB tether needed once this is flashed -- just power
// (USB-C or the board's 7-36V terminal) and a phone/laptop to connect to
// its WiFi.
//
// *** IMPORTANT: "USB CDC On Boot" must be set to "Enabled" *** (same
// native-USB gotcha as esp32_can_live.ino -- see that sketch's header
// comment, or docs/HARDWARE_SETUP-equivalent notes in the README, for
// why.)
//
// How to use it:
//   1. Flash this (Partition Scheme: "16M Flash (3MB APP/9.9MB FATFS)").
//   2. On your phone/laptop, join the WiFi network named below (AP_SSID).
//   3. Browse to http://192.168.4.1/
//   4. Hit "Start Recording" before you drive, "Stop Recording" when
//      you're done. Rename/download/delete logs from the same page.
//
// Logs are plain CSV in the same format firmware/can_live/can_live.ino +
// tools/record_drive.py produce (time,throttle,brake,steering_deg,speed,
// rpm,gear,gear_raw) -- download one and run it straight through
// hud_overlay/render_overlay.py, unmodified.
#include <WiFi.h>
#include <WebServer.h>
#include <time.h>
#include "FFat.h"
#include "can_task.h"
#include "gps_task.h"
#include "web_ui.h"

// Change these if you want -- WPA2 passwords need to be 8+ characters.
static const char* AP_SSID = "Mazda3-Telemetry";
static const char* AP_PASS = "mazda3can";

WebServer server(80);

// ---- small helpers ----

// Keeps filenames inside FATFS sane: no path traversal, always ends in
// .csv, always has the leading '/' FFat paths expect. Returns "" if the
// input can't be made into something safe.
static String sanitizeLogName(String name) {
    name.trim();
    if (!name.startsWith("/")) name = "/" + name;
    if (name.indexOf("..") >= 0) return "";
    // Reject anything that isn't "/something.csv" with no extra slashes.
    if (name.lastIndexOf('/') != 0) return "";
    if (!name.endsWith(".csv")) name += ".csv";
    if (name.length() <= 5) return "";   // just "/.csv" or shorter
    return name;
}

static void sendJsonError(const char* msg) {
    server.send(400, "application/json", String("{\"ok\":false,\"error\":\"") + msg + "\"}");
}

// ---- route handlers ----

void handleRoot() {
    server.send_P(200, "text/html", INDEX_HTML);
}

void handleLive() {
    Telemetry t = CANTask_GetTelemetry();
    GpsFix gps = GpsTask_GetFix();
    bool recording = CANTask_IsRecording();
    String logName = CANTask_CurrentLogName();
    logName.replace("/", "");

    char buf[520];
    snprintf(buf, sizeof(buf),
        "{\"recording\":%s,\"log_name\":\"%s\",\"log_rows\":%u,"
        "\"rpm\":%u,\"throttle\":%.1f,\"brake\":%u,\"speed\":%.1f,"
        "\"steering\":%.1f,\"gear\":%d,\"reverse\":%s,\"handbrake\":%s,"
        "\"wheel_fl\":%.1f,\"wheel_fr\":%.1f,\"wheel_rl\":%.1f,\"wheel_rr\":%.1f,"
        "\"gps_valid\":%s,\"gps_lat\":%.6f,\"gps_lon\":%.6f,\"gps_speed\":%.1f,"
        "\"updates\":%u}",
        recording ? "true" : "false", logName.c_str(), (unsigned)CANTask_CurrentLogRows(),
        (unsigned)t.rpm, t.throttle, (unsigned)t.brake, t.speed,
        t.steering_deg, t.gear, t.reverse ? "true" : "false", t.handbrake ? "true" : "false",
        t.wheel_fl, t.wheel_fr, t.wheel_rl, t.wheel_rr,
        gps.valid ? "true" : "false", gps.lat, gps.lon, gps.speed_mph,
        (unsigned)t.updates);

    server.sendHeader("Cache-Control", "no-store");
    server.send(200, "application/json", buf);
}

void handleLogsList() {
    String json = "[";
    File root = FFat.open("/");
    File f = root.openNextFile();
    bool first = true;
    while (f) {
        String name = f.name();
        if (!f.isDirectory() && name.endsWith(".csv")) {
            if (!first) json += ",";
            first = false;
            json += "{\"name\":\"" + name + "\",\"size\":" + String(f.size()) + "}";
        }
        f = root.openNextFile();
    }
    json += "]";
    server.sendHeader("Cache-Control", "no-store");
    server.send(200, "application/json", json);
}

void handleRecordStart() {
    String name = CANTask_StartRecording();
    if (name == "") {
        sendJsonError("couldn't open a new log file (storage full?)");
        return;
    }
    name.replace("/", "");
    server.send(200, "application/json", "{\"ok\":true,\"name\":\"" + name + "\"}");
}

void handleRecordStop() {
    CANTask_StopRecording();
    server.send(200, "application/json", "{\"ok\":true}");
}

// Called by the web page on load, with the browser's own clock (as epoch
// milliseconds -- always UTC, unlike Y/M/D/h/m/s fields which would be in
// whatever timezone the phone/laptop is set to). First caller for this boot
// wins -- see CANTask_SetWallClock()'s comment in can_task.h. After this
// succeeds, new logs get real dated filenames instead of "log_00007.csv".
void handleSetTime() {
    if (!server.hasArg("epoch_ms")) {
        sendJsonError("missing epoch_ms");
        return;
    }
    time_t epochSec = (time_t)(server.arg("epoch_ms").toDouble() / 1000.0);
    struct tm t;
    gmtime_r(&epochSec, &t);
    bool applied = CANTask_SetWallClock(
        t.tm_year + 1900, t.tm_mon + 1, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec);
    server.send(200, "application/json",
                String("{\"ok\":true,\"applied\":") + (applied ? "true" : "false") + "}");
}

void handleLogsRename() {
    if (!server.hasArg("name") || !server.hasArg("new")) {
        sendJsonError("missing name or new");
        return;
    }
    String oldName = sanitizeLogName(server.arg("name"));
    String newName = sanitizeLogName(server.arg("new"));
    if (oldName == "" || newName == "") {
        sendJsonError("invalid filename");
        return;
    }
    if (CANTask_IsRecording() && oldName == CANTask_CurrentLogName()) {
        sendJsonError("can't rename the log that's currently recording -- stop first");
        return;
    }
    if (!FFat.exists(oldName)) {
        sendJsonError("file not found");
        return;
    }
    if (FFat.exists(newName)) {
        sendJsonError("a file with that name already exists");
        return;
    }
    if (!FFat.rename(oldName, newName)) {
        sendJsonError("rename failed");
        return;
    }
    server.send(200, "application/json", "{\"ok\":true}");
}

void handleLogsDelete() {
    if (!server.hasArg("name")) {
        sendJsonError("missing name");
        return;
    }
    String name = sanitizeLogName(server.arg("name"));
    if (name == "") {
        sendJsonError("invalid filename");
        return;
    }
    if (CANTask_IsRecording() && name == CANTask_CurrentLogName()) {
        sendJsonError("can't delete the log that's currently recording -- stop first");
        return;
    }
    if (!FFat.exists(name)) {
        sendJsonError("file not found");
        return;
    }
    if (!FFat.remove(name)) {
        sendJsonError("delete failed");
        return;
    }
    server.send(200, "application/json", "{\"ok\":true}");
}

void handleLogsDownload() {
    if (!server.hasArg("name")) {
        server.send(400, "text/plain", "missing name");
        return;
    }
    String name = sanitizeLogName(server.arg("name"));
    if (name == "" || !FFat.exists(name)) {
        server.send(404, "text/plain", "not found");
        return;
    }
    File f = FFat.open(name, FILE_READ);
    String downloadName = name.substring(1);  // strip leading '/'
    server.sendHeader("Content-Disposition", "attachment; filename=\"" + downloadName + "\"");
    server.streamFile(f, "text/csv");
    f.close();
}

void handleNotFound() {
    server.send(404, "text/plain", "not found");
}

void setup() {
    Serial.begin(115200);
    delay(300);

    CANTask_Init();
    GpsTask_Init();

    WiFi.mode(WIFI_AP);
    WiFi.setSleep(false);   // modem sleep saves power but adds latency/drops that can look like a dead AP to clients
    if (!WiFi.softAP(AP_SSID, AP_PASS)) {
        Serial.println("ERROR: WiFi.softAP() failed -- the AP won't be visible. "
                        "Try a power cycle (not just the reset button).");
    }
    Serial.print("AP started. Connect to WiFi \"");
    Serial.print(AP_SSID);
    Serial.print("\", then open http://");
    Serial.println(WiFi.softAPIP());

    server.on("/", handleRoot);
    server.on("/api/live", handleLive);
    server.on("/api/logs", handleLogsList);
    server.on("/api/record/start", HTTP_POST, handleRecordStart);
    server.on("/api/record/stop", HTTP_POST, handleRecordStop);
    server.on("/api/set_time", HTTP_POST, handleSetTime);
    server.on("/api/logs/rename", HTTP_POST, handleLogsRename);
    server.on("/api/logs/delete", HTTP_POST, handleLogsDelete);
    server.on("/api/logs/download", HTTP_GET, handleLogsDownload);
    server.onNotFound(handleNotFound);
    server.begin();

    Serial.println("Web server ready.");
}

void loop() {
    server.handleClient();
}
