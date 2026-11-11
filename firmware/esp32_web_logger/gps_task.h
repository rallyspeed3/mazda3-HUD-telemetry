#pragma once
#include <Arduino.h>

// Latest decoded fix from the GN-880/BN-880 GPS module, wired to GPIO1
// (ESP32 RX <- GPS TX) / GPIO2 (ESP32 TX -> GPS RX) -- see
// firmware/esp32_gps_test/esp32_gps_test.ino for the wiring writeup.
struct GpsFix {
    bool valid = false;      // NMEA status field was 'A' (active/valid) on the last RMC sentence
    double lat = 0;          // decimal degrees, +N / -S
    double lon = 0;          // decimal degrees, +E / -W
    float speed_mph = 0;
    int year = 0, month = 0, day = 0, hour = 0, minute = 0, second = 0;   // UTC, from the fix itself
    uint32_t updates = 0;    // total valid RMC sentences decoded, for a simple "is the GPS alive" check
};

// Call once from setup(). Starts a background task (pinned to core 0,
// alongside the CAN task) that reads NMEA sentences from the GPS and keeps
// a running decode of the latest fix. Also feeds the board's wall clock
// (CANTask_SetWallClock()) from the GPS's own UTC time the first time it
// gets a valid fix -- this works even with zero WiFi clients ever
// connecting, unlike the browser-clock-sync fallback.
void GpsTask_Init();

// Thread-safe snapshot of the latest decoded fix.
GpsFix GpsTask_GetFix();
