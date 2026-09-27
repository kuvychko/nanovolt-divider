#include "utc.h"

#include <Arduino.h>
#include <stdio.h>
#include <time.h>

namespace utc {

namespace {
uint32_t g_base = 0;     // unix seconds at g_base_ms
uint32_t g_base_ms = 0;
}  // namespace

void set(uint32_t unixSeconds) {
  g_base = unixSeconds;
  g_base_ms = millis();
}

uint32_t now() { return g_base ? g_base + (millis() - g_base_ms) / 1000 : 0; }

bool valid() { return g_base != 0; }

void format(char *buf, uint32_t unixSeconds) {
  if (!unixSeconds) {
    snprintf(buf, 21, "-");
    return;
  }
  const time_t t = unixSeconds;
  struct tm tm;
  gmtime_r(&t, &tm);
  strftime(buf, 21, "%Y-%m-%dT%H:%M:%SZ", &tm);
}

}  // namespace utc
