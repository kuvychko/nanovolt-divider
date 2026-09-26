// Per-range calibration record (spec section 8), kept in NVS.
//
//   k(T) = k0 * (1 + alpha * (T - T0))
//
// alpha defaults to 0: no temperature correction until it has been measured. SCPI edits change
// the working copy; CAL:SAVE writes it to NVS, and boot loads it back.
#pragma once
#include <Print.h>
#include <stdint.h>

#include "instrument.h"

namespace cal {

struct RangeCal {
  double nominal;  // R_L / (R_H + R_L), fixed
  double k0;       // calibrated factor at T0
  double t0;       // reference temperature, C
  double alpha;    // ratio tempco, 1/C
  char date[32];   // free text supplied by the host, e.g. ISO 8601
};

void begin();  // load from NVS (defaults where absent)
RangeCal &get(instrument::Range r);  // r must not be RANGE_NONE
bool save();                         // working copy -> NVS
void resetToNominal();               // working copy only
bool dirty();                        // working copy differs from NVS
void markDirty();

// Calibrated factor for range r at temperature t. Temperature correction applies only when alpha
// is non-zero and t is a real reading (not NAN). NAN for RANGE_NONE.
double factor(instrument::Range r, float t);

// Plain-text form used for the SD backup: one "range k0 t0 alpha date" line per range.
void write(Print &out);
bool parseLine(const char *line);  // returns false on a malformed line

}  // namespace cal
