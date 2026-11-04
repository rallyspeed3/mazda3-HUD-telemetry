#pragma once
#include <Arduino.h>

// Snapshot of the latest decoded values -- read by the web server to
// answer /api/live, written continuously by the CAN task on core 0.
struct Telemetry {
    uint32_t rpm = 0;
    float throttle = 0;       // %
    uint32_t brake = 0;       // raw units, same as the original toolkit
    float speed = 0;          // mph
    float steering_deg = 0;
    int gear = 0;              // -1 = reverse, 0 = neutral, 1-6 = gear
    uint8_t gear_raw = 0x01;
    bool reverse = false;
    bool handbrake = false;
    float wheel_fl = 0, wheel_fr = 0, wheel_rl = 0, wheel_rr = 0;
    uint32_t updates = 0;      // total decoded frames seen, for a simple "is data flowing" check
};

// Call once from setup(). Mounts the log filesystem, starts the TWAI
// (CAN) controller, and launches the background task that drains CAN
// frames and (when recording) appends CSV rows -- all pinned to core 0
// so it never competes with the web server for CPU time.
void CANTask_Init();

// Thread-safe snapshot of the latest decoded values.
Telemetry CANTask_GetTelemetry();

// Recording control. Returns the log filename on start ("" on failure),
// or an empty/garbage string from Stop (check CANTask_IsRecording() if
// you need to know whether it actually did anything).
String CANTask_StartRecording();
void CANTask_StopRecording();
bool CANTask_IsRecording();
String CANTask_CurrentLogName();   // "" when not recording
uint32_t CANTask_CurrentLogRows();
