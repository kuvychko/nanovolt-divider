#include "sdstore.h"

#include <Arduino.h>
#include <SD.h>
#include <math.h>

#include "bus.h"
#include "calibration.h"
#include "instrument.h"
#include "tmp275.h"

namespace sdstore {

namespace {

bool g_logging = false;
bool g_last_ok = false;
char g_path[24] = "";
uint32_t g_interval_s = 10;
uint32_t g_last_row = 0;

bool ensureDir() { return SD.exists(DIR) || SD.mkdir(DIR); }

void row(Print &out, const char *event, const char *note) {
  const instrument::State &s = instrument::state();
  const float t = tmp275::celsius();
  out.printf("%lu,%s,%s,%s,%s,", (unsigned long)millis(), event, instrument::rangeName(s.range),
             s.polarity == instrument::POL_INV ? "INV" : "NORM",
             !s.known ? "UNKNOWN" : s.inject ? "INJECT" : "ISOLATE");
  if (isnan(t)) out.print(',');
  else out.printf("%.4f,", t);
  const double k = cal::factor(s.range, t);
  if (isnan(k)) out.print(',');
  else out.printf("%.10e,", k);
  // Notes are free text from the host; keep the CSV intact.
  for (const char *p = note; *p; p++) out.print(*p == ',' || *p == '\n' ? ' ' : *p);
  out.print('\n');
}

}  // namespace

bool info(Print &out) {
  bus::SdSession sd;
  g_last_ok = sd.ok();
  if (!sd.ok()) {
    out.print("NO CARD");
    return false;
  }
  static const char *types[] = {"NONE", "MMC", "SD", "SDHC", "UNKNOWN"};
  const uint8_t t = SD.cardType();
  out.printf("%s,%llu MB,%llu MB used", types[t < 4 ? t : 4], SD.cardSize() >> 20,
             SD.usedBytes() >> 20);
  return true;
}

bool exportCal() {
  bus::SdSession sd;
  g_last_ok = false;
  if (!sd.ok() || !ensureDir()) return false;
  File f = SD.open(CAL_FILE, FILE_WRITE);
  if (!f) return false;
  cal::write(f);
  f.close();
  return g_last_ok = true;
}

bool importCal() {
  bus::SdSession sd;
  g_last_ok = false;
  if (!sd.ok()) return false;
  File f = SD.open(CAL_FILE, FILE_READ);
  if (!f) return false;
  bool ok = true;
  while (f.available()) {
    String line = f.readStringUntil('\n');
    ok &= cal::parseLine(line.c_str());
  }
  f.close();
  g_last_ok = true;
  return ok;
}

bool logStart() {
  logStop();
  bus::SdSession sd;
  g_last_ok = false;
  if (!sd.ok() || !ensureDir()) return false;
  for (int n = 1; n < 10000; n++) {
    snprintf(g_path, sizeof(g_path), "%s/log_%04d.csv", DIR, n);
    if (SD.exists(g_path)) continue;
    File f = SD.open(g_path, FILE_WRITE);
    if (!f) return false;
    f.print("ms,event,range,polarity,output,temp_C,factor,note\n");
    row(f, "LOG_START", "");
    f.close();
    g_logging = g_last_ok = true;
    g_last_row = millis();
    return true;
  }
  g_path[0] = '\0';
  return false;
}

void logStop() {
  if (g_logging) logEvent("LOG_STOP");
  g_logging = false;
}

bool logging() { return g_logging; }
const char *logPath() { return g_path; }

void logEvent(const char *event, const char *note) {
  if (!g_logging) return;
  bus::SdSession sd;
  File f;
  if (sd.ok()) f = SD.open(g_path, FILE_APPEND);
  g_last_ok = bool(f);
  if (!f) {
    g_logging = false;  // card gone: stop rather than retrying on every event
    return;
  }
  row(f, event, note);
  f.close();
  g_last_row = millis();
}

void setLogInterval(uint32_t seconds) { g_interval_s = seconds; }
uint32_t logInterval() { return g_interval_s; }

void poll() {
  if (g_logging && g_interval_s && millis() - g_last_row >= g_interval_s * 1000) logEvent("TEMP");
}

bool lastOk() { return g_last_ok; }

}  // namespace sdstore
