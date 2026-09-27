// Wall-clock UTC, set by the host (SYST:TIME) and kept in RAM only. The module has no RTC, so
// until the host sets it the time is unknown and now() returns 0 - never a guessed date.
#pragma once
#include <stdint.h>

namespace utc {

void set(uint32_t unixSeconds);
uint32_t now();  // seconds since 1970-01-01 UTC, or 0 if never set since boot
bool valid();

// ISO 8601 "2026-09-26T16:49:21Z", or "-" when unset. buf needs 21 bytes.
void format(char *buf, uint32_t unixSeconds);

}  // namespace utc
