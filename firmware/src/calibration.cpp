#include "calibration.h"

#include <Preferences.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

namespace cal {

namespace {

constexpr double NOMINAL[instrument::RANGE_COUNT] = {0, 1.0 / (100e3 + 1), 1.0 / (1e6 + 1),
                                                      1.0 / (10e6 + 1)};
constexpr double T0_DEFAULT = 25.0;
constexpr const char *NVS_NS = "nvdcal";

RangeCal g_cal[instrument::RANGE_COUNT];
bool g_dirty = false;

void setDefault(uint8_t i) {
  g_cal[i].nominal = NOMINAL[i];
  g_cal[i].k0 = NOMINAL[i];
  g_cal[i].t0 = T0_DEFAULT;
  g_cal[i].alpha = 0;
  strcpy(g_cal[i].date, "nominal");
}

void key(char *buf, const char *field, uint8_t i) { snprintf(buf, 12, "%s%u", field, i); }

}  // namespace

void begin() {
  Preferences p;
  p.begin(NVS_NS, false);  // read-write: creates the namespace on first boot instead of logging NOT_FOUND
  for (uint8_t i = 1; i < instrument::RANGE_COUNT; i++) {
    setDefault(i);
    char k[12];
    key(k, "k0_", i);
    g_cal[i].k0 = p.getDouble(k, g_cal[i].k0);
    key(k, "t0_", i);
    g_cal[i].t0 = p.getDouble(k, g_cal[i].t0);
    key(k, "a_", i);
    g_cal[i].alpha = p.getDouble(k, g_cal[i].alpha);
    key(k, "d_", i);
    if (p.isKey(k)) p.getString(k, g_cal[i].date, sizeof(g_cal[i].date));
  }
  p.end();
  g_dirty = false;
}

RangeCal &get(instrument::Range r) { return g_cal[r < instrument::RANGE_COUNT ? r : 1]; }

bool save() {
  Preferences p;
  if (!p.begin(NVS_NS, false)) return false;
  bool ok = true;
  for (uint8_t i = 1; i < instrument::RANGE_COUNT; i++) {
    char k[12];
    key(k, "k0_", i);
    ok &= p.putDouble(k, g_cal[i].k0) > 0;
    key(k, "t0_", i);
    ok &= p.putDouble(k, g_cal[i].t0) > 0;
    key(k, "a_", i);
    ok &= p.putDouble(k, g_cal[i].alpha) > 0;
    key(k, "d_", i);
    ok &= p.putString(k, g_cal[i].date) == strlen(g_cal[i].date);
  }
  p.end();
  if (ok) g_dirty = false;
  return ok;
}

void resetToNominal() {
  for (uint8_t i = 1; i < instrument::RANGE_COUNT; i++) setDefault(i);
  g_dirty = true;
}

bool dirty() { return g_dirty; }
void markDirty() { g_dirty = true; }

double factor(instrument::Range r, float t) {
  if (r == instrument::RANGE_NONE || r >= instrument::RANGE_COUNT) return NAN;
  const RangeCal &c = g_cal[r];
  if (c.alpha == 0 || isnan(t)) return c.k0;
  return c.k0 * (1 + c.alpha * (t - c.t0));
}

void write(Print &out) {
  out.println("# nanovolt-divider calibration: range k0 t0_C alpha_perC date");
  for (uint8_t i = 1; i < instrument::RANGE_COUNT; i++) {
    const RangeCal &c = g_cal[i];
    out.printf("%s %.12e %.4f %.6e %s\n", instrument::rangeName(instrument::Range(i)), c.k0, c.t0,
               c.alpha, c.date);
  }
}

bool parseLine(const char *line) {
  while (*line == ' ' || *line == '\t') line++;
  if (*line == '#' || *line == '\0' || *line == '\r' || *line == '\n') return true;
  char name[8], date[32] = "";
  double k0, t0, alpha;
  if (sscanf(line, "%7s %lf %lf %lf %31[^\r\n]", name, &k0, &t0, &alpha, date) < 4) return false;
  for (uint8_t i = 1; i < instrument::RANGE_COUNT; i++) {
    if (strcasecmp(name, instrument::rangeName(instrument::Range(i))) != 0) continue;
    // Reject anything more than 10 % from nominal: a factor that far out is a typo, not a cal.
    if (!(fabs(k0 / NOMINAL[i] - 1) < 0.1)) return false;
    g_cal[i].k0 = k0;
    g_cal[i].t0 = t0;
    g_cal[i].alpha = alpha;
    strlcpy(g_cal[i].date, date, sizeof(g_cal[i].date));
    g_dirty = true;
    return true;
  }
  return false;
}

}  // namespace cal
