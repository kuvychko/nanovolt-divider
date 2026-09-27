#include "calibration.h"

#include <Preferences.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

namespace cal {

namespace {

constexpr double NOMINAL[instrument::RANGE_COUNT] = {0, 1.0 / (100e3 + 1), 1.0 / (1e6 + 1),
                                                      1.0 / (10e6 + 1)};
// Uncertainty of a nominal record, from the part tolerances: the 1 ohm is 1 %, the high legs
// 0.1 % / 0.1 % / 1 %. Their tempcos are unknown until measured and are not included.
constexpr double NOMINAL_U_PPM[instrument::RANGE_COUNT] = {0, 10050, 10050, 14142};
constexpr double T0_DEFAULT = 25.0;
constexpr double TMIN_DEFAULT = -40, TMAX_DEFAULT = 125;  // the TMP275's range

// v2 store: one blob per range. The v1 namespace ("nvdcal") only ever held nominal values and is
// ignored.
constexpr const char *NVS_NS = "nvdcal2";
constexpr uint16_t BLOB_VERSION = 2;

struct Blob {
  uint16_t version;
  double k0, t0, alpha, beta, u_k0_ppm, u_alpha_ppm, tmin, tmax;
  char date[32];
  char source[64];
};

RangeCal g_cal[instrument::RANGE_COUNT];
bool g_dirty = false;

void setDefault(uint8_t i) {
  RangeCal &c = g_cal[i];
  c.nominal = NOMINAL[i];
  c.k0 = NOMINAL[i];
  c.t0 = T0_DEFAULT;
  c.alpha = c.beta = 0;
  c.u_k0_ppm = NOMINAL_U_PPM[i];
  c.u_alpha_ppm = 0;
  c.tmin = TMIN_DEFAULT;
  c.tmax = TMAX_DEFAULT;
  strcpy(c.date, "-");
  strcpy(c.source, "nominal");
}

void key(char *buf, uint8_t i) { snprintf(buf, 8, "r%u", i); }

// ---- text parsing: key=value tokens, values optionally double-quoted

bool nextToken(const char *&p, char *key, size_t keyLen, char *val, size_t valLen) {
  while (*p == ' ' || *p == '\t') p++;
  if (!*p || *p == '\r' || *p == '\n') return false;
  size_t n = 0;
  while (*p && *p != '=' && *p != ' ') {
    if (n + 1 < keyLen) key[n++] = *p;
    p++;
  }
  key[n] = '\0';
  if (*p != '=') return false;
  p++;
  n = 0;
  if (*p == '"') {
    p++;
    while (*p && *p != '"') {
      if (n + 1 < valLen) val[n++] = *p;
      p++;
    }
    if (*p == '"') p++;
  } else {
    while (*p && *p != ' ' && *p != '\t' && *p != '\r' && *p != '\n') {
      if (n + 1 < valLen) val[n++] = *p;
      p++;
    }
  }
  val[n] = '\0';
  return true;
}

bool toDouble(const char *s, double &v) {
  char *end;
  v = strtod(s, &end);
  return end != s && *end == '\0' && isfinite(v);
}

}  // namespace

void begin() {
  Preferences p;
  p.begin(NVS_NS, false);  // read-write: creates the namespace on first boot instead of logging NOT_FOUND
  for (uint8_t i = 1; i < instrument::RANGE_COUNT; i++) {
    setDefault(i);
    char k[8];
    key(k, i);
    Blob b;
    if (!p.isKey(k) || p.getBytesLength(k) != sizeof(Blob) || p.getBytes(k, &b, sizeof(b)) != sizeof(b) ||
        b.version != BLOB_VERSION)
      continue;
    RangeCal &c = g_cal[i];
    c.k0 = b.k0;
    c.t0 = b.t0;
    c.alpha = b.alpha;
    c.beta = b.beta;
    c.u_k0_ppm = b.u_k0_ppm;
    c.u_alpha_ppm = b.u_alpha_ppm;
    c.tmin = b.tmin;
    c.tmax = b.tmax;
    strlcpy(c.date, b.date, sizeof(c.date));
    strlcpy(c.source, b.source, sizeof(c.source));
  }
  p.end();
  g_dirty = false;
}

RangeCal &get(instrument::Range r) { return g_cal[r < instrument::RANGE_COUNT && r ? r : 1]; }

bool save() {
  Preferences p;
  if (!p.begin(NVS_NS, false)) return false;
  bool ok = true;
  for (uint8_t i = 1; i < instrument::RANGE_COUNT; i++) {
    const RangeCal &c = g_cal[i];
    Blob b = {};
    b.version = BLOB_VERSION;
    b.k0 = c.k0;
    b.t0 = c.t0;
    b.alpha = c.alpha;
    b.beta = c.beta;
    b.u_k0_ppm = c.u_k0_ppm;
    b.u_alpha_ppm = c.u_alpha_ppm;
    b.tmin = c.tmin;
    b.tmax = c.tmax;
    strlcpy(b.date, c.date, sizeof(b.date));
    strlcpy(b.source, c.source, sizeof(b.source));
    char k[8];
    key(k, i);
    ok &= p.putBytes(k, &b, sizeof(b)) == sizeof(b);
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

Eval evaluate(instrument::Range r, float t) {
  if (r == instrument::RANGE_NONE || r >= instrument::RANGE_COUNT) return {NAN, NAN, false};
  const RangeCal &c = g_cal[r];
  if (isnan(t)) return {c.k0, c.u_k0_ppm, false};
  const double dt = t - c.t0;
  const double k = c.k0 * (1 + c.alpha * dt + c.beta * dt * dt);
  const double ua = c.u_alpha_ppm * dt;
  return {k, sqrt(c.u_k0_ppm * c.u_k0_ppm + ua * ua), t >= c.tmin && t <= c.tmax};
}

double factor(instrument::Range r, float t) { return evaluate(r, t).k; }

bool plausible(instrument::Range r, double k0) {
  return r != instrument::RANGE_NONE && r < instrument::RANGE_COUNT && fabs(k0 / NOMINAL[r] - 1) < 0.1;
}

void writeRecord(Print &out, instrument::Range r) {
  const RangeCal &c = g_cal[r];
  out.printf("range=%s k0=%.12e t0=%.4f alpha=%.6e beta=%.6e u_k0_ppm=%.3f u_alpha_ppm=%.4f "
             "tmin=%.2f tmax=%.2f date=\"%s\" source=\"%s\"\n",
             instrument::rangeName(r), c.k0, c.t0, c.alpha, c.beta, c.u_k0_ppm, c.u_alpha_ppm, c.tmin,
             c.tmax, c.date, c.source);
}

void write(Print &out) {
  out.println("# nanovolt-divider calibration v2: k(T) = k0 (1 + alpha (T-T0) + beta (T-T0)^2)");
  for (uint8_t i = 1; i < instrument::RANGE_COUNT; i++) writeRecord(out, instrument::Range(i));
}

bool parseLine(const char *line) {
  while (*line == ' ' || *line == '\t') line++;
  if (*line == '#' || *line == '\0' || *line == '\r' || *line == '\n') return true;

  RangeCal c;
  int range = -1;
  const char *p = line;
  char k[16], v[80];
  // Every field is required: a partial record must not silently keep old values.
  uint16_t seen = 0;
  static const char *FIELDS[] = {"range", "k0",  "t0",   "alpha", "beta", "u_k0_ppm",
                                 "u_alpha_ppm", "tmin", "tmax", "date",  "source"};
  constexpr uint16_t ALL = (1u << 11) - 1;
  while (nextToken(p, k, sizeof(k), v, sizeof(v))) {
    int f = -1;
    for (int i = 0; i < 11; i++)
      if (strcmp(k, FIELDS[i]) == 0) f = i;
    if (f < 0) return false;
    seen |= 1u << f;
    double d = 0;
    if (f >= 1 && f <= 8 && !toDouble(v, d)) return false;
    switch (f) {
      case 0:
        for (uint8_t i = 1; i < instrument::RANGE_COUNT; i++)
          if (strcasecmp(v, instrument::rangeName(instrument::Range(i))) == 0) range = i;
        break;
      case 1: c.k0 = d; break;
      case 2: c.t0 = d; break;
      case 3: c.alpha = d; break;
      case 4: c.beta = d; break;
      case 5: c.u_k0_ppm = d; break;
      case 6: c.u_alpha_ppm = d; break;
      case 7: c.tmin = d; break;
      case 8: c.tmax = d; break;
      case 9: strlcpy(c.date, v, sizeof(c.date)); break;
      case 10: strlcpy(c.source, v, sizeof(c.source)); break;
    }
  }
  if (seen != ALL || range < 1 || !plausible(instrument::Range(range), c.k0) || c.tmin > c.tmax)
    return false;
  c.nominal = NOMINAL[range];
  g_cal[range] = c;
  g_dirty = true;
  return true;
}

}  // namespace cal
