#include "gps_task.h"
#include "can_task.h"

static const int GPS_RX_PIN = 1;   // ESP32 RX <- GPS TX
static const int GPS_TX_PIN = 2;   // ESP32 TX -> GPS RX
static const uint32_t GPS_BAUD = 9600;
static const float KNOTS_TO_MPH = 1.15078f;

static HardwareSerial GpsSerial(1);   // UART1 -- UART0 is tied up by the USB/CDC console

static portMUX_TYPE gpsMux = portMUX_INITIALIZER_UNLOCKED;
static GpsFix g_fix;

GpsFix GpsTask_GetFix() {
    GpsFix copy;
    portENTER_CRITICAL(&gpsMux);
    copy = g_fix;
    portEXIT_CRITICAL(&gpsMux);
    return copy;
}

// NMEA sentences are comma-separated; this pulls out field `idx` (0 = the
// "$GNRMC" header itself). Fine for every field we read here even with the
// trailing "*checksum" still attached, since none of them are the last field.
static String nmeaField(const String& line, int idx) {
    int start = 0;
    int field = 0;
    while (field < idx) {
        int comma = line.indexOf(',', start);
        if (comma < 0) return "";
        start = comma + 1;
        field++;
    }
    int end = line.indexOf(',', start);
    if (end < 0) end = line.length();
    return line.substring(start, end);
}

// "ddmm.mmmm" (lat) or "dddmm.mmmm" (lon) -> unsigned decimal degrees.
// Sign (N/S, E/W) is applied by the caller.
static double nmeaToDecimalDegrees(const String& raw, bool isLon) {
    if (raw.length() == 0) return 0;
    int degDigits = isLon ? 3 : 2;
    double deg = raw.substring(0, degDigits).toDouble();
    double minutes = raw.substring(degDigits).toDouble();
    return deg + minutes / 60.0;
}

static bool checksumOk(const String& line) {
    int star = line.lastIndexOf('*');
    if (star < 1 || line.charAt(0) != '$' || star + 2 >= (int)line.length()) return false;
    uint8_t sum = 0;
    for (int i = 1; i < star; i++) sum ^= (uint8_t)line.charAt(i);
    uint8_t expected = (uint8_t)strtol(line.substring(star + 1, star + 3).c_str(), nullptr, 16);
    return sum == expected;
}

// $G?RMC,hhmmss.ss,A,ddmm.mmmm,N,dddmm.mmmm,W,speed_kt,course,ddmmyy,...*CS
// The talker ID varies (GN/GP/GL/...) depending on which constellations the
// fix is using, so the caller matches on the trailing "RMC" rather than a
// fixed 5-character header.
static void parseRMC(const String& line) {
    String status = nmeaField(line, 2);
    if (status != "A") {
        portENTER_CRITICAL(&gpsMux);
        g_fix.valid = false;
        portEXIT_CRITICAL(&gpsMux);
        return;
    }

    String timeStr = nmeaField(line, 1);
    String latStr = nmeaField(line, 3);
    String nsStr = nmeaField(line, 4);
    String lonStr = nmeaField(line, 5);
    String ewStr = nmeaField(line, 6);
    String speedStr = nmeaField(line, 7);
    String dateStr = nmeaField(line, 9);

    if (timeStr.length() < 6 || dateStr.length() < 6) return;   // malformed -- skip rather than log garbage

    double lat = nmeaToDecimalDegrees(latStr, false);
    if (nsStr == "S") lat = -lat;
    double lon = nmeaToDecimalDegrees(lonStr, true);
    if (ewStr == "W") lon = -lon;

    portENTER_CRITICAL(&gpsMux);
    g_fix.valid = true;
    g_fix.lat = lat;
    g_fix.lon = lon;
    g_fix.speed_mph = speedStr.toFloat() * KNOTS_TO_MPH;
    g_fix.hour   = timeStr.substring(0, 2).toInt();
    g_fix.minute = timeStr.substring(2, 4).toInt();
    g_fix.second = timeStr.substring(4, 6).toInt();
    g_fix.day   = dateStr.substring(0, 2).toInt();
    g_fix.month = dateStr.substring(2, 4).toInt();
    g_fix.year  = 2000 + dateStr.substring(4, 6).toInt();   // NMEA only gives a 2-digit year
    g_fix.updates++;
    portEXIT_CRITICAL(&gpsMux);

    // First valid fix of the boot sets the board's wall clock, same as a
    // browser loading the web UI would -- except this needs no client
    // connected at all. CANTask_SetWallClock() itself is a no-op once
    // something has already set it, so calling it on every fix is harmless.
    CANTask_SetWallClock(g_fix.year, g_fix.month, g_fix.day, g_fix.hour, g_fix.minute, g_fix.second);
}

static void gpsTaskLoop(void* pvParameters) {
    String line;
    line.reserve(96);

    while (true) {
        while (GpsSerial.available()) {
            char c = (char)GpsSerial.read();
            if (c == '\n') {
                line.trim();
                if (line.length() > 6 && line.charAt(0) == '$' &&
                    line.substring(3, 6) == "RMC" && checksumOk(line)) {
                    parseRMC(line);
                }
                line = "";
            } else if (c != '\r') {
                if (line.length() < 90) line += c;   // drop absurdly long garbage instead of growing forever
            }
        }
        vTaskDelay(1);
    }
}

void GpsTask_Init() {
    GpsSerial.begin(GPS_BAUD, SERIAL_8N1, GPS_RX_PIN, GPS_TX_PIN);
    xTaskCreatePinnedToCore(gpsTaskLoop, "GpsTask", 4096, NULL, 1, NULL, 0);
}
