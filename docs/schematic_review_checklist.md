# Rev0 schematic review checklist

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

- [ ] Open `hardware/nanovolt-divider.kicad_pro` in KiCad 10.
- [ ] Confirm Board Setup -> Net Classes lists **`HV`** alongside `Default`, with patterns
      `/HV_IN_P` and `/HV_DIV`. *(This has silently vanished twice. If it is missing, every 450 V
      rule in `.kicad_dru` matches nothing and DRC still reports "0 violations".)*
- [ ] Have to hand: Panasonic TQ2 datasheet (ASCTB14E), Ohmite MOX-700 and Slim-Mox drawings,
      Vishay RS-2C drawing, and the physical ELEGOO display module.

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

- [ ] **Emitter to ground, collector to coil.** `Q1.2` is the emitter and sits on `DGND`; `Q1.3` is
      the collector and drives the coil. A low-side NPN switch, not the reverse.
- [ ] **Coil polarity.** `+5V` on pin **1** (S+) with the transistor on pin **5** (S-) for the SET
      coil; `+5V` on pin **10** (R+) with the transistor on pin **6** (R-) for RESET.
- [ ] **Flyback diode orientation.** `D1.1` is the **cathode** and goes to `+5V`; `D1.2` is the
      anode and goes to the collector. Reversed diodes short the 5 V rail through the coil.
- [ ] **Contact mapping matches the datasheet.** Pole A: `3` COM, `2` NC, `4` NO. Pole B: `8` COM,
      `9` NC, `7` NO. Check against ASCTB14E "Schematic (bottom view), 2 coil latching" — note it
      is a **bottom** view.
- [ ] **Latching, not monostable.** Confirm the part really is TQ2-**L2**-5V (two coils), not
      TQ2-5V. A single-coil part needs holding current, which this circuit never provides.
- [ ] Base drive is (3.3 - 0.8 V) / 1 k = **2.5 mA**; the coil needs 40 mA, so beta >= 16. The
      MMBT2222A is comfortably above that. Confirm you are happy with the margin at low temperature.
- [ ] `R2` (10 k) pulldown holds the driver off while the MCP23017 is in reset. Confirm that still
      holds given `U1` RESET is tied high through `R23` (see section 6).
- [ ] Coil is 125 ohm / 40 mA at 5 V. Confirm the firmware contract: **pulse 10-20 ms, never hold.**

---

## 2. Range topology and divider maths

| Net | Members |
|---|---|
| `/SRC_P` | `K1.3` `K2.3` `K3.3` `K4.3` |
| `/R100K_IN` / `/R100K_OUT` | `K1.4`+`R31.1` / `K1.7`+`R31.2` |
| `/R1M_IN` / `/R1M_OUT` | `K2.4`+`R32.1` / `K2.7`+`R32.2` |
| `/R10M_IN` / `/R10M_OUT` | `K3.4`+`R33.1` / `K3.7`+`R33.2` |
| `/RANGE_BUS` | `K1.8` `K2.8` `K3.8` `K5.3` |

- [ ] **Both poles switch each high leg:** `SRC_P -> A_COM -> A_NO -> R -> B_NO -> B_COM ->
      RANGE_BUS`. A deselected resistor is open at *both* ends, so it cannot load or leak into
      `RANGE_BUS`.
- [ ] `A_NC` and `B_NC` on K1-K3 are no-connect (six nets, one pin each). Confirm you want nothing
      parked on the NC contacts.
- [ ] Ratio is `k = R35 / (R_high + R35)` = 1/100001, 1/1000001, 1/10000001 — nominal 1e-5 / 1e-6 /
      1e-7. Confirm the **actual** ratios come from calibration, not these nominals.
- [ ] **Only one range relay may be SET at a time.** Nothing in the hardware enforces this; two
      closed ranges put resistors in parallel and silently change the ratio. Confirm the firmware
      is the only interlock and that you accept that.
- [ ] Leakage on the 1e-7 range: with a 10 M high leg, ~1 G of board leakage is a 1 % error on that
      range alone. Decide whether you want a guard ring or a conformal-coat step, or accept it.
- [ ] Power in the high legs at your maximum source voltage — confirm it is far below the MOX-700
      and Slim-Mox ratings, and further below the level where self-heating shifts the ratio.

---

## 3. Polarity and inject semantics

| Net | Members |
|---|---|
| `/NORMAL_IN_P` | `J1.1` `K4.2(NC_A)` `K4.7(NO_B)` |
| `/NORMAL_IN_N` | `J2.1` `K4.4(NO_A)` `K4.9(NC_B)` |
| `/SRC_RTN` | `K4.8(COM_B)` `SW1.4` |
| `/INJ_NODE` | `K5.4(NO_A)` `SW1.1` |

- [ ] **K4 RESET = normal polarity.** RESET puts both poles on NC, so `SRC_P` <- `A_NC` <- `J1`
      (NORMAL IN +) and `SRC_RTN` <- `B_NC` <- `J2`. Walk it once and confirm SET swaps **both**
      legs, not just one.
- [ ] **K5 RESET = ISOLATE.** RESET puts pole A on `A_NC`, a no-connect, so `RANGE_BUS` is open and
      the 1 ohm / DMM path is untouched. SET connects `RANGE_BUS` to `INJ_NODE`.
- [ ] K5 pole B (`7`, `8`, `9`) is entirely unused. Confirm you do not want it breaking the return
      leg too — today the return stays permanently connected.
- [ ] Confirm the intended truth table matches `README.md`, and that the firmware state machine will
      be written against these net names rather than "coil 1 / coil 2".

---

## 4. Measurement node and thermal EMF

| Net | Members |
|---|---|
| `/MEAS_NODE` | `J5.1` `R35.2` `SW1.2` |
| `/ANALOG_RTN` | `J6.1` `R35.1` `SW1.5` |

- [ ] **Work out where thermal EMF actually matters.** Current flows source -> high leg -> `SW1`
      pole 1 -> `R35` -> `SW1` pole 2 -> source, so EMF in the relay and switch *contacts* sits in
      the drive loop and is divided by `k` along with the source. The **undivided** path is only
      `J5 -> R35 -> J6`. Confirm that reasoning, then confirm those three parts and the copper
      between them are the only place low-thermal construction is required.
- [ ] `J5`/`J6` tap `R35`'s own terminals rather than sharing the `SW1` pads. Confirm the Kelvin
      connection is where you want it.
- [ ] Nothing switches below the measurement node. Confirm no relay, jumper or test point has crept
      into `MEAS_NODE` / `ANALOG_RTN`.
- [ ] `R35` is a 2.5 W part running at microwatts. Confirm you chose it for stability and derating,
      and check its **thermal EMF per degree C** against your target resolution.
- [ ] `U2` (TMP117) is thermally coupled to `R35` but electrically on `DGND`/`+3V3`. Confirm there
      is no galvanic path from the sensor into the analog return.

---

## 5. HV path (450 VDC service)

| Net | Members | Netclass |
|---|---|---|
| `/HV_IN_P` | `J3.1` `R34.1` | HV |
| `/HV_DIV` | `R34.2` `SW1.3` | HV |

- [ ] `R34` (10 M Slim-Mox) at 450 V draws **45 uA** and dissipates **20 mW** — far inside the 1 W
      rating, and the SM102 5 kV rating covers the standoff. Confirm both numbers.
- [ ] Output at 450 V is 45 uA x 1 ohm = **45 uV**. Confirm that is the range you expect.
- [ ] **`HV_DIV` floats to the full 450 V** when the toggle is in NORMAL and the HV supply is still
      connected. That is why it is on the HV netclass despite sitting at microvolts in use. Confirm
      the reasoning.
- [ ] **HV IN- has no board connection.** It is wired panel-to-panel, HV IN- jack -> `SW1` pole 2 HV
      lug (lug 6). Confirm that is what you want and that the panel wire is rated and routed for it.
- [ ] HV netclass patterns are the two net names spelled out, **never `HV*`** — a wildcard would
      sweep in `HV_SENSE`, a 3.3 V logic line. Confirm both patterns are present.
- [ ] **Prove the rules bite** rather than trusting a clean DRC: drag an HV pad within 3 mm of a
      neighbour and confirm `Rule: HV clearance` / `HV creepage` appear. Undo afterwards.
- [ ] Shrouded safety banana jacks for HV IN — still to be selected.

---

## 6. Control section

| Net | Members |
|---|---|
| `+3V3` | `C1.1` `C2.1` `C4.1` `J8.4` `R21.1` `R22.1` `R23.1` `R24.2` `U1.9` `U2.B1` |
| `DGND` | 35 pins, incl. `U1.10` `U1.15` `U1.16` `U1.17` `U2.B2` `U2.C1` |
| `/CONTROL/SCL` | `J8.2` `R22.2` `U1.12` `U2.A2` |
| `/CONTROL/SDA` | `J8.3` `R21.2` `U1.13` `U2.A1` |
| `/HV_SENSE` | `C5.1` `J9.2` `R25.1` `SW1.8` |
| `/MODE_SW_HV` | `R24.1` `SW1.9` |

- [ ] **MCP23017 address.** `A0`/`A1`/`A2` (15/16/17) all on `DGND` -> **0x20**. Confirm no clash
      with anything else on the bus.
- [ ] **TMP117 address.** `ADD0` (`C1`) on `DGND` -> **0x48**. Confirm.
- [ ] `U1.18` (RESET) is pulled to `+3V3` through `R23` (10 k), active-low, so the expander runs.
      Confirm you do not want the ESP32 driving it instead, and that the 10 k pulldown on every
      driver base holds the relays quiet during the power-up window before `U1` is configured.
- [ ] GPIO to coil mapping: `GPA0..GPA7` = K1_SET, K1_RESET, K2_SET, K2_RESET, K3_SET, K3_RESET,
      K4_SET, K4_RESET; `GPB0`/`GPB1` = K5_SET/K5_RESET; `GPB2..GPB7` spare and no-connect. Confirm
      this is what the firmware will assume.
- [ ] Per-pin draw is 2.5 mA against a 25 mA limit, and only one coil is pulsed at a time. Confirm
      nothing in the firmware can pulse two at once.
- [ ] I2C pull-ups are 4.7 k to 3.3 V (~0.7 mA sink). Confirm the display module does **not** also
      fit pull-ups on IO22/IO27 — doubled-up pull-ups over-stiffen the bus.
- [ ] **Mode sense polarity.** HV throw -> `R24` (10 k) -> `+3V3`; `R25` (100 k) to `DGND` always.
      So `HV_SENSE` **high (~3.0 V) = HV**, low = NORMAL. The NORMAL throw has no resistor and no
      pad. Confirm 3.0 V clears IO35's input-high threshold.
- [ ] Decide the mid-transition behaviour you want: with a break-before-make switch `SW1.8` floats
      and `R25` pulls `HV_SENSE` low, so firmware momentarily reads **NORMAL**. `C5` (10 nF x 100 k
      = 1 ms) filters the harness but does not change that. Decide whether to debounce in firmware.
- [ ] IO35 is **input-only with no internal pull** on ESP32. Confirm `R25` is genuinely the only
      thing defining the level.

---

## 7. Power

- [ ] `+5V` comes from the display module USB `VIN` (`J7.3`) and feeds only the ten relay coils.
      Confirm the module regulator and the USB supply tolerate a 40 mA, 10-20 ms pulse.
- [ ] `+3V3` comes from the module LDO (`J8.4`) and feeds `U1`, `U2` and the pull-ups. Confirm the
      LDO has headroom for that on top of the display.
- [ ] Bulk `C3` 22 uF on +5V and `C4` 22 uF on +3V3; decoupling `C1` 100 n at `U1`, `C2` 100 n at
      `U2`. Confirm 22 uF keeps the 5 V rail from sagging during a coil pulse.
- [ ] `DGND` is a distinct global net from the analog return. Confirm `SRC_RTN` / `ANALOG_RTN`
      genuinely float and are never bonded to `DGND` anywhere — including through the DMM.

---

## 8. Physical reality — the part a tool cannot check

- [ ] **ELEGOO module connector pinout.** `J7`/`J8`/`J9` assume P1 = TX/RX/VIN/GND,
      CN1 = GND/IO22/IO27/3V3, P3 = GND/IO35/IO22/IO21. **These are unverified.** Do a continuity
      check on the board in hand — CYD revisions vary. The symbols carry the module pin names so a
      mismatch is visible; correct them if wrong.
- [ ] **3PDT lever-to-throw mapping.** Which lug row the lever selects as NORMAL depends on the
      part, which has not been chosen. Confirm before wiring the panel; `README.md` records the
      assumed mapping.
- [ ] **3PDT selection.** Break-before-make, 450 VDC rated, with pole-to-pole isolation good enough
      that pole 3 (3.3 V `HV_SENSE`) can sit beside a 450 V pole.
- [ ] **Custom footprint pad numbering** against the physical parts: MOX-700 (`R31`, `R32`),
      Slim-Mox SM102 (`R33`, `R34`), RS-2C (`R35`). The TQ2 relay footprint is already checked
      (pads 1-5 / 6-10 in two rows at 2.54 mm, 7.62 mm apart, DIP order with 1 opposite 10).
- [ ] **`SW_3PDT_WirePads_Split`** has seven pads, not nine. Confirm the two absent lugs (6 and 7)
      are the ones you intend to wire panel-to-panel and leave unused, and that the pad-to-lug
      silkscreen labelling is right.
- [ ] TMP117 is a **DSBGA-6 at 0.4 mm pitch**. Confirm you can assemble it, and that the relaxed
      0.1 mm intra-footprint DRC exception in `.kicad_dru` is acceptable to your fab.

---

## 9. Failure modes to think through

- [ ] **Power-up.** Latching relays hold their last state through a power cycle. What does the
      instrument do when it wakes in an unknown relay state — read back, or force a known state?
      Nothing reads contact position today.
- [ ] **Brownout mid-pulse.** A coil pulse interrupted part-way can leave a latching relay
      half-transferred. Decide whether that is tolerable or needs a re-assert on boot.
- [ ] **MCP23017 reset during operation.** All GPIOs go high-Z, the 10 k pulldowns hold the drivers
      off, and the relays keep their state. Confirm that is safe, not merely quiet.
- [ ] **Switch in transit.** HV and normal paths are both open briefly. Confirm nothing is damaged
      by the open circuit and that the DMM reading is simply discarded.
- [ ] **HV connected while in NORMAL.** `HV_DIV` floats to 450 V against a board otherwise sitting
      at microvolts. Confirm the creepage and the operator sequence you intend to document.

---

## Sign-off

| Section | Reviewed | Notes / changes needed |
|---|---|---|
| 1 Relay channel | | |
| 2 Range topology | | |
| 3 Polarity / inject | | |
| 4 Measurement node | | |
| 5 HV path | | |
| 6 Control | | |
| 7 Power | | |
| 8 Physical reality | | |
| 9 Failure modes | | |

Re-run ERC and DRC after any change, and re-confirm the `HV` netclass survived.
