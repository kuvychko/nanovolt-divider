# Rev A firmware

Firmware for the ESP32 "Cheap Yellow Display" (ESP32-2432S028R family) that runs the nanovolt divider:

* the relay state machine for K1..K5, through the MCP23017;
* the TMP275;
* per-range calibration in NVS, with a backup on the microSD card;
* a CSV run log on the card;
* SCPI over USB serial;
* the touchscreen front panel.

Wi-Fi/TCP comes later. The SCPI interpreter (`src/scpi.cpp`) has no transport dependency, so the TCP link will feed
the same interpreter.

## Build and flash

The project uses PlatformIO. Install it with `uv tool install platformio`. The CYD's CH340 is `COM8` in
`platformio.ini`.

```
pio run -d firmware                        # build all environments
pio run -d firmware -e cyd -t upload       # flash
uv run tools/scpi.py                       # interactive SCPI terminal (COM8)
uv run tools/scpi.py "*IDN?" "SYST:MODE?"  # one-shot
```

| Environment | Use |
|---|---|
| `cyd` | Standard CYD with an ILI9341 panel. The default. |
| `cyd_st7789` | CYD2USB variant (two USB ports) with an ST7789 panel. Use it if `cyd` shows garbage or wrong colours. `DIAG:DISP:INV ON` flips the colour inversion at run time, to help tell the variants apart. |
| `cyd_sim` | No board needed. The MCP23017 and TMP275 are simulated, and every coil pulse is printed as `# PULSE K5 RESET (GPA0) 20 ms`. Use it to check relay sequencing. |

The platform is pinned to `espressif32@7.1.3` (Arduino core 2.0.17) and `LovyanGFX@1.2.30`. Core logging is compiled
out (`CORE_DEBUG_LEVEL=0`), because it would land in the SCPI response stream. The firmware's own unsolicited lines
(the boot banner and the pulse trace) all start with `#`, so a host can skip them.

## How it drives the board

* **I2C is SDA = IO27, SCL = IO18.** See the top-level README, "Display harness".
* **Coil table.** The table is in `src/coils.cpp`, and nowhere else. It follows the layout order: GPB0..7 = K4 S, K4 R,
  K1 S, K1 R, K2 S, K2 R, K3 S, K3 R; GPA0 = K5 R, GPA1 = K5 S. GPA2..7 stay inputs.
* **One coil at a time.** Every pulse first confirms that both output latches read back 0. It then sets one bit,
  holds it for the pulse width (20 ms by default), clears it, reads the latches back again, and waits the gap
  (20 ms).
* **The MCP23017 survives an ESP32 reboot.** R23 ties `~RESET` high, so a reboot mid-pulse would leave a coil
  energised. Boot therefore clears OLATA/OLATB before anything else, including before it makes any pin an output.
* **Relay rules (spec §6.3).**
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
| `/nvd/cal.txt` | Calibration backup: one line per range, `range k0 t0_C alpha_perC date`. |
| `/nvd/log_NNNN.csv` | Run log: `ms,event,range,polarity,output,temp_C,factor,note`. It gets a row for every relay change, for every `SYST:LOG:MARK`, and a `TEMP` row every `SYST:LOG:INT` seconds (default 10; 0 turns it off). |

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
| `SYST:MODE?` | Full state: `BOARD=,STATE=,RANGE=,POL=,OUTP=,TEMP=,FACTOR=,CAL=,LOG=`. |
| `OUTP ON\|OFF` / `OUTP?` | INJECT / ISOLATE. `OUTP OFF` always pulses, even if already isolated. |
| `POL NORM\|INV` / `POL?` | Changes happen while isolated. |
| `RANG 1E-5\|1E-6\|1E-7\|NONE` / `RANG?` | Break-before-make, while isolated. |
| `SOUR:FACT?` | Calibrated factor of the active range, temperature-corrected when alpha ≠ 0. |
| `TEMP?` | TMP275, °C. |
| `CAL:RAT [range,]k` / `CAL:RAT? [range]` | k0. The range defaults to the active one. Values more than 10 % from nominal are rejected. |
| `CAL:TC [range,]alpha` / `CAL:TC?` | Ratio tempco, 1/°C. The default 0 means no correction. |
| `CAL:TREF [range,]T0` / `CAL:TREF?` | Reference temperature, °C. |
| `CAL:DATE [range,]"text"` / `CAL:DATE?` | Free text, e.g. an ISO 8601 date. |
| `CAL:NOM? [range]` | Nominal factor, 1/(R_H + 1). |
| `CAL:SAVE` | Writes the working calibration to NVS. The other `CAL:` edits change only the working copy (`SYST:MODE?` shows `CAL=UNSAVED`). |
| `CAL:DEF` | Resets the working copy to nominal. |
| `CAL:EXP` / `CAL:IMP` | Writes the working copy to `/nvd/cal.txt`, or reads it back from there. `CAL:SAVE` after an import. |
| `SYST:LOG ON\|OFF` / `SYST:LOG?` | Starts a new `/nvd/log_NNNN.csv`, or stops logging. |
| `SYST:LOG:FILE?` `SYST:LOG:MARK "text"` `SYST:LOG:INT s` | Log file name, a note row (e.g. `"A forward"` during an ABBA run), and the temperature-row interval. |
| `SYST:BOOT:SAFE ON\|OFF` | Whether boot pulses the safe state. Stored in NVS; the default is ON. |
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
2. **Power on.** The banner should read `STATE UNKNOWN`, and `MCP` and `TMP` should be green.
3. `DIAG:I2C?` should return `0x20,0x48`. `DIAG:PINS?` should now report `PULLUP` on both pins: those are R21/R22,
   because the module itself has none (measured on the module in hand: `IO18=NONE,IO27=NONE`).
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
