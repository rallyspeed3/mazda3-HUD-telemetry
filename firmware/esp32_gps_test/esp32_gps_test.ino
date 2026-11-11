// esp32_gps_test.ino -- bring-up sketch for a Beitian GN-880/BN-880 GPS
// module wired directly to this board's free P1 header pins. Does nothing
// but relay raw NMEA sentences from the GPS straight out over USB serial,
// so you can confirm the wiring and baud rate are right before building
// any parsing logic on top of it.
//
// Wiring (confirmed free on this board's P1 header via its own silkscreen
// -- GPIO15/GPIO16 are NOT available here, they're hard-wired to the
// onboard CAN transceiver):
//   GN-880 TX -> ESP32 GPIO1  (ESP32 RX)
//   GN-880 RX -> ESP32 GPIO2  (ESP32 TX)
//   GN-880 VCC -> 3V3
//   GN-880 GND -> GND
// Cross TX/RX -- the module's TX feeds the chip's RX and vice versa. Which
// GPIO number is "RX" vs "TX" is just a software assignment (ESP32's pin
// matrix lets any GPIO do either); GPIO1/GPIO2 here is this project's
// chosen convention, not a hardware requirement.
//
// *** IMPORTANT: "USB CDC On Boot" must be set to "Enabled" *** -- same
// native-USB requirement as the other esp32_*.ino sketches in this repo.
//
// BN-880 ships talking NMEA 0183 at 9600 baud by default. If this prints
// nothing, double check TX/RX aren't swapped and that the module has a
// clear view of the sky (first fix can take a minute or two outdoors).

static const int GPS_RX_PIN = 1;   // ESP32 RX <- GPS TX
static const int GPS_TX_PIN = 2;   // ESP32 TX -> GPS RX
static const uint32_t GPS_BAUD = 9600;

HardwareSerial GPS(1);   // UART1 -- UART0 is tied up by the USB/CDC console

void setup() {
    Serial.begin(115200);
    delay(300);
    Serial.println("esp32_gps_test ready -- relaying raw NMEA from the GPS below.");

    GPS.begin(GPS_BAUD, SERIAL_8N1, GPS_RX_PIN, GPS_TX_PIN);
}

void loop() {
    while (GPS.available()) {
        Serial.write(GPS.read());
    }
}
