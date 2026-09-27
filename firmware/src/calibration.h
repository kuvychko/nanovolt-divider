// Per-range calibration record (docs/calibration_protocol.md), kept in NVS.
//
//   k(T) = k0 * (1 + alpha * (T - T0) + beta * (T - T0)^2)
//
// T is the TMP275 reading on the 1 ohm island. alpha and beta default to 0: no temperature
// correction until it has been measured. SCPI edits change the working copy; CAL:SAVE writes it
// to NVS (and appends it to the SD history), and boot loads it back.
#pragma once
#include <Print.h>
#include <stdint.h>

#include "instrument.h"

namespace cal {

struct RangeCal {
  double nominal;      // R_L / (R_H + R_L), fixed; not stored
  double k0;           // calibrated factor at T0
  double t0;           // reference temperature, C
  double alpha;        // 1/C
  double beta;         // 1/C^2
  double u_k0_ppm;     // standard uncertainty of k0
  double u_alpha_ppm;  // standard uncertainty of alpha, ppm/C
  double tmin, tmax;   // temperature span the record was measured over, C
  char date[32];       // free text from the host, e.g. ISO 8601
  char source[64];     // provenance: the bench run IDs, or "nominal"
};

struct Eval {
  double k;       // NAN for RANGE_NONE
  double u_ppm;   // sqrt(u_k0^2 + (u_alpha * (T - T0))^2)
  bool in_span;   // T inside [tmin, tmax]; false when T is unknown
};

void begin();  // load from NVS (defaults where absent)
RangeCal &get(instrument::Range r);  // r must not be RANGE_NONE
bool save();                         // working copy -> NVS
void resetToNominal();               // working copy only
bool dirty();                        // working copy differs from NVS
void markDirty();

// Calibrated factor for range r at temperature t (NAN t = no correction, k0).
Eval evaluate(instrument::Range r, float t);
double factor(instrument::Range r, float t);  // evaluate().k

// Rejects a k0 more than 10 % from nominal: that far out is a typo, not a calibration.
bool plausible(instrument::Range r, double k0);

// Text form used on the SD card: one key=value line per range, strings quoted.
//   range=1E-6 k0=... t0=... alpha=... beta=... u_k0_ppm=... u_alpha_ppm=... tmin=... tmax=...
//   date="..." source="..."
void writeRecord(Print &out, instrument::Range r);
void write(Print &out);            // header comment + all three ranges
bool parseLine(const char *line);  // true for a blank/comment line or a valid record

}  // namespace cal
