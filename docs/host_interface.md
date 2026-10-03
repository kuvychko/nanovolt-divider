# Host interface

What a program driving the divider over USB needs to know: the link, the one trap in opening it,
how to detect a controller reset, grounding, and the SCPI contract. The full command reference is in
[`firmware/README.md`](../firmware/README.md). The examples use Linux on a Raspberry Pi, which is
how the instrument is run, but nothing here is specific to it.

## 1. Link

| | |
|---|---|
| Physical | The display module's USB port (CH340, VID:PID `1a86:7523`). It also powers the instrument, including the relay coils: 40 mA pulses, one at a time. |
| Serial | 115200 8N1, no flow control. Commands end in `\n`, and so do responses. |
| Device name | The CH340 has no serial number, so the USB port position is its identity. Use a `by-path` udev symlink and keep the cable in the same port (rule below). |
| Unsolicited output | Lines starting with `# ` (hash, space): the boot banner, `# ready`, and `DIAG:TRAC` pulse traces. Skip them. A definite-length block starts with `#` followed by a digit, so the two never collide. |
| Radio | Never initialised. USB is the only control path. |

A udev rule that names the port and clears HUPCL (see below), with `ID_PATH` taken from
`udevadm info -q property -n /dev/ttyUSB0`:

```
# /etc/udev/rules.d/99-nvdivider.rules
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", ENV{ID_PATH}=="<path>", SYMLINK+="nvdivider", RUN+="/bin/stty -F /dev/%k -hupcl"
```

### Reset on open: the one trap

The module's auto-reset circuit pulls the ESP32's EN low while **RTS is asserted and DTR is not**. A
reset re-runs the boot safe state (all relays to RESET, i.e. ISOLATE), which in the middle of a
measurement is a silent change of stimulus.

* **On Linux**, `open()` asserts both lines, and pyserial then applies its `dtr` setting before its
  `rts` setting. Opening with `dtr=False, rts=False` therefore passes through "RTS only" and resets the
  board. **Open with both left asserted** (`dtr=True, rts=True`, pyserial's default), so no line ever
  changes.
* **On Windows** both lines are applied together at open, and released/released is safe.
  `tools/scpi.py` handles both platforms.
* **Clear HUPCL** (`stty -hupcl`, the udev rule above), so that closing the port does not drop the lines
  either.

Verified on a Raspberry Pi: with the above, 100 open/close cycles left `SYST:BOOT:COUNT?` unchanged and
`SYST:UPT?` counting. **Verify it on any new host**: read the boot count, open and close the port 100
times, read it again. It must not change.

If the circuit cannot be tamed on some host, the hardware fallback is to lift the RTS-to-EN transistor on
the module. Flashing then needs the BOOT button held.

### Reset detection

Even with the above, a long run must detect a reboot rather than assume there was none. Causes include
brown-out, watchdog, or someone pressing the button.

* `SYST:BOOT:COUNT?` is an NVS counter, incremented on every boot. Record it at start and check it
  regularly. It is also the last field of `SYST:MODE?` (`BOOT=n`), so one query per poll covers state
  and reboots together.
* `SYST:UPT?` gives seconds since boot.
* **On a change:**
  1. mark the affected samples;
  2. re-send `SYST:TIME` (the clock is RAM-only);
  3. re-assert the wanted state with explicit commands.

  The host owns the desired state. The firmware deliberately has no "resume" mode.

### Grounds

`DGND`, the control ground, is tied through USB to the host, and possibly through the host to the
meter's chassis (e.g. via a GPIB adapter). The precision path (NORMAL IN, the high legs, the 1 Ω,
OUT) is galvanically separate: it touches the control side only through relay contacts, and the coil
drivers sit on the far side of the relay's coil-contact isolation. No loop is introduced through the
analog path. Keep the meter's LO on OUT− as the only connection between the measurement and anything
grounded.

## 2. SCPI contract

* **Error queue.** Errors never appear in the response stream; they queue for `SYST:ERR?`
  (`0,"No error"` when clean). **After every write, drain `SYST:ERR?` and raise on anything
  non-zero.** A rejected command changes nothing. That includes `CAL:REC`, which checks every field
  before touching the record.
* **Synchronisation.** Commands execute in order, and a query blocks until everything before it has
  finished. Append `;*OPC?` to a write to wait for completion.
* **Timing.** A coil pulse takes 20 ms plus a 20 ms gap.

  | Command | Pulses | Time |
  |---|---|---|
  | `OUTP` | 1 | 40 ms |
  | `POL` (while injecting) | 3 | 120 ms |
  | `RANG` (while injecting) | 4 | 160 ms |
  | `*RST` | 5 | 200 ms |

  `OUTP OFF` pulses even when already isolated, so a host that re-asserts state should command only
  what differs. SD operations take 50 to 300 ms. A 64 KiB `MMEM:DATA?` chunk takes about 6 s at
  115200 baud.
* **Not a number.** `9.91E+37` stands for "no value": no range selected, or no temperature.

| Need | Command | Response |
|---|---|---|
| Identify | `*IDN?` | `NVD,Nanovolt Divider Rev A,<efuse MAC>,<fw version>` |
| Whole state | `SYST:MODE?` | `BOARD=OK,STATE=KNOWN,RANGE=1E-6,POL=NORM,OUTP=INJECT,TEMP=23.8125,FACTOR=…,CAL=SAVED,LOG=OFF,BOOT=5` |
| Set state | `RANG 1E-5\|1E-6\|1E-7\|NONE`, `POL NORM\|INV`, `OUTP ON\|OFF`, `*RST` | Break-before-make and isolate-while-switching are enforced by the firmware. |
| Temperature | `TEMP?` | °C, 4 decimals (TMP275, 1/16 °C steps, refreshed at 1 Hz) |
| Factor now | `SOUR:FACT?` | Active range at the live temperature. |
| Factor at T | `CAL:FACT? <range>[,<T>]` | `k,u_ppm,in_span`. T defaults to live. `in_span=0` outside [Tmin, Tmax] or with no temperature. |
| Calibration | `CAL:REC <range>,k0,T0,alpha,beta,u_k0_ppm,u_alpha_ppm,Tmin,Tmax,"date","source"`, `CAL:REC? <range>`, `CAL:SAVE`, `CAL:EXP` | See [calibration.md](calibration.md), "Write-back". `CAL:REC?` returns the fields without the range. |
| Clock | `SYST:TIME <unix s>`, `SYST:TIME?` | UTC, RAM only, 0 = unset. Set it on every connect. |
| Reset detection | `SYST:BOOT:COUNT?`, `SYST:UPT?` | |
| Files | `MMEM:CAT? ["/nvd"]`; `MMEM:DATA? "<path>"[,offset[,length ≤ 65536]]` | `"name",size,…`; an IEEE 488.2 block `#<n><len><bytes>` followed by `\n`. `MMEM:DATA?` must be the only command on its line. `tools/scpi.py` `Instrument.fetch()` is a reference implementation of chunked reads. |
