#include "bus.h"

#include <Arduino.h>
#include <SD.h>
#include <SPI.h>
#include <Wire.h>

#include "pins.h"

namespace bus {

namespace {

constexpr uint32_t I2C_HZ = 100000;
constexpr uint32_t SD_HZ = 4000000;

// While the bus is in I2C mode, hold the card deselected and its command line idle, so the SCL
// clock is never mistaken for card traffic.
void parkSdPins() {
  pinMode(pins::SD_CS, OUTPUT);
  digitalWrite(pins::SD_CS, HIGH);
  pinMode(pins::SD_MOSI, OUTPUT);
  digitalWrite(pins::SD_MOSI, HIGH);
}

void startI2C() {
  parkSdPins();
  Wire.begin(pins::I2C_SDA, pins::I2C_SCL, I2C_HZ);
  Wire.setTimeOut(20);
}

}  // namespace

void begin() { startI2C(); }

bool write8(uint8_t addr, uint8_t reg, uint8_t value) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.write(value);
  return Wire.endTransmission() == 0;
}

bool write16(uint8_t addr, uint8_t reg, uint16_t value) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.write(uint8_t(value >> 8));
  Wire.write(uint8_t(value & 0xFF));
  return Wire.endTransmission() == 0;
}

static bool readN(uint8_t addr, uint8_t reg, uint8_t *buf, size_t n) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(addr, uint8_t(n)) != n) return false;
  for (size_t i = 0; i < n; i++) buf[i] = Wire.read();
  return true;
}

bool read8(uint8_t addr, uint8_t reg, uint8_t &value) { return readN(addr, reg, &value, 1); }

bool read16(uint8_t addr, uint8_t reg, uint16_t &value) {
  uint8_t b[2];
  if (!readN(addr, reg, b, 2)) return false;
  value = uint16_t(b[0]) << 8 | b[1];
  return true;
}

bool probe(uint8_t addr) {
  Wire.beginTransmission(addr);
  return Wire.endTransmission() == 0;
}

size_t scan(uint8_t *found, size_t max) {
  size_t n = 0;
  for (uint8_t a = 0x08; a < 0x78; a++) {
    if (probe(a) && n < max) found[n++] = a;
  }
  return n;
}

void probePullups(bool &io18High, bool &io27High) {
  Wire.end();
  pinMode(pins::I2C_SCL, INPUT_PULLDOWN);
  pinMode(pins::I2C_SDA, INPUT_PULLDOWN);
  delay(5);
  io18High = digitalRead(pins::I2C_SCL);
  io27High = digitalRead(pins::I2C_SDA);
  pinMode(pins::I2C_SCL, INPUT);
  pinMode(pins::I2C_SDA, INPUT);
  startI2C();
}

SdSession::SdSession() : ok_(false) {
  Wire.end();
  SPI.begin(pins::SD_SCK, pins::SD_MISO, pins::SD_MOSI, pins::SD_CS);
  ok_ = SD.begin(pins::SD_CS, SPI, SD_HZ);
}

SdSession::~SdSession() {
  if (ok_) SD.end();
  SPI.end();
  startI2C();
}

}  // namespace bus
