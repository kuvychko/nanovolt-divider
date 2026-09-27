// microSD: calibration backup and the run log. Every call mounts the card for its own duration
// (bus::SdSession), so a missing or removed card is an error return, never a hang.
#pragma once
#include <Print.h>
#include <stdint.h>

namespace sdstore {

constexpr const char *DIR = "/nvd";
constexpr const char *CAL_FILE = "/nvd/cal.txt";
constexpr const char *CAL_HISTORY_FILE = "/nvd/cal_history.txt";

bool info(Print &out);  // DIAG:SD? - card type, size, free space
bool exportCal();       // working calibration -> /nvd/cal.txt
bool importCal();       // /nvd/cal.txt -> working calibration (then CAL:SAVE to keep it)
// Appends the saved calibration, stamped with UTC and the boot count, to /nvd/cal_history.txt.
// Append-only: the audit trail of every calibration this instrument has carried.
bool appendCalHistory();

// Run log: /nvd/log_NNNN.csv, one row per relay change, per SYST:LOG:MARK, and a temperature row
// every interval. Columns: ms, utc, event, range, polarity, output, temp_C, factor, note
// (utc is ISO 8601 once the host has sent SYST:TIME, "-" before that).
bool logStart();
void logStop();
bool logging();
const char *logPath();
void logEvent(const char *event, const char *note = "");
void setLogInterval(uint32_t seconds);  // 0 = event rows only
uint32_t logInterval();
void poll();  // periodic temperature rows
bool lastOk();  // last card access succeeded (status bar)

// MMEM:CAT?: "name",size pairs, comma-separated. false if the card or directory is missing.
bool catalog(Print &out, const char *dir);
// MMEM:DATA?: bytes [offset, offset + length) of a file as an IEEE 488.2 definite-length block
// (#<digits><length><bytes>), clipped to the file. Returns the byte count sent, -1 on error (in
// which case nothing was written).
long readBlock(Print &out, const char *path, uint32_t offset, uint32_t length);

}  // namespace sdstore
