// microSD: calibration backup and the run log. Every call mounts the card for its own duration
// (bus::SdSession), so a missing or removed card is an error return, never a hang.
#pragma once
#include <Print.h>
#include <stdint.h>

namespace sdstore {

constexpr const char *DIR = "/nvd";
constexpr const char *CAL_FILE = "/nvd/cal.txt";

bool info(Print &out);  // DIAG:SD? - card type, size, free space
bool exportCal();       // working calibration -> /nvd/cal.txt
bool importCal();       // /nvd/cal.txt -> working calibration (then CAL:SAVE to keep it)

// Run log: /nvd/log_NNNN.csv, one row per relay change, per SYST:LOG:MARK, and a temperature row
// every interval. Columns: ms, event, range, polarity, output, temp_C, factor, note.
bool logStart();
void logStop();
bool logging();
const char *logPath();
void logEvent(const char *event, const char *note = "");
void setLogInterval(uint32_t seconds);  // 0 = event rows only
uint32_t logInterval();
void poll();  // periodic temperature rows
bool lastOk();  // last card access succeeded (status bar)

}  // namespace sdstore
