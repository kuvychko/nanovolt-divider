#include "scpi.h"

#include <Arduino.h>
#include <math.h>
#include <string.h>

#include "bus.h"
#include "calibration.h"
#include "coils.h"
#include "instrument.h"
#include "mcp23017.h"
#include "pins.h"
#include "sdstore.h"
#include "settings.h"
#include "tmp275.h"
#include "ui.h"

namespace scpi {

namespace {

// ---------------------------------------------------------------- error queue

constexpr int QUEUE_LEN = 10;
struct QueuedError {
  int code;
  char text[72];
};
QueuedError g_queue[QUEUE_LEN];
int g_queue_n = 0;

// ---------------------------------------------------------------- parsing

constexpr int MAX_PARAMS = 4;
constexpr int MAX_NODES = 5;

struct Ctx {
  const char *params[MAX_PARAMS];
  int nparams;
  String resp;  // this command's response (queries only)
};

typedef void (*Handler)(Ctx &);

struct Command {
  const char *pattern;  // nodes separated by ':', optional nodes in [brackets]; '?' = query form
  Handler fn;
};

// True if `tok` is the long form or the short form (the leading upper-case letters) of `node`.
bool nodeMatch(const char *node, size_t nodeLen, const char *tok, size_t tokLen) {
  size_t shortLen = 0;
  while (shortLen < nodeLen && !islower((unsigned char)node[shortLen])) shortLen++;
  if (tokLen != nodeLen && tokLen != shortLen) return false;
  return strncasecmp(node, tok, tokLen) == 0;
}

struct Node {
  const char *s;
  size_t len;
  bool optional;
};

int splitPattern(const char *p, Node *nodes) {
  int n = 0;
  while (*p && n < MAX_NODES) {
    const char *end = strchr(p, ':');
    size_t len = end ? size_t(end - p) : strlen(p);
    Node &nd = nodes[n++];
    nd.optional = p[0] == '[';
    nd.s = nd.optional ? p + 1 : p;
    nd.len = nd.optional ? len - 2 : len;
    if (!end) break;
    p = end + 1;
  }
  return n;
}

bool matchFrom(const Node *pat, int np, int pi, const Node *hdr, int nh, int hi) {
  if (pi == np) return hi == nh;
  if (pat[pi].optional && matchFrom(pat, np, pi + 1, hdr, nh, hi)) return true;
  return hi < nh && nodeMatch(pat[pi].s, pat[pi].len, hdr[hi].s, hdr[hi].len) &&
         matchFrom(pat, np, pi + 1, hdr, nh, hi + 1);
}

bool headerMatch(const char *pattern, const char *header, size_t headerLen) {
  const size_t plen = strlen(pattern);
  const bool pq = pattern[plen - 1] == '?';
  const bool hq = headerLen && header[headerLen - 1] == '?';
  if (pq != hq) return false;
  if (hq) headerLen--;
  if (pattern[0] == '*') return headerLen == plen - pq && strncasecmp(pattern, header, headerLen) == 0;

  char pbuf[48];
  strlcpy(pbuf, pattern, sizeof(pbuf));
  if (pq) pbuf[plen - 1] = '\0';
  Node pat[MAX_NODES], hdr[MAX_NODES];
  const int np = splitPattern(pbuf, pat);

  if (headerLen && header[0] == ':') header++, headerLen--;
  int nh = 0;
  const char *p = header, *end = header + headerLen;
  while (p < end && nh < MAX_NODES) {
    const char *c = (const char *)memchr(p, ':', end - p);
    const char *e = c ? c : end;
    hdr[nh++] = {p, size_t(e - p), false};
    p = e + 1;
  }
  return matchFrom(pat, np, 0, hdr, nh, 0);
}

bool paramIs(const char *param, const char *keyword) {
  return nodeMatch(keyword, strlen(keyword), param, strlen(param));
}

bool parseBool(const char *p, bool &v) {
  if (paramIs(p, "ON") || strcmp(p, "1") == 0) return v = true, true;
  if (paramIs(p, "OFF") || strcmp(p, "0") == 0) return v = false, true;
  return false;
}

bool parseDouble(const char *p, double &v) {
  char *end;
  v = strtod(p, &end);
  return end != p && *end == '\0' && isfinite(v);
}

bool parseRange(const char *p, instrument::Range &r) {
  if (paramIs(p, "NONE")) return r = instrument::RANGE_NONE, true;
  double v;
  if (!parseDouble(p, v)) return false;
  static const double values[] = {0, 1e-5, 1e-6, 1e-7};
  for (uint8_t i = 1; i < instrument::RANGE_COUNT; i++) {
    if (fabs(v / values[i] - 1) < 0.01) return r = instrument::Range(i), true;
  }
  return false;
}

void fail(int code, const char *text) { pushError(code, text); }

bool check(instrument::Err e) {
  if (e != instrument::OK) fail(e, instrument::errText(e));
  return e == instrument::OK;
}

bool needParams(Ctx &c, int n) {
  if (c.nparams == n) return true;
  fail(c.nparams < n ? -109 : -108, c.nparams < n ? "Missing parameter" : "Parameter not allowed");
  return false;
}

// NAN goes out as the SCPI not-a-number value, 9.91E+37, whatever the format.
String fmtDouble(double v, const char *fmt = "%.10e") {
  if (isnan(v)) return "9.91E+37";
  char b[32];
  snprintf(b, sizeof(b), fmt, v);
  return b;
}

void respondDouble(Ctx &c, double v, const char *fmt = "%.10e") { c.resp = fmtDouble(v, fmt); }

// CAL:* commands take an optional leading range: "CAL:RAT 1E-6,9.99e-7" or "CAL:RAT 9.99e-7"
// (active range). Queries likewise: "CAL:RAT? 1E-6" or "CAL:RAT?".
bool calRange(Ctx &c, int valueParams, instrument::Range &r) {
  if (c.nparams == valueParams + 1) {
    if (!parseRange(c.params[0], r) || r == instrument::RANGE_NONE) {
      fail(-224, "Illegal parameter value;range");
      return false;
    }
    return true;
  }
  if (c.nparams != valueParams) {
    fail(-109, "Missing parameter");
    return false;
  }
  r = instrument::state().range;
  if (r == instrument::RANGE_NONE) {
    fail(-221, "Settings conflict;no range selected, name one");
    return false;
  }
  return true;
}

const char *lastParam(Ctx &c) { return c.params[c.nparams - 1]; }

// ---------------------------------------------------------------- handlers

void idn(Ctx &c) {
  char b[80];
  snprintf(b, sizeof(b), "NVD,Nanovolt Divider Rev A,%012llX,%s", ESP.getEfuseMac(),
           NVD_FW_VERSION);
  c.resp = b;
}
void rst(Ctx &) { check(instrument::safeState()); }
void cls(Ctx &) { g_queue_n = 0; }
void opc(Ctx &c) { c.resp = "1"; }

void systErr(Ctx &c) {
  if (g_queue_n == 0) {
    c.resp = "0,\"No error\"";
    return;
  }
  c.resp = String(g_queue[0].code) + ",\"" + g_queue[0].text + "\"";
  memmove(g_queue, g_queue + 1, sizeof(QueuedError) * --g_queue_n);
}
void systVers(Ctx &c) { c.resp = "1999.0"; }

void systMode(Ctx &c) {
  const instrument::State &s = instrument::state();
  const float t = tmp275::celsius();
  char b[200];
  snprintf(b, sizeof(b), "BOARD=%s,STATE=%s,RANGE=%s,POL=%s,OUTP=%s,TEMP=%s,FACTOR=%s,CAL=%s,LOG=%s",
           s.board ? "OK" : "NONE", s.known ? "KNOWN" : "UNKNOWN", instrument::rangeName(s.range),
           s.polarity == instrument::POL_INV ? "INV" : "NORM", s.inject ? "INJECT" : "ISOLATE",
           fmtDouble(t, "%.4f").c_str(), fmtDouble(cal::factor(s.range, t)).c_str(),
           cal::dirty() ? "UNSAVED" : "SAVED", sdstore::logging() ? "ON" : "OFF");
  c.resp = b;
}

void bootSafe(Ctx &c) {
  bool v;
  if (!needParams(c, 1)) return;
  if (!parseBool(c.params[0], v)) return fail(-224, "Illegal parameter value");
  settings::get().bootSafe = v;
  if (!settings::save()) fail(-200, "Execution error;NVS write failed");
}
void bootSafeQ(Ctx &c) { c.resp = settings::get().bootSafe ? "1" : "0"; }

void systLog(Ctx &c) {
  bool v;
  if (!needParams(c, 1)) return;
  if (!parseBool(c.params[0], v)) return fail(-224, "Illegal parameter value");
  if (!v) return sdstore::logStop();
  if (!sdstore::logStart()) fail(-250, "Mass storage error;cannot create log file");
}
void logQ(Ctx &c) { c.resp = sdstore::logging() ? "1" : "0"; }
void logFileQ(Ctx &c) { c.resp = String("\"") + sdstore::logPath() + "\""; }
void logMark(Ctx &c) {
  if (!needParams(c, 1)) return;
  if (!sdstore::logging()) return fail(-221, "Settings conflict;log is off");
  sdstore::logEvent("MARK", c.params[0]);
}
void logInt(Ctx &c) {
  double v;
  if (!needParams(c, 1)) return;
  if (!parseDouble(c.params[0], v) || v < 0 || v > 86400) return fail(-222, "Data out of range");
  sdstore::setLogInterval(uint32_t(v));
}
void logIntQ(Ctx &c) { c.resp = String(sdstore::logInterval()); }

void outp(Ctx &c) {
  bool v;
  if (!needParams(c, 1)) return;
  if (!parseBool(c.params[0], v)) return fail(-224, "Illegal parameter value");
  check(instrument::setOutput(v));
}
void outpQ(Ctx &c) { c.resp = instrument::state().inject ? "1" : "0"; }

void pol(Ctx &c) {
  if (!needParams(c, 1)) return;
  if (paramIs(c.params[0], "NORMal")) return (void)check(instrument::setPolarity(instrument::POL_NORM));
  if (paramIs(c.params[0], "INVerted")) return (void)check(instrument::setPolarity(instrument::POL_INV));
  fail(-224, "Illegal parameter value");
}
void polQ(Ctx &c) { c.resp = instrument::state().polarity == instrument::POL_INV ? "INV" : "NORM"; }

void rang(Ctx &c) {
  instrument::Range r;
  if (!needParams(c, 1)) return;
  if (!parseRange(c.params[0], r)) return fail(-224, "Illegal parameter value;1E-5|1E-6|1E-7|NONE");
  check(instrument::setRange(r));
}
void rangQ(Ctx &c) { c.resp = instrument::rangeName(instrument::state().range); }

void factQ(Ctx &c) {
  const instrument::State &s = instrument::state();
  respondDouble(c, cal::factor(s.range, tmp275::celsius()));
}
void tempQ(Ctx &c) { respondDouble(c, tmp275::celsius(), "%.4f"); }

void calRat(Ctx &c) {
  instrument::Range r;
  double v;
  if (!calRange(c, 1, r)) return;
  if (!parseDouble(lastParam(c), v)) return fail(-224, "Illegal parameter value");
  if (!(fabs(v / cal::get(r).nominal - 1) < 0.1)) return fail(-222, "Data out of range;>10% from nominal");
  cal::get(r).k0 = v;
  cal::markDirty();
}
void calRatQ(Ctx &c) {
  instrument::Range r;
  if (calRange(c, 0, r)) respondDouble(c, cal::get(r).k0, "%.12e");
}
void calNomQ(Ctx &c) {
  instrument::Range r;
  if (calRange(c, 0, r)) respondDouble(c, cal::get(r).nominal, "%.12e");
}
void calTc(Ctx &c) {
  instrument::Range r;
  double v;
  if (!calRange(c, 1, r)) return;
  if (!parseDouble(lastParam(c), v) || fabs(v) > 1e-3) return fail(-222, "Data out of range");
  cal::get(r).alpha = v;
  cal::markDirty();
}
void calTcQ(Ctx &c) {
  instrument::Range r;
  if (calRange(c, 0, r)) respondDouble(c, cal::get(r).alpha, "%.6e");
}
void calTref(Ctx &c) {
  instrument::Range r;
  double v;
  if (!calRange(c, 1, r)) return;
  if (!parseDouble(lastParam(c), v) || v < -40 || v > 125) return fail(-222, "Data out of range");
  cal::get(r).t0 = v;
  cal::markDirty();
}
void calTrefQ(Ctx &c) {
  instrument::Range r;
  if (calRange(c, 0, r)) respondDouble(c, cal::get(r).t0, "%.4f");
}
void calDate(Ctx &c) {
  instrument::Range r;
  if (!calRange(c, 1, r)) return;
  if (!*lastParam(c)) return fail(-224, "Illegal parameter value;empty");
  strlcpy(cal::get(r).date, lastParam(c), sizeof(cal::get(r).date));
  cal::markDirty();
}
void calDateQ(Ctx &c) {
  instrument::Range r;
  if (calRange(c, 0, r)) c.resp = String("\"") + cal::get(r).date + "\"";
}
void calSave(Ctx &) {
  if (!cal::save()) fail(-200, "Execution error;NVS write failed");
}
void calDef(Ctx &) { cal::resetToNominal(); }
void calExp(Ctx &) {
  if (!sdstore::exportCal()) fail(-250, "Mass storage error;cal export failed");
}
void calImp(Ctx &) {
  if (!sdstore::importCal()) fail(-250, "Mass storage error;cal import failed or file malformed");
}

void diagI2c(Ctx &c) {
  uint8_t found[16];
  const size_t n = bus::scan(found, 16);
  if (!n) c.resp = "NONE";
  for (size_t i = 0; i < n; i++) {
    char b[8];
    snprintf(b, sizeof(b), "%s0x%02X", i ? "," : "", found[i]);
    c.resp += b;
  }
}

class StringPrint : public Print {
 public:
  explicit StringPrint(String &s) : s_(s) {}
  size_t write(uint8_t b) override {
    s_ += char(b);
    return 1;
  }

 private:
  String &s_;
};

void diagMcp(Ctx &c) {
  StringPrint sp(c.resp);
  mcp::dump(sp);
}

void diagPuls(Ctx &c) {
  if (!needParams(c, 2)) return;
  const char *k = c.params[0];
  if ((k[0] != 'K' && k[0] != 'k') || k[1] < '1' || k[1] > '5' || k[2]) return fail(-224, "Illegal parameter value;K1..K5");
  uint8_t coil;
  if (paramIs(c.params[1], "SET")) coil = coils::SET;
  else if (paramIs(c.params[1], "RESet")) coil = coils::RESET;
  else return fail(-224, "Illegal parameter value;SET|RES");
  check(instrument::rawPulse(k[1] - '1', coil));
}

void setTiming(Ctx &c, bool width) {
  double v;
  if (!needParams(c, 1)) return;
  if (!parseDouble(c.params[0], v) || v < coils::PULSE_MS_MIN || v > coils::PULSE_MS_MAX)
    return fail(-222, "Data out of range;5..100 ms");
  if (width) {
    coils::setPulseMs(uint16_t(v));
    settings::get().pulseMs = coils::pulseMs();
  } else {
    coils::setGapMs(uint16_t(v));
    settings::get().gapMs = coils::gapMs();
  }
  if (!settings::save()) fail(-200, "Execution error;NVS write failed");
}
void diagWidt(Ctx &c) { setTiming(c, true); }
void diagWidtQ(Ctx &c) { c.resp = String(coils::pulseMs()); }
void diagGap(Ctx &c) { setTiming(c, false); }
void diagGapQ(Ctx &c) { c.resp = String(coils::gapMs()); }

void diagPins(Ctx &c) {
  bool io18, io27;
  bus::probePullups(io18, io27);
  c.resp = String("IO18=") + (io18 ? "PULLUP" : "NONE") + ",IO27=" + (io27 ? "PULLUP" : "NONE");
}

void diagSd(Ctx &c) {
  StringPrint sp(c.resp);
  sdstore::info(sp);
}

void diagTrac(Ctx &c) {
  bool v;
  if (!needParams(c, 1)) return;
  if (!parseBool(c.params[0], v)) return fail(-224, "Illegal parameter value");
  coils::setTrace(v);
}
void diagTracQ(Ctx &c) { c.resp = coils::trace() ? "1" : "0"; }

void diagInv(Ctx &c) {
  bool v;
  if (!needParams(c, 1)) return;
  if (!parseBool(c.params[0], v)) return fail(-224, "Illegal parameter value");
  ui::invertDisplay(v);
}
void diagTouchCal(Ctx &) { ui::requestTouchCal(); }
void diagTouchQ(Ctx &c) {
  StringPrint sp(c.resp);
  ui::printTouch(sp);
}

const Command COMMANDS[] = {
    {"*IDN?", idn},
    {"*RST", rst},
    {"*CLS", cls},
    {"*OPC?", opc},
    {"SYSTem:ERRor:[NEXT]?", systErr},
    {"SYSTem:VERSion?", systVers},
    {"SYSTem:MODE?", systMode},
    {"SYSTem:BOOT:SAFE", bootSafe},
    {"SYSTem:BOOT:SAFE?", bootSafeQ},
    {"SYSTem:LOG:[STATe]", systLog},
    {"SYSTem:LOG:[STATe]?", logQ},
    {"SYSTem:LOG:FILE?", logFileQ},
    {"SYSTem:LOG:MARK", logMark},
    {"SYSTem:LOG:INTerval", logInt},
    {"SYSTem:LOG:INTerval?", logIntQ},
    {"OUTPut:[STATe]", outp},
    {"OUTPut:[STATe]?", outpQ},
    {"[SOURce]:POLarity", pol},
    {"[SOURce]:POLarity?", polQ},
    {"[SOURce]:RANGe", rang},
    {"[SOURce]:RANGe?", rangQ},
    {"[SOURce]:FACTor?", factQ},
    {"[MEASure]:TEMPerature?", tempQ},
    {"CALibration:RATio", calRat},
    {"CALibration:RATio?", calRatQ},
    {"CALibration:NOMinal?", calNomQ},
    {"CALibration:TC", calTc},
    {"CALibration:TC?", calTcQ},
    {"CALibration:TREF", calTref},
    {"CALibration:TREF?", calTrefQ},
    {"CALibration:DATE", calDate},
    {"CALibration:DATE?", calDateQ},
    {"CALibration:SAVE", calSave},
    {"CALibration:DEFault", calDef},
    {"CALibration:EXPort", calExp},
    {"CALibration:IMPort", calImp},
    {"DIAGnostic:I2C?", diagI2c},
    {"DIAGnostic:MCP?", diagMcp},
    {"DIAGnostic:PULSe", diagPuls},
    {"DIAGnostic:PULSe:WIDTh", diagWidt},
    {"DIAGnostic:PULSe:WIDTh?", diagWidtQ},
    {"DIAGnostic:PULSe:GAP", diagGap},
    {"DIAGnostic:PULSe:GAP?", diagGapQ},
    {"DIAGnostic:PINS?", diagPins},
    {"DIAGnostic:SD?", diagSd},
    {"DIAGnostic:TRACe", diagTrac},
    {"DIAGnostic:TRACe?", diagTracQ},
    {"DIAGnostic:DISPlay:INVert", diagInv},
    {"DIAGnostic:TOUCh:CALibrate", diagTouchCal},
    {"DIAGnostic:TOUCh?", diagTouchQ},
};

// Splits `s` in place on `sep` outside double quotes; returns the number of pieces.
int splitQuoted(char *s, char sep, char **out, int max) {
  int n = 0;
  bool quoted = false;
  out[n++] = s;
  for (char *p = s; *p; p++) {
    if (*p == '"') quoted = !quoted;
    else if (*p == sep && !quoted) {
      *p = '\0';
      if (n == max) return -1;
      out[n++] = p + 1;
    }
  }
  return n;
}

char *trim(char *s) {
  while (isspace((unsigned char)*s)) s++;
  char *e = s + strlen(s);
  while (e > s && isspace((unsigned char)e[-1])) *--e = '\0';
  return s;
}

void executeOne(char *cmd, String &resp) {
  cmd = trim(cmd);
  if (!*cmd) return;
  size_t hlen = strcspn(cmd, " \t");
  char *args = cmd + hlen;

  Ctx c;
  c.nparams = 0;
  args = trim(args);
  if (*args) {
    char *parts[MAX_PARAMS];
    c.nparams = splitQuoted(args, ',', parts, MAX_PARAMS);
    if (c.nparams < 0) return fail(-108, "Parameter not allowed;too many");
    for (int i = 0; i < c.nparams; i++) {
      char *p = trim(parts[i]);
      size_t n = strlen(p);
      if (n >= 2 && p[0] == '"' && p[n - 1] == '"') p[n - 1] = '\0', p++;
      c.params[i] = p;
    }
  }

  for (const Command &cmdDef : COMMANDS) {
    if (!headerMatch(cmdDef.pattern, cmd, hlen)) continue;
    cmdDef.fn(c);
    if (c.resp.length()) {
      if (resp.length()) resp += ';';
      resp += c.resp;
    }
    return;
  }
  fail(-113, "Undefined header");
}

}  // namespace

void pushError(int code, const char *text) {
  if (g_queue_n == QUEUE_LEN) {
    g_queue[QUEUE_LEN - 1].code = -350;
    strlcpy(g_queue[QUEUE_LEN - 1].text, "Queue overflow", sizeof(g_queue[0].text));
    return;
  }
  g_queue[g_queue_n].code = code;
  strlcpy(g_queue[g_queue_n].text, text, sizeof(g_queue[g_queue_n].text));
  g_queue_n++;
}

void execute(const char *line, Print &out) {
  char buf[256];
  strlcpy(buf, line, sizeof(buf));
  char *cmds[8];
  const int n = splitQuoted(buf, ';', cmds, 8);
  if (n < 0) return fail(-100, "Command error;too many commands in one line");
  String resp;
  for (int i = 0; i < n; i++) executeOne(cmds[i], resp);
  if (resp.length()) {
    out.print(resp);
    out.print('\n');
  }
}

}  // namespace scpi
