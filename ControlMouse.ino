#include <Mouse.h>

void setup() {
  Mouse.begin();

  Serial.begin(1000000);

  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LOW);
}

void loop() {
  while (Serial.available() >= 2) {
    int dxRaw = Serial.read();
    int dyRaw = Serial.read();
    int8_t dx = (int8_t)(uint8_t)dxRaw;
    int8_t dy = (int8_t)(uint8_t)dyRaw;

    Mouse.move(dx, dy, 0);

    digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
  }
}
