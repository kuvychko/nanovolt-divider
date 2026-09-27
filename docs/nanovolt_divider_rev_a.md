# Programmable Nanovolt Divider / Precision Attenuator
## Rev A Design Specification

**Revision:** Rev A  
**Date:** 2026-09-06  
**Status:** Rev A boards ordered from OSH Park 2026-09-11 and received (fab files in `hardware/fab/`); enclosure in design (`enclosure/`)  
**Primary use:** calibrated low-level DC injection and sub-LSB metrology with an external precision DMM  
**Scope note:** a second, passive path for measuring a ~450 V Geiger-counter supply was specified for Rev A and then removed - see §4.3.

---

## 1. Problem statement

The goal is to build a compact bench instrument that converts an ordinary, controllable DC source into a stable and calibrated nanovolt-to-microvolt signal by **passive resistive attenuation**, rather than attempting to synthesize nanovolts directly.

The motivating experiment used a LAN-controlled bench power supply, a simple ~1:10^6 divider built from inexpensive resistors, an HP 3478A 5½-digit DMM on its 30 mV range, and ABBA modulation/averaging. That setup demonstrated reliable recovery of signals well below the DMM's 100 nV quantization count, including signals around 20 nV.

The Rev A instrument should preserve the simplicity of the successful experiment:

> **A conventional voltage source + passive precision attenuation + reversal + true zero + calibration + averaging.**

The precision signal path should remain as passive and electrically quiet as practical.

---

## 2. Planned capabilities

1. **Three programmable normal-input attenuation ranges**
   - approximately `1e-5`
   - approximately `1e-6`
   - approximately `1e-7`

2. **Shared 1 Ω low-leg resistor**
   - permanent part of the DMM measurement path
   - never switched out of the low-voltage path
   - serves as the "heart" of the divider

3. **Programmable polarity reversal**
   - implemented with a latching relay
   - reversal occurs upstream of the precision divider

4. **Programmable injection / isolation**
   - implemented with a latching relay upstream of the 1 Ω resistor
   - `INJECT`: selected source drives current through the 1 Ω resistor
   - `ISOLATE`: high-side source is disconnected while the DMM remains connected across the same 1 Ω resistor
   - provides a physically meaningful zero without perturbing the low-voltage measurement path

5. **~~Dedicated high-voltage input~~** — *removed, see §4.3*

6. **Temperature monitoring**
   - one TMP275 located adjacent to the 1 Ω resistor
   - used to characterize thermal behavior and support optional ratio correction
   - SOIC-8, because the board is hand-soldered; the TMP117 it replaced is DSBGA-6 only
   - ±0.5 °C / 12-bit rather than the TMP117's ±0.1 °C / 16-bit. The correction is driven by the
     *change* in temperature since calibration, so short-term repeatability matters here and
     absolute accuracy does not.

7. **Stored calibration**
   - calibrated divider multiplier for each normal range
   - reference temperature
   - optional measured temperature coefficient for each range
   - calibration metadata stored in nonvolatile memory

8. **Local user interface**
   - integrated 2.8" ESP32 + 320×240 resistive-touch TFT module
   - touchscreen control of:
     - range
     - polarity
     - injection/isolation
   - display shows active mode, range, polarity, output state, calibrated factor, temperature, and communications status

9. **Remote control**
   - SCPI-style command interface over USB serial, to the Raspberry Pi metrology hub
   - ~~SCPI-style command interface over Wi-Fi/TCP~~: *dropped. With the Pi on USB, a 2.4 GHz radio a few
     centimetres from a nanovolt path buys nothing, and it would be a second control route the hub cannot see. The
     firmware never initialises the radio.*

---

## 3. Rev A non-goals

Rev A intentionally avoids becoming a general-purpose precision source or full HV instrument.

Not planned for Rev A:

- direct nanovolt generation with DACs/op-amps
- precision voltage reference
- closed-loop output regulation
- internal DMM/ADC as the metrology reference
- automatic PSU control inside the instrument
- sub-nanovolt absolute-accuracy claims
- complex active analog circuitry in the precision signal path

The external PSU remains the voltage source; the external DMM remains the measurement reference.

---

## 4. Electrical architecture

### 4.1 Normal-input signal path

The normal input uses five identical dual-coil latching relay channels:

| Relay | Function |
|---|---|
| K1 | Select 100 kΩ high leg (`~1e-5`) |
| K2 | Select 1 MΩ high leg (`~1e-6`) |
| K3 | Select 10 MΩ high leg (`~1e-7`) |
| K4 | Polarity reversal |
| K5 | Injection enable / isolation |

Only one range relay is active at a time.

Nominal divider factors are:

\[
k = \frac{R_L}{R_H + R_L}
\]

with \(R_L = 1\ \Omega\).

| Range | High leg | Nominal factor |
|---|---:|---:|
| `1e-5` | 100 kΩ | 9.999900001e-6 |
| `1e-6` | 1 MΩ | 9.999990000e-7 |
| `1e-7` | 10 MΩ | 9.999999000e-8 |

Actual factors will be determined by calibration and stored in firmware.

### 4.2 Zero / isolation philosophy

The 1 Ω low-leg resistor is **never shorted and never removed from the DMM path**.

In `INJECT` mode:

```text
selected high leg -> injection node -> 1 Ω -> analog return
                                  |           |
                                DMM HI      DMM LO
```

In `ISOLATE` mode:

```text
selected high leg -> OPEN

                    injection node -> 1 Ω -> analog return
                         |                    |
                       DMM HI               DMM LO
```

This preserves the same 1 Ω resistor, PCB traces, solder joints, output connector, cable, and DMM terminals. Only the intentionally injected current is removed.

### 4.3 High-voltage path — removed

Rev A originally carried a second passive input for a ~450 V Geiger-counter supply: a dedicated
10 MΩ high leg into the **shared** 1 Ω low leg, selected by a physical 3PDT NORMAL/HV toggle. It
has been removed. The reasoning is recorded here because the numbers are the useful part:

- Sharing the 1 Ω leg capped the ratio. At 10 MΩ the divider drew 45 µA and delivered **45 µV**
  out; more output meant a smaller high leg, and 1 MΩ draws 450 µA where 10 MΩ draws 45 µA.
- A Geiger supply is built to source microamps into a tube that draws almost none, so its output
  impedance is high — often set by a deliberate series anode resistor. Against a 1 MΩ source
  impedance a 10 MΩ divider already reads 9 % low, and a 1 MΩ divider reads 50 % low. That error
  tracks the supply's operating point, so calibration cannot remove it.
- The HV path had **no polarity reversal** — K4 serves the NORMAL input only — so thermal EMF and
  DMM offset could not be nulled by ABBA the way they are on the normal ranges. More output was
  exactly what that path needed, and the shared 1 Ω leg was the one thing that would not give it.

A dedicated fixed divider is free of all three constraints, because it chooses its own low leg. The
450 V measurement therefore moves out of this instrument, and Rev A stays single-purpose.

Removed with it: `R34`, `J3`, `SW1` and the panel toggle, `R24`/`R25`/`C5`, the `J9`/P3 harness,
the `HV` netclass and its clearance/creepage rules, and 11 mm of board height. `SW1`'s two analog
poles were only ever selecting between the normal path and the HV path, so with the HV path gone
both collapse to plain nets: K5's `A_NO` lands directly on `MEAS_NODE` and its `B_NO` directly on
`ANALOG_RTN`. The ISOLATE function is untouched — K5 was always what performed it.

---

## 5. System block diagram

```mermaid
flowchart LR
    subgraph CTRL["Front / Control Section"]
        UI["2.8 in ESP32 Touch TFT"]
        IO["MCP23017\nI²C GPIO expander"]
        T["TMP275\ntemperature sensor"]
        UI <-->|I²C / control| IO
        UI <-->|I²C| T
    end

    subgraph NORMAL["Normal Precision Divider"]
        NIN["NORMAL IN\n+ / -"]
        POL["K4\nPOLARITY"]
        RSEL["K1 / K2 / K3\nRange select"]
        RH["100 kΩ / 1 MΩ / 10 MΩ"]
        INJ["K5\nINJECT / ISOLATE"]
        NIN --> POL --> RSEL --> RH --> INJ
    end

    NODE["Measurement node"]
    RL["1 Ω precision low leg"]
    OUT["DIVIDER OUT\n+ / -"]

    NORMAL --> NODE --> RL --> OUT

    IO -. "10 relay-coil control lines" .-> NORMAL
    T -. "thermal proximity only; no analog connection" .-> RL
```


---

## 6. Control architecture

### 6.1 Controller

Rev A uses an integrated **2.8" ESP32 touch-display module** rather than a separate Arduino + TFT.

Expected module characteristics:

- ESP32 MCU
- Wi-Fi
- USB serial interface
- 320×240 ILI9341 TFT
- resistive touchscreen / XPT2046-type controller

The module in hand is a "Cheap Yellow Display" (ESP32-2432S028R family). Its three 4-pin
connectors are UART / power (RXD, TXD, GND, 5V), 3V3 (3.3V, IO35, nc, GND) and SPI (IO23 MOSI,
IO19 MISO, IO18 SCK, IO27 CS). The board takes 5 V and GND from the first, 3.3 V and GND from the
second, and the I²C bus from the third: **SDA = IO27, SCL = IO18**. The module has no IO22, and
IO35 is input-only. The pad-by-pad wiring is in the README, under "Display harness".

### 6.2 GPIO expansion

Five TQ2-L2 relays require ten coil-control outputs:

- 5 × SET
- 5 × RESET

An **MCP23017** I²C GPIO expander provides these outputs.

The ten MCP23017 outputs drive ten identical low-side transistor stages:

```text
MCP23017 GPIO
    |
   1 kΩ
    |
MMBT2222A base
    |
10 kΩ pulldown to DGND

relay coil -> MMBT2222A collector
MMBT2222A emitter -> DGND
1N4148W flyback diode across relay coil
```

The same I²C bus is used for the TMP275 (address 0x48, `A2`/`A1`/`A0` all on `DGND`).

### 6.3 Relay safety/state rules

1. Power-up into a deterministic safe state.
2. Establish `ISOLATE` before configuring other relay states.
3. Only one range relay may be active at a time.
4. Range changes use break-before-make.
5. Polarity changes occur while isolated.
6. Relay coils are pulsed only briefly; they are never continuously energized.

---

## 7. Mechanical / thermal architecture

The enclosure should have two physically distinct regions.

### Control / warm / noisy region

- ESP32 + touchscreen
- Wi-Fi antenna
- MCP23017
- relay-driver electronics
- USB/power wiring

### Precision / quiet region

- relay contacts
- precision high-leg resistors
- 1 Ω resistor
- TMP275
- output connector

A physical divider wall inside the enclosure is desirable for airflow isolation, thermal isolation, and wiring organization.

The enclosure should not be fully metallic because the ESP32 Wi-Fi antenna requires an RF-transparent path.
*(No longer binding: Wi-Fi was dropped, see §2 item 9.)* A plastic-bodied instrument enclosure with a machinable metal front panel is preferred.

### 1 Ω thermal region

The 1 Ω resistor should receive special layout treatment:

- located near the output connector,
- minimal low-level trace length,
- output/sense traces branch directly from the resistor terminals,
- TMP275 placed nearby,
- no relay coil or TFT/backlight heat nearby,
- optional PCB cutouts/slots to reduce thermal conduction from the rest of the board.

---

## 8. Calibration model

Each range stores a calibration record:

```text
RangeCalibration
    range_id
    nominal_factor
    calibrated_factor_at_Tref
    reference_temperature
    measured_ratio_tempco
    calibration_timestamp
```

Temperature correction, once characterized, may use:

\[
k(T) = k_0 \left[1 + \alpha(T - T_0)\right]
\]

Rev A firmware should support the field from the beginning but use **zero temperature correction until the coefficient is experimentally measured**.

**As built (firmware 0.2.0).** The record grew. It adds a quadratic term β, standard uncertainties for k0 and α, the
TMP275 span [Tmin, Tmax] it was measured over, and a provenance string:
k(T) = k0 [1 + α(T − T0) + β(T − T0)²], with T the TMP275 reading on the 1 Ω island. The instrument answers
"the ratio at this board temperature" directly (`CAL:FACT? <range>,<T>` → k, uncertainty, in-span flag). Every
saved calibration is appended to an audit trail on the SD card. How the record is measured is in
[calibration_protocol.md](calibration_protocol.md).

---

## 9. Planned SCPI interface

Exact command names may evolve, but Rev A should support these concepts:

```text
*IDN?
*RST?

:OUTP ON
:OUTP OFF
:OUTP?

:POL NORM
:POL INV
:POL?

:RANG 1E-5
:RANG 1E-6
:RANG 1E-7
:RANG?

:TEMP?

:CAL:RATIO?
:CAL:TC?
:CAL:TREF?

:SOUR:FACTOR?
:SYST:MODE?
```

USB serial and Wi-Fi/TCP should share the same parser and instrument state machine.

**As built.** All of the above exist, with `*RST` as a command (not a query) and `SOUR:FACT?` for the factor. The
additions are diagnostics, calibration records, file access to the SD card, and reset detection. The command
reference is `firmware/README.md`; the host-side contract is [bench_handoff.md](bench_handoff.md). There is no
Wi-Fi (§2).

---

## 10. KiCad schematic organization

The schematic should be created **top-down**.

Recommended hierarchy:

```text
nanovolt-divider.kicad_sch        # root / system architecture
|
+-- control.kicad_sch
|     ESP32/display interface
|     MCP23017
|     TMP275 interface
|     power/decoupling
|
+-- relay_channel.kicad_sch       # same file instantiated 5 times
      K1 RANGE_1E5
      K2 RANGE_1E6
      K3 RANGE_1E7
      K4 POLARITY
      K5 INJECT
```

The root sheet owns the actual metrology topology:

- NORMAL input
- 100 kΩ / 1 MΩ / 10 MΩ divider network
- 1 Ω low leg
- output terminals

`relay_channel.kicad_sch` should be generic and expose:

```text
SET
RESET

A_COM
A_NO
A_NC

B_COM
B_NO
B_NC
```

The same sheet is instantiated five times. KiCad's multi-channel/repeat-layout workflow can then duplicate the physical relay-driver layout after one channel is placed and routed.

---

## 11. BOM — Rev A

### 11.1 Precision / analog components

| Qty Rev A | Part | Mfr. part number | Function / notes | Status |
|---:|---|---|---|---|
| 1 | Vishay/Dale 1 Ω wirewound | `RS02C1R000FE70` | Shared low leg, 1%, 2.5 W, through-hole | **Purchased** |
| 1 | Ohmite 100 kΩ metal film | `MOX70031003BZE` | Normal `1e-5` range, 0.1%, 5 ppm/°C | **Purchased** |
| 1 | Ohmite 1 MΩ metal film | `MOX70031004BYE` | Normal `1e-6` range, 0.1%, 10 ppm/°C | **Purchased** |
| 1 | Ohmite 10 MΩ thick film | `SM102031005FE` | Normal `1e-7` range, 1% | **Purchased** |
| 5 | Panasonic latching relay | `TQ2-L2-5V-3` | K1–K5 | 1 purchased; **4 more required** |
| 1 | TI temperature sensor, SOIC-8 | `TMP275AIDR` | Temperature of 1 Ω region, I²C 0x48 | **To order** (the purchased `TMP117MAIYBGR` is DSBGA-6 and cannot be hand-soldered) |

### 11.2 Relay-driver / control-board components

| Qty Rev A | Part | Mfr. part number | Function / notes | Status |
|---:|---|---|---|---|
| 10 | NPN transistor, SOT-23 | `MMBT2222A` | Two low-side coil drivers per relay | **12 purchased** |
| 10 | Switching diode | `1N4148W` | Flyback diode across each relay coil | **12 purchased** |
| 10 | 1 kΩ resistor, 1206 | existing stock/library | Transistor base resistor | On hand / source TBD |
| 10 | 10 kΩ resistor, 1206 | existing stock/library | Base pulldown | On hand / source TBD |
| 1 | MCP23017 | TBD | I²C GPIO expander for relay controls | **To order** |
| 1 | Integrated 2.8" ESP32 touch TFT | "Cheap Yellow Display", ESP32-2432S028R family | UI, Wi-Fi, USB, controller | **On hand** |

### 11.3 Decoupling / power

| Qty Rev A | Part | Mfr. part number | Function / notes | Status |
|---:|---|---|---|---|
| as needed | 100 nF, 16 V, X7R, SMD | `SH31B104K160CT` | Local high-frequency decoupling | **20 purchased** |
| 2–3 | 22 µF, 1206 MLCC | `EMK316BB7226ML-T` | Local/bulk 5 V decoupling | **3 purchased** |
| 2 | I²C pull-up resistors, 1206 | TBD | SDA/SCL pull-ups if required | On hand / TBD |

### 11.4 Front panel / mechanical

| Qty | Item | Notes | Status |
|---:|---|---|---|
| 2 | Normal-input banana sockets | + / − | To select |
| 2 | Output banana sockets | + / − | To select |
| 1 | Enclosure | 3D-printed: front panel, back panel, base plate, PCB holder (SOLIDWORKS + 3MF in `enclosure/`) | In design (v0) |
| 1 | Internal compartment divider | Plastic / FR4 / 3D printed | To design |
| 1 | TFT mounting bezel | Optional 3D-printed bezel | To design |
| misc. | PCB standoffs, harnesses | Mechanical integration | TBD |
| 1 | Banana-jack nut wrench | 3D-printed tool (`enclosure/banana-plug-wrench-v0`) | In design (v0) |
| - | *(no board-side harness headers)* | Display-module pigtails solder straight to the `J7`/`J8` pads | n/a |

---

## 12. First Mouser order

The first Mouser order establishes the core passive-divider and relay-driver component set:

- 1 Ω low-leg resistor
- 100 kΩ, 1 MΩ, and 10 MΩ divider resistors
- 12 × MMBT2222A
- 12 × 1N4148W
- 20 × 100 nF X7R MLCCs
- 3 × 1206 bulk MLCCs
- 1 × TMP117 *(DSBGA-6, superseded - see 11.1)*
- 1 × TQ2-L2-5V-3 relay

Additional Rev A procurement is expected to include:

- four more TQ2-L2-5V-3 relays,
- one `TMP275AIDR` (SOIC-8) in place of the DSBGA-6 TMP117,
- MCP23017,
- banana sockets,
- enclosure/mechanical hardware.

---

## 13. Rev A design principles

1. **Do not synthesize nanovolts directly.** Generate ordinary voltages well and attenuate them.
2. **Keep the precision signal path passive.**
3. **Nothing switches below the 1 Ω measurement node.**
4. **A zero measurement should preserve the same low-voltage path.**
5. **Use latching relays so coil power and heating vanish during measurement.**
6. **Separate digital/warm electronics physically from the precision divider.**
7. **Calibrate actual ratios; do not depend on nominal resistor tolerance.**
8. **Measure temperature before attempting temperature correction.**
9. **Favor simple, inspectable circuitry over unnecessary analog sophistication.**
10. **Keep the instrument single-purpose.** A capability that has to share the 1 Ω low leg inherits
    its constraints; if those constraints make it a poor version of the thing, it belongs in its own
    box. This is what retired the 450 V path — see §4.3.

---

## 14. Immediate next steps

1. Create the KiCad project and project-local symbol/footprint libraries.
2. Draw the Rev A root-sheet architecture first.
3. Create the generic `relay_channel.kicad_sch` interface.
4. Instantiate the relay channel five times.
5. Implement and ERC-check one relay channel.
6. Build the control sheet around the ESP32 module, MCP23017, and TMP275.
7. Complete the precision signal path on the root sheet.
9. Assign real footprints from component datasheets.
10. Perform a schematic architecture/safety review before starting PCB placement.
