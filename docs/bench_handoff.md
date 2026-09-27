# Handoff to bench-metrology

This page covers what `bench-metrology` needs in order to drive the nanovolt divider from the Raspberry Pi hub and
run the [calibration protocol](calibration_protocol.md). Everything on the instrument side is done and tested:
firmware 0.2.0, on the Rev A board over USB from Windows. The Pi side is not built yet.

## 1. Link

| | |
|---|---|
| Physical | The CYD's USB port (CH340, VID:PID `1a86:7523`) to the Pi. This also powers the instrument, including the relay coils: 40 mA pulses, one at a time. |
| Serial | 115200 8N1, no flow control. Commands end in `\n`, and so do responses. |
| Device name | The CH340 has no serial number, so use a `by-path` udev symlink, e.g. `SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", ENV{ID_PATH}=="<from udevadm info>", SYMLINK+="nvdivider"`. Moving the cable to another port changes the path, so keep it in one port. |
| Unsolicited output | Lines starting with `# ` (hash, space): the boot banner, `# ready`, and `DIAG:TRAC` pulse traces. Skip them. A definite-length block starts with `#` followed by a digit, so the two never collide. |
| Radio | Never initialised. There is no Wi-Fi or Bluetooth; USB is the only control path. |

### Reset on open: the one trap

The CYD's auto-reset circuit pulls EN low while **RTS is asserted and DTR is not**. A reset re-runs the boot safe
state (all relays to RESET, i.e. ISOLATE), which in the middle of a run is a silent change of state.

* **On Linux**, `open()` asserts both lines. pyserial then applies its `dtr` setting before its `rts` setting, so
  opening with `dtr=False, rts=False` passes through "RTS only" and resets the board. **Open with both left asserted**
  (`dtr=True, rts=True`, pyserial's default), so no line ever changes.
* Run `stty -F /dev/nvdivider -hupcl` once per boot (a udev `RUN+=` works), so that closing the port does not drop the
  lines either.
* **Verify it; don't trust it.** Read `SYST:BOOT:COUNT?`, then close and reopen the port 100 times and read it again.
  It must not change. This has been verified on Windows (`tools/scpi.py`, which also documents the platform
  difference), but **not yet on the Pi**.
* If the circuit cannot be tamed, the fallback is hardware: lift the RTS-to-EN transistor on the module. Flashing then
  needs the BOOT button held.

### Reset detection

Even with the above, a run must detect a reboot rather than assume there was none. Possible causes include
brown-out, watchdog, or someone pressing the button.

* `SYST:BOOT:COUNT?` is an NVS counter, incremented on every boot. Record it at run start and check it every cycle.
  It is also the last field of `SYST:MODE?` (`BOOT=n`).
* `SYST:UPT?` gives seconds since boot.
* **On a change:**
  1. mark the affected samples;
  2. re-send `SYST:TIME` (the clock is RAM-only);
  3. re-assert the schedule's state with explicit commands.

  The host owns the desired state. The firmware deliberately has no "resume" mode.

### Grounds

`DGND`, the control ground, is tied through USB to the Pi, and through the Pi to the GPIB adapter and the meter's
chassis. The precision path (NORMAL IN, the high legs, the 1 Ω, OUT) is galvanically separate: it touches the control
side only through relay contacts, and the coil drivers sit on the far side of the relay's coil-contact isolation. The
PSU sits on an isolated LAN segment. No new loop is introduced through the analog path. Still, the meter's LO and the
divider's OUT− should be the only connection between the measurement and anything grounded.

## 2. SCPI contract

The full command reference is in `firmware/README.md`. This section covers what a driver relies on.

* **Error queue.** Errors never appear in the response stream; they queue for `SYST:ERR?` (`0,"No error"` when
  clean). Do what the UDP3305S driver does: **after every write, drain `SYST:ERR?` and raise on anything non-zero.** A
  rejected command changes nothing. That includes `CAL:REC`, which checks every field before touching the record.
* **Synchronisation.** Commands execute in order, and a query blocks until everything before it has finished. Append
  `;*OPC?` to a write to wait for completion.
* **Timing.** A coil pulse takes 20 ms plus a 20 ms gap.

  | Command | Pulses | Time |
  |---|---|---|
  | `OUTP` | 1 | 40 ms |
  | `POL` (while injecting) | 3 | 120 ms |
  | `RANG` (while injecting) | 4 | 160 ms |
  | `*RST` | 5 | 200 ms |

  The ABBA timing in the protocol drops the first 2 s of every dwell anyway. SD operations take 50 to 300 ms. A
  64 KiB `MMEM:DATA?` chunk takes about 6 s at 115200 baud.
* **Not a number.** `9.91E+37` stands for "no value": no range selected, or no temperature.

| Need | Command | Response |
|---|---|---|
| Identify | `*IDN?` | `NVD,Nanovolt Divider Rev A,<efuse MAC>,<fw version>` |
| Whole state | `SYST:MODE?` | `BOARD=OK,STATE=KNOWN,RANGE=1E-6,POL=NORM,OUTP=INJECT,TEMP=23.8125,FACTOR=…,CAL=SAVED,LOG=OFF,BOOT=5` |
| Set state | `RANG 1E-5\|1E-6\|1E-7\|NONE`, `POL NORM\|INV`, `OUTP ON\|OFF`, `*RST` | Break-before-make and isolate-while-switching are enforced by the firmware. |
| Temperature | `TEMP?` | °C, 4 decimals (TMP275, 1/16 °C steps, refreshed at 1 Hz) |
| Factor now | `SOUR:FACT?` | Active range at the live temperature. |
| Factor at T | `CAL:FACT? <range>[,<T>]` | `k,u_ppm,in_span`. T defaults to live. `in_span=0` outside [Tmin, Tmax] or with no temperature. |
| Calibration | `CAL:REC <range>,k0,T0,alpha,beta,u_k0_ppm,u_alpha_ppm,Tmin,Tmax,"date","source"`, `CAL:REC? <range>`, `CAL:SAVE`, `CAL:EXP` | See protocol §8. |
| Clock | `SYST:TIME <unix s>`, `SYST:TIME?` | UTC, RAM only, 0 = unset. |
| Reset detection | `SYST:BOOT:COUNT?`, `SYST:UPT?` | |
| Files | `MMEM:CAT? ["/nvd"]`; `MMEM:DATA? "<path>"[,offset[,length ≤ 65536]]` | `"name",size,…`; an IEEE 488.2 block `#<n><len><bytes>` followed by `\n`. `MMEM:DATA?` must be the only command on its line. `tools/scpi.py` `Instrument.fetch()` is a reference implementation of chunked reads. |

## 3. What to build in bench-metrology

1. **`instruments/nvdivider.py`.** A thin driver in the style of `udp3305s.py`:
   * a raw serial transport (pyserial; not VISA);
   * `write()` that verifies through the error queue;
   * `query()` that skips `# ` lines;
   * `query_block()`;
   * typed helpers: `set_state(range, polarity, inject)`, `temperature()`, `factor(range, t)`, `boot_count()`,
     `set_time()`, `read_cal()` / `write_cal()`, `fetch()`.

   Per the layering rule, it holds no knowledge of why a measurement is taken. Tests run against a fake serial port
   with no hardware attached, as the repo requires.
2. **Experiments.** `psu-drift` (Run P), `divider-ratio` (Run R) and `high-legs` (Run H). All three share one schedule
   builder (protocol §4), `acquisition/loop.py` for reconnect and retry, and the `schedule.jsonl` pattern from
   `experiments/injection.py`. Each sample row gets the divider's TMP275 reading. Add it as run-level structure,
   following `injection.py`'s reasoning about keeping `MEASUREMENT_SCHEMA` stable, or as a documented new column;
   that is the bench repo's call. Each cycle checks `BOOT=`.
3. **Analysis.** Reuse `ThermalModel`, `thermal_lag`, `spectral` and `uncertainty`. New code is only the protocol §6
   combination and the range-ratio cross-check.
4. **Cal write-back.** A separate, explicitly invoked command (never part of a run), with a dry-run mode. It prints
   the records it will send, requires confirmation, sends them, drains the error queue after each, runs `CAL:SAVE`
   and `CAL:EXP`, and reads everything back. **Bench rule 6** ("never implement a calibration write") exists to
   protect the HP 3478A's calibration RAM. It needs an explicit amendment stating that it does not cover the
   divider's calibration, which exists to be written.
5. **Status.** The divider is an instrument like any other in `bench instruments list` / `bench env` provenance: record
   `*IDN?`, the boot count and `CAL:REC?` for all three ranges in every run's metadata.

## 4. Before the first calibration run

- [ ] Divider on the Pi's USB, `/dev/nvdivider` symlink, `-hupcl`.
- [ ] The 100-reconnect boot-count test passes on the Pi.
- [ ] PSU OVP raised to 22 V if V_cal = 20 V (protocol §3).
- [ ] `SYST:BOOT:SAFE?` = 1, `CAL:REC?` nominal on all three ranges, `SYST:ERR?` clean.
- [ ] Optional: delete `/nvd/cal_history.txt` from a PC before the real calibration. It holds firmware-test entries
      from 2026-09-26 (source `FIRMWARE TEST, not a calibration`, then a return to nominal). The firmware itself can
      only append.
