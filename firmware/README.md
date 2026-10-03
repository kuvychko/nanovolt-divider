# Rev A firmware

Firmware for the ESP32 "Cheap Yellow Display" (ESP32-2432S028R family) that runs the nanovolt divider:

* the relay state machine for K1..K5, through the MCP23017;
* the TMP275;
* per-range calibration k(T) in NVS, with a backup, an append-only history and a CSV run log on the microSD card;
* SCPI over USB serial;
* the touchscreen front panel.

The instrument is controlled over USB from a host computer (e.g. a Raspberry Pi): see
[docs/host_interface.md](../docs/host_interface.md) for the host side, and
[docs/calibration.md](../docs/calibration.md) for how the calibration is measured. **The radio is never
initialised:** there is no Wi-Fi or Bluetooth, and no 2.4 GHz transmitter a few centimetres from a nanovolt path.
The module's RGB LED is held off; it is inside the enclosure.

## Build and flash

The project uses PlatformIO. Install it with `uv tool install platformio`. Set `upload_port` and `monitor_port`
in `platformio.ini` to your module's serial port (they are `COM8` there), and pass `-p <port>` to `tools/scpi.py`.

```
pio run -d firmware -e cyd -e cyd_st7789 -e cyd_sim   # build every environment (plain `pio run` builds only cyd)
pio run -d firmware -e cyd -t upload       # flash
uv run tools/scpi.py -p <port>             # interactive SCPI terminal
uv run tools/scpi.py -p <port> "*IDN?" "SYST:MODE?"  # one-shot
```

| Environment | Use |
|---|---|
| `cyd` | Standard CYD with an ILI9341 panel. The default. |
| `cyd_st7789` | CYD2USB variant (two USB ports) with an ST7789 panel. Use it if `cyd` shows garbage or wrong colours. `DIAG:DISP:INV ON` flips the colour inversion at run time, to help tell the variants apart. |
| `cyd_sim` | No board needed. The MCP23017 and TMP275 are simulated, and every coil pulse is printed as `# PULSE K5 RESET (GPA0) 20 ms`. Use it to check relay sequencing. |

The platform is pinned to `espressif32@7.1.3` (Arduino core 2.0.17) and `LovyanGFX@1.2.30`. Core logging is compiled
out (`CORE_DEBUG_LEVEL=0`), because it would land in the SCPI response stream. The firmware's own unsolicited lines
(the boot banner and the pulse trace) all start with `# `, so a host can skip them.

## How it drives the board

* **I2C is SDA = IO27, SCL = IO18.** See the top-level README, "Display harness".
* **Coil table.** The table is in `src/coils.cpp`, and nowhere else. It follows the layout order: GPB0..7 = K4 S, K4 R,
  K1 S, K1 R, K2 S, K2 R, K3 S, K3 R; GPA0 = K5 R, GPA1 = K5 S. GPA2..7 stay inputs.
* **One coil at a time.** Every pulse first confirms that both output latches read back 0. It then sets one bit,
  holds it for the pulse width (20 ms by default), clears it, reads the latches back again, and waits the gap
  (20 ms).
* **The MCP23017 survives an ESP32 reboot.** R23 ties `~RESET` high, so a reboot mid-pulse would leave a coil
  energised. Boot therefore clears OLATA/OLATB before anything else, including before it makes any pin an output.
* **Relay rules ([design §6.3](../docs/nanovolt_divider_rev_a.md#63-relay-safetystate-rules)).**
  * At boot, and on `*RST`, the firmware pulses the safe state: K5 RESET (ISOLATE) first, then K1..K3 RESET, then K4
    RESET.
  * A range or polarity change runs this sequence:
    1. isolate;
    2. RESET the old range (break);
    3. SET the new one (make);
    4. restore INJECT if it was on.

    For example, `RANG 1E-6` while injecting on 1E-5 pulses K5R, K1R, K2S, K5S.
  * INJECT is refused while no range is selected.
* **State is assumed, not measured.** Latching relays cannot be read back. The state shown is what the last successful
  pulses produced. It is `UNKNOWN` until the boot safe state has run, and after any failed pulse or raw `DIAG:PULS`.
  While the state is unknown, all relay commands except `*RST` are refused. On the touchscreen, tap the red banner.
* **No board.** With no MCP23017 answering, the screen shows `NO BOARD` and relay commands return `-241`. The firmware
  re-probes every 2 s. A board that appears later is never pulsed automatically: its state is `UNKNOWN` until
  `*RST`.

### microSD and the shared IO18

The card's SCK is IO18, which is also I2C SCL. The bus stays in I2C mode, and each card access switches it to SPI,
mounts the card, does the work, unmounts and switches back (`bus::SdSession`). This is safe both ways:

* I2C traffic clocks SCK while the card's CS is held high, so the card ignores it.
* SPI clocking toggles SCL while SDA idles high, which never forms an I2C START.

Card access happens only between operations, never during a coil pulse. The touch controller is bit-banged on its own
pins, because the only free SPI host belongs to the card.

Files on the card:

| Path | Contents |
|---|---|
| `/nvd/cal.txt` | Calibration backup (`CAL:EXP` / `CAL:IMP`): one `key=value` line per range, `range= k0= t0= alpha= beta= u_k0_ppm= u_alpha_ppm= tmin= tmax= date="" source=""`. An import requires every field. |
| `/nvd/cal_history.txt` | Every `CAL:SAVE`, appended: a `# CAL:SAVE utc=… boot=…` line and the three records. The firmware never rewrites or deletes it. |
| `/nvd/log_NNNN.csv` | Run log: `ms,utc,event,range,polarity,output,temp_C,factor,note`. It gets a row for every relay change, for every `SYST:LOG:MARK`, and a `TEMP` row every `SYST:LOG:INT` seconds (default 10; 0 turns it off). `utc` is `-` until the host sends `SYST:TIME`. |

`MMEM:CAT?` and `MMEM:DATA?` read these over USB, so the card never has to come out:
`uv run tools/scpi.py --fetch /nvd/cal_history.txt hist.txt`. From Git Bash, prefix the command with
`MSYS_NO_PATHCONV=1`, or Bash rewrites `/nvd/...` into a Windows path.

### Calibration model

```
k(T) = k0 · [1 + alpha (T − T0) + beta (T − T0)²]
u(T) = sqrt(u_k0² + (u_alpha · (T − T0))²)   ppm
```

T is the TMP275 reading. Each range carries its own record, including the span [tmin, tmax] it was measured over.
Before calibration the records are nominal: k0 = 1/(R_H + 1), no tempco, and u_k0 from the part tolerances
(10050 / 10050 / 14142 ppm). Records are stored as one NVS blob per range, so a save is all-or-nothing per range.

## SCPI reference

These rules apply to every command:

* Headers match in long or short form, case-insensitively.
* A leading `:` is optional.
* `;` separates commands on one line. The responses to all the queries on a line come back joined by `;`.
* Errors go to the queue, which `SYST:ERR?` reads. A value that does not exist, such as the factor with no range
  selected or a missing temperature, reads `9.91E+37`.

| Command | |
|---|---|
| `*IDN?` `*RST` `*CLS` `*OPC?` | `*RST` pulses the safe state. |
| `SYST:ERR?` `SYST:VERS?` | |
| `SYST:MODE?` | Full state: `BOARD=,STATE=,RANGE=,POL=,OUTP=,TEMP=,FACTOR=,CAL=,LOG=,BOOT=`. |
| `SYST:TIME <unix s>` / `SYST:TIME?` | UTC from the host, kept in RAM (0 until set). Stamps the run log and the cal history. |
| `SYST:BOOT:COUNT?` `SYST:UPT?` | Boots since the NVS was first written, and seconds since this boot. The count changing mid-run means the instrument restarted. |
| `OUTP ON\|OFF` / `OUTP?` | INJECT / ISOLATE. `OUTP OFF` always pulses, even if already isolated. |
| `POL NORM\|INV` / `POL?` | Changes happen while isolated. |
| `RANG 1E-5\|1E-6\|1E-7\|NONE` / `RANG?` | Break-before-make, while isolated. |
| `SOUR:FACT? [T]` | Calibrated factor of the active range, at the live TMP275 temperature or at T. |
| `CAL:FACT? range[,T]` | `k,u_ppm,in_span` for any range, at the live temperature or at T. `in_span` is 0 outside the record's [tmin, tmax] or with no temperature. |
| `CAL:REC range,k0,T0,alpha,beta,u_k0_ppm,u_alpha_ppm,tmin,tmax,"date","source"` / `CAL:REC? range` | One range's whole record, written atomically: any invalid field rejects the lot. The query returns the same fields after the range. This is the command the calibration write-back uses. |
| `TEMP?` | TMP275, °C. |
| `CAL:RAT [range,]k` / `CAL:RAT? [range]` | k0. The range defaults to the active one. Values more than 10 % from nominal are rejected. |
| `CAL:TC [range,]alpha` / `CAL:TC?` | Ratio tempco, 1/°C. The default 0 means no correction. |
| `CAL:TREF [range,]T0` / `CAL:TREF?` | Reference temperature, °C. |
| `CAL:DATE [range,]"text"` / `CAL:DATE?` | Free text, e.g. an ISO 8601 date. |
| `CAL:NOM? [range]` | Nominal factor, 1/(R_H + 1). |
| `CAL:SAVE` | Writes the working calibration to NVS and appends it to `/nvd/cal_history.txt`. The other `CAL:` edits change only the working copy (`SYST:MODE?` shows `CAL=UNSAVED`). If the history append fails, the save still stands and `-250` is queued. |
| `CAL:DEF` | Resets the working copy to nominal. |
| `CAL:EXP` / `CAL:IMP` | Writes the working copy to `/nvd/cal.txt`, or reads it back from there. `CAL:SAVE` after an import. |
| `SYST:LOG ON\|OFF` / `SYST:LOG?` | Starts a new `/nvd/log_NNNN.csv`, or stops logging. |
| `SYST:LOG:FILE?` `SYST:LOG:MARK "text"` `SYST:LOG:INT s` | Log file name, a note row (e.g. `"A forward"` during an ABBA run), and the temperature-row interval. |
| `SYST:BOOT:SAFE ON\|OFF` | Whether boot pulses the safe state. Stored in NVS; the default is ON. |
| `MMEM:CAT? ["dir"]` | `"name",size,...` for a directory, `/nvd` by default. |
| `MMEM:DATA? "path"[,offset[,length]]` | Up to 65536 bytes of a file, as an IEEE 488.2 definite-length block `#<n><len><bytes>` followed by `\n`. Must be the only command on its line. |
| `DIAG:I2C?` | Bus scan. Expect `0x20,0x48` with the board connected. |
| `DIAG:MCP?` | MCP23017 register dump. |
| `DIAG:PULS K1..K5,SET\|RES` | One raw pulse, bypassing the rules. Leaves the state `UNKNOWN`. |
| `DIAG:PULS:WIDT ms` / `DIAG:PULS:GAP ms` | 5..100 ms. Stored in NVS. |
| `DIAG:TRAC ON\|OFF` | Prints each pulse as `# PULSE ...`. |
| `DIAG:PINS?` | IO18/IO27 read with internal pull-downs: `PULLUP` means an external pull-up is fitted. |
| `DIAG:SD?` | Card type and size. |
| `DIAG:TOUC:CAL` / `DIAG:TOUC?` | Runs the 3-point touch calibration, or returns the current raw and mapped touch point. Holding the screen at power-up also starts the calibration. |
| `DIAG:DISP:INV ON\|OFF` | Panel colour inversion (not stored). |

## First power-on with the board

Before you start, flash the `cyd` build with the module alone, and set `SYST:BOOT:SAFE OFF`. That way the first coil
pulses are ones you fire by hand, not five at once at boot.

1. **Harness.** Land every wire by signal name (top-level README, "Display harness"). The J7 silk numbers are
   reversed against the module. With the power off, buzz the harness from the module pins to the pads:

   | Module pin | Board pad |
   |---|---|
   | 5V | `J7` pad 3 |
   | GND (UART/power connector) | `J7` pad 4 |
   | GND (3V3 connector) | `J8` pad 1 |
   | IO18 | `J8` pad 2 |
   | IO27 | `J8` pad 3 |
   | 3.3V | `J8` pad 4 |

   A reversed 5 V would reach the coil drivers the moment USB is plugged in, so this check comes before any power.
2. **Power on.** The banner should read `STATE UNKNOWN`, and the `BOARD` and `TEMP` status lights should be green.
3. `DIAG:I2C?` should return `0x20,0x48`. `DIAG:PINS?` should now report `PULLUP` on both pins: those are R21/R22,
   because the module itself has none (with the module alone, `DIAG:PINS?` reads `IO18=NONE,IO27=NONE`).
4. `DIAG:MCP?` should show `IODIRA=0xFC`, `IODIRB=0x00` and both `OLAT` registers `0x00`.
5. `TEMP?` should give a plausible room temperature.
6. `DIAG:TRAC ON`, then pulse each coil by hand, listening for the click and ideally watching the collector on a scope:

   ```
   DIAG:PULS K5,RES
   DIAG:PULS K5,SET
   DIAG:PULS K5,RES
   ```

   Repeat for K1..K4. With a meter on the contacts, check each relay's pole against the state table in the top-level
   README.
7. `*RST` should pulse the whole safe state. Then `SYST:BOOT:SAFE ON`, and power-cycle to confirm the boot sequence.
8. Walk the ranges with `OUTP ON`, `RANG 1E-6`, `POL INV` and so on, meter the output, and check `SYST:ERR?` is clean.
