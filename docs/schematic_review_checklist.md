# Rev A schematic review checklist

Work through this before spending time on routing. Written against the schematics as of commit
`a713704`.

**Already machine-checked — do not spend review time re-tracing it:**

```
kicad-cli sch erc  --severity-all --exit-code-violations hardware/nanovolt-divider.kicad_sch
kicad-cli pcb drc  --severity-error --schematic-parity   hardware/nanovolt-divider.kicad_pcb
```

Both are clean (ERC 0, DRC 0 errors, 0 schematic-parity issues). Connectivity, floating pins,
duplicate references and footprint/symbol parity are therefore **not** what you are looking for.

This checklist targets the three things a tool cannot check:

1. **Intent** — the netlist is self-consistent, but is it the circuit you meant?
2. **Physical reality** — do the symbols and footprints match the parts on your bench?
3. **Margins and failure modes** — ratings, power-up states, what happens mid-transition.

Tick `[x]` as you go. Anything you cannot confirm, write the reason beside it rather than leaving
it blank.

---

## 0. Set-up

- [x] Open `hardware/nanovolt-divider.kicad_pro` in KiCad 10.
- [x] Have to hand: Panasonic TQ2 datasheet (ASCTB14E), Ohmite MOX-700 and Slim-Mox drawings,
      Vishay RS-2C drawing, and the physical ELEGOO display module.
- [x] Only `Default` remains in Board Setup -> Net Classes. The `HV` class and the 450 V
      clearance/creepage rules in `.kicad_dru` went with the HV divider — nothing on this board
      exceeds the source voltage any more.

---

## 1. Relay channel (`relay_channel.kicad_sch`, instantiated 5x)

One sheet drives all five relays, so an error here is an error five times over. Expected per
instance (K1 shown; K2-K5 identical):

| Net | Members (`DGND` and `+5V` rows show this instance's members only) |
|---|---|
| `/K1_SET` | `R1.1` `U1.21` |
| base node `Net-(Q1-B)` | `Q1.1(B)` `R1.2` `R2.1` |
| `DGND` | `Q1.2(E)` `R2.2` |
| `+5V` | `K1.1(S+)` `D1.1(K)` |
| coil drive `Net-(D1-A)` | `Q1.3(C)` `K1.5(S-)` `D1.2(A)` |

- [x] **Emitter to ground, collector to coil.** `Q1.2` is the emitter and sits on `DGND`; `Q1.3` is
      the collector and drives the coil. A low-side NPN switch, not the reverse.
- [x] **Coil polarity.** `+5V` on pin **1** (S+) with the transistor on pin **5** (S-) for the SET
      coil; `+5V` on pin **10** (R+) with the transistor on pin **6** (R-) for RESET.
- [x] **Flyback diode orientation.** `D1.1` is the **cathode** and goes to `+5V`; `D1.2` is the
      anode and goes to the collector. Reversed diodes short the 5 V rail through the coil.
- [x] **Contact mapping matches the datasheet.** Pole A: `3` COM, `2` NC, `4` NO. Pole B: `8` COM,
      `9` NC, `7` NO. Check against ASCTB14E "Schematic (bottom view), 2 coil latching" — note it
      is a **bottom** view.
- [x] **Latching, not monostable.** Confirm the part really is TQ2-**L2**-5V (two coils), not
      TQ2-5V. A single-coil part needs holding current, which this circuit never provides.
- [x] Base drive is (3.3 - 0.8 V) / 1 k = **2.5 mA**; the coil needs 40 mA, so beta >= 16. The
      MMBT2222A is comfortably above that. Confirm you are happy with the margin at low temperature.
- [x] `R2` (10 k) pulldown holds the driver off while the MCP23017 is in reset. Confirm that still
      holds given `U1` RESET is tied high through `R23` (see section 5).
- [x] Coil is 125 ohm / 40 mA at 5 V. Confirm the firmware contract: **pulse 10-20 ms, never hold.**

---

## 2. Range topology and divider maths

| Net | Members |
|---|---|
| `/SRC_P` | `K1.3` `K2.3` `K3.3` `K4.3` |
| `/R100K_IN` / `/R100K_OUT` | `K1.4`+`R31.1` / `K1.7`+`R31.2` |
| `/R1M_IN` / `/R1M_OUT` | `K2.4`+`R32.1` / `K2.7`+`R32.2` |
| `/R10M_IN` / `/R10M_OUT` | `K3.4`+`R33.1` / `K3.7`+`R33.2` |
| `/RANGE_BUS` | `K1.8` `K2.8` `K3.8` `K5.3` |

- [x] **Both poles switch each high leg:** `SRC_P -> A_COM -> A_NO -> R -> B_NO -> B_COM ->
      RANGE_BUS`. A deselected resistor is open at *both* ends, so it cannot load or leak into
      `RANGE_BUS`.
- [x] `A_NC` and `B_NC` on K1-K3 are no-connect (six nets, one pin each). Confirm you want nothing
      parked on the NC contacts.
- [x] Ratio is `k = R35 / (R_high + R35)` = 1/100001, 1/1000001, 1/10000001 — nominal 1e-5 / 1e-6 /
      1e-7. Confirm the **actual** ratios come from calibration, not these nominals.
- [x] **Only one range relay may be SET at a time.** Nothing in the hardware enforces this; two
      closed ranges put resistors in parallel and silently change the ratio. Confirm the firmware
      is the only interlock and that you accept that.
- [x] Leakage on the 1e-7 range: with a 10 M high leg, ~1 G of board leakage is a 1 % error on that
      range alone. Decide whether you want a guard ring or a conformal-coat step, or accept it. ACCEPT THE LEAKAGE.
- [x] Power in the high legs at your maximum source voltage — confirm it is far below the MOX-700
      and Slim-Mox ratings, and further below the level where self-heating shifts the ratio.

---

## 3. Polarity and inject semantics

| Net | Members |
|---|---|
| `/NORMAL_IN_P` | `J1.1` `K4.2(NC_A)` `K4.7(NO_B)` |
| `/NORMAL_IN_N` | `J2.1` `K4.4(NO_A)` `K4.9(NC_B)` |
| `/SRC_RTN` | `K4.8(COM_B)` `K5.8(COM_B)` |
| `/MEAS_NODE` | `K5.4(NO_A)` `R35.2` `J5.1` |
| `/ANALOG_RTN` | `K5.7(NO_B)` `R35.1` `J6.1` |

- [x] **K4 RESET = normal polarity.** RESET puts both poles on NC, so `SRC_P` <- `A_NC` <- `J1`
      (NORMAL IN +) and `SRC_RTN` <- `B_NC` <- `J2`. Walk it once and confirm SET swaps **both**
      legs, not just one.
- [x] **K5 RESET = ISOLATE, both legs.** Pole A breaks the high side (`RANGE_BUS` -> `MEAS_NODE`)
      and pole B breaks the return (`SRC_RTN` -> `ANALOG_RTN`). Both `A_NC` and `B_NC` are
      no-connect, so in
      ISOLATE the source is fully detached from the measurement node — its output capacitance and any
      leakage to earth included. Confirm both halves switch together and that you want no return
      path at all in ISOLATE.
- [x] Confirm nothing else quietly bridges the source to `ANALOG_RTN` while K5 is RESET — the whole
      point of breaking the return is lost if the DMM or the source chassis provides that path.
- [x] Confirm the intended truth table matches `README.md`, and that the firmware state machine will
      be written against these net names rather than "coil 1 / coil 2".

---

## 4. Measurement node and thermal EMF

| Net | Members |
|---|---|
| `/MEAS_NODE` | `J5.1` `K5.4` `R35.2` |
| `/ANALOG_RTN` | `J6.1` `K5.7` `R35.1` |

- [x] **Work out where thermal EMF actually matters.** Current flows source -> high leg -> `K5`
      pole A -> `R35` -> `K5` pole B -> source, so EMF in the relay *contacts* sits in the drive
      loop and is divided by `k` along with the source. The **undivided** path is only
      `J5 -> R35 -> J6`. Confirm that reasoning, then confirm those three parts and the copper
      between them are the only place low-thermal construction is required.
- [x] `J5`/`J6` tap `R35`'s own terminals directly. Confirm the Kelvin connection is where you
      want it.
- [x] Nothing switches below the measurement node. Confirm no relay, jumper or test point has crept
      into `MEAS_NODE` / `ANALOG_RTN`.
- [x] `R35` is a 2.5 W part running at microwatts. Confirm you chose it for stability and derating,
      and check its **thermal EMF per degree C** against your target resolution.
- [x] `U2` (TMP275) is thermally coupled to `R35` but electrically on `DGND`/`+3V3`. Confirm there
      is no galvanic path from the sensor into the analog return. It sits on the 1 ohm island above
      `R35` rather than over the resistor body - a SOIC-8 does not fit in that gap. Confirm the
      island alone couples it closely enough for the ratio correction you intend.

---

## 5. Control section

| Net | Members |
|---|---|
| `+3V3` | `C1.1` `C2.1` `C4.1` `J8.4` `R21.1` `R22.1` `R23.1` `U1.9` `U2.8` |
| `DGND` | 32 pins, incl. `U1.10` `U1.15` `U1.16` `U1.17` `U2.4` `U2.5` `U2.6` `U2.7` |
| `/CONTROL/SCL` | `J8.2` `R22.2` `U1.12` `U2.2` |
| `/CONTROL/SDA` | `J8.3` `R21.2` `U1.13` `U2.1` |

- [ ] **MCP23017 address.** `A0`/`A1`/`A2` (15/16/17) all on `DGND` -> **0x20**. Confirm no clash
      with anything else on the bus.
- [ ] **TMP275 address.** `A2`/`A1`/`A0` (pins 5/6/7) all on `DGND` -> **0x48**. Confirm. This is
      the same address the TMP117 had, so no firmware change follows from the swap - but the
      register map and resolution do differ (12-bit, 0.0625 C/LSB, not TMP117-compatible).
- [ ] `U1.18` (RESET) is pulled to `+3V3` through `R23` (10 k), active-low, so the expander runs.
      Confirm you do not want the ESP32 driving it instead, and that the 10 k pulldown on every
      driver base holds the relays quiet during the power-up window before `U1` is configured.
- [ ] GPIO to coil mapping: `GPB0..GPB7` = K4_SET, K4_RESET, K1_SET, K1_RESET, K2_SET, K2_RESET,
      K3_SET, K3_RESET; `GPA0` = K5_RESET, `GPA1` = K5_SET; `GPA2..GPA7` spare and no-connect. The
      order follows the board (GPB0..7 face the driver columns in this order), not the relay
      numbering. Confirm this is what the firmware will assume. `GPA7`/`GPB7` are output-only on
      current silicon; every coil line is an output.
- [ ] Per-pin draw is 2.5 mA against a 25 mA limit, and only one coil is pulsed at a time. Confirm
      nothing in the firmware can pulse two at once.
- [ ] I2C pull-ups are 4.7 k to 3.3 V (~0.7 mA sink). The bus is SCL = IO18, SDA = IO27, both on
      the module's SPI connector (the module in hand has no IO22). Confirm the display module does
      **not** also fit pull-ups on IO18/IO27. IO18 doubles as the microSD SCK on the standard CYD,
      so check the SD slot in particular: doubled-up pull-ups over-stiffen the bus.

---

## 6. Power

- [ ] `+5V` comes from the display module's 5V pin (UART / power connector, landed on `J7.3`) and feeds only the
      ten relay coils.
      Confirm the module regulator and the USB supply tolerate a 40 mA, 10-20 ms pulse.
- [ ] `+3V3` comes from the module LDO (3V3 connector, landed on `J8.4`) and feeds `U1`, `U2` and the pull-ups. Confirm the
      LDO has headroom for that on top of the display.
- [ ] Bulk `C3` 22 uF on +5V and `C4` 22 uF on +3V3; decoupling `C1` 100 n at `U1`, `C2` 100 n at
      `U2`. Confirm 22 uF keeps the 5 V rail from sagging during a coil pulse.
- [ ] `DGND` is a distinct global net from the analog return. Confirm `SRC_RTN` / `ANALOG_RTN`
      genuinely float and are never bonded to `DGND` anywhere — including through the DMM.

---

## 7. Physical reality — the part a tool cannot check

- [x] **Display module connector pinout.** The Rev A pads assumed P1 = TX/RX/VIN/GND and
      CN1 = GND/IO22/IO27/3V3. The module in hand (Cheap Yellow Display) differs: UART / power =
      RXD, TXD, GND, 5V; 3V3 = 3.3V, IO35, nc, GND; SPI = IO23, IO19, IO18, IO27. The schematic
      now follows the module in hand; the board does not change. See README "Display harness".
- [ ] **Continuity before soldering.** Buzz each pigtail conductor from module pin to wire end and
      label it. Land by signal name: the `J7` silk numbers are reversed against the module
      (module pin 3 is GND, but pad `3` is `+5V`), and the `J8` "CN1" silk no longer names a
      single connector. The harness is **soldered** at the board end, so there is no keyed housing,
      and nothing but this check stands between a mis-landed wire and a reversed 5 V supply.
- [ ] **Harness conductor count.** Only the six live conductors have pads: `J7` = 5V (pad 3) and
      GND (pad 4) from the UART / power connector; `J8` = GND (pad 1) and 3.3V (pad 4) from the 3V3
      connector, IO18 / SCL (pad 2) and IO27 / SDA (pad 3) from the SPI connector. Confirm that the
      cut conductors (RXD, TXD, IO35, the nc pin, IO23 and IO19) are snipped and insulated at the
      pigtail, not left bare near the board.
- [ ] **Both GND wires are run.** They are one net, but they are not redundant: the UART / power
      connector's ground (`J7`) returns the pulsed coil current (2 × 40 mA), and the 3V3
      connector's (`J8`) serves I2C. Collapsing them to one wire pushes coil pulse current through
      the I2C return. Confirm that two separate conductors land.
- [ ] **Pigtail gauge vs. pad drill.** Pads are 0.8 mm drill / 1.6 mm pad, sized for 28–24 AWG
      ribbon. Offer a real pigtail up to a 1:1 plot before ordering.
- [ ] **Strain relief at the board end.** The board no longer has a connector housing taking the
      cable load, and 28 AWG conductors fatigue. Decide how the harness is anchored (tie-down,
      adhesive, or a service loop) before the board is fixed in the enclosure.
- [ ] **Custom footprint pad numbering** against the physical parts: MOX-700 (`R31`, `R32`),
      Slim-Mox SM102 (`R33`), RS-2C (`R35`). The TQ2 relay footprint is already checked
      (pads 1-5 / 6-10 in two rows at 2.54 mm, 7.62 mm apart, DIP order with 1 opposite 10).
- [ ] **`J_ESP32_P1/CN1_WirePads`** pad numbering: 2 and 4 pads respectively, numbered with
      the module's pin numbers (`J7` reads 3, 4 — it has no pads 1/2). Silk carries the module
      connector name (`P1`/`CN1`) and the pin numbers; the refdes is on F.Fab because the two groups
      are stacked with only one usable silk line each. *Rev A as built:* that silk follows the
      assumed pinout, not the module in hand. Treat it as a pad locator only, and land wires by
      signal name.
- [ ] `U2` is a **SOIC-8 at 1.27 mm pitch** (`TMP275AIDR`), chosen so the board can be
      hand-soldered; it replaced a DSBGA-6 TMP117 and the 0.1 mm intra-footprint DRC exception went
      with it. Confirm the +/-0.5 C absolute accuracy and 0.0625 C resolution are enough for the
      ratio correction - the TMP117 gave +/-0.1 C and 0.0078 C.

---

## 8. Failure modes to think through

- [ ] **Power-up.** Latching relays hold their last state through a power cycle. What does the
      instrument do when it wakes in an unknown relay state — read back, or force a known state?
      Nothing reads contact position today.
- [ ] **Brownout mid-pulse.** A coil pulse interrupted part-way can leave a latching relay
      half-transferred. Decide whether that is tolerable or needs a re-assert on boot.
- [ ] **MCP23017 reset during operation.** All GPIOs go high-Z, the 10 k pulldowns hold the drivers
      off, and the relays keep their state. Confirm that is safe, not merely quiet.

---

## Sign-off

| Section | Reviewed | Notes / changes needed |
|---|---|---|
| 1 Relay channel | | |
| 2 Range topology | | |
| 3 Polarity / inject | | |
| 4 Measurement node | | |
| 5 Control | | |
| 6 Power | | |
| 7 Physical reality | | |
| 8 Failure modes | | |

Re-run ERC and DRC after any change.
