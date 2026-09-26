// SCPI-style command interpreter. Transport-agnostic: USB serial feeds it now, and Wi-Fi/TCP
// will feed the same instance later.
//
// One program message per line; ';' separates commands within it. Headers match in long or short
// form, case-insensitively (OUTPut -> OUTP or OUTPUT), and a leading ':' is optional. Responses
// to the queries in one line are joined with ';' and end with '\n'. Errors go to the queue
// (SYST:ERR?), never to the response stream.
#pragma once
#include <Print.h>

namespace scpi {

void execute(const char *line, Print &out);

// Pushes an error onto the queue (also used by the UI for failed touch actions).
void pushError(int code, const char *text);

}  // namespace scpi
