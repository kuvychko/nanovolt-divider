# Calibration protocol

How the divider's three ratios, and their temperature dependence, are measured, how well, and how the result is
written into the instrument. The protocol is designed here. It is run from the Raspberry Pi metrology hub by the
`bench-metrology` repo (see [bench_handoff.md](bench_handoff.md)).

Equipment: the UNI-T UDP3305S-E (CH1) as the source and the HP 3478A as the only meter. Temperature is the
divider's own TMP275, plus room temperature from warehouse-db for the PSU. There is no temperature chamber:
temperature varies only through the room's natural HVAC and diurnal cycling.

## 1. What is calibrated

Per range i ∈ {1E-5, 1E-6, 1E-7}, the firmware stores (`CAL:REC`):

```
k_i(T) = k0_i · [1 + α_i (T − T0) + β_i (T − T0)²]        valid for Tmin ≤ T ≤ Tmax
```

* **T is the TMP275 reading.** It is not room temperature, and it is not the resistor's own temperature. The sensor
  sits on the slotted 1 Ω island next to R35. That is the co-location the bench repo's uncertainty analysis says is
  the only real fix for its "unbounded" sensor-gain term, at least for the 1 Ω. The high legs are off the island, on
  the main board, so they see the same room through a different thermal path. Their lag relative to the TMP275 is
  fitted, not assumed zero (§6).
* **Decomposition.** k = R_L/(R_H + R_L), and R_L/R_H ≤ 1e-5, so to better than 0.1 ppm
  **α_i = α_L − α_H,i**. α_L, the 1 Ω's tempco, is common to all three ranges; α_H,i belongs to each high leg.
* **β** stays 0 unless the observed span resolves curvature. A 2–3 °C natural swing will not. **[Tmin, Tmax]** is the
  TMP275 span actually observed during the runs. Outside it, `CAL:FACT?` still answers but reports `in_span=0`.
* Stored with the record: `u_k0_ppm` and `u_alpha_ppm` (standard uncertainties, k = 1), a date, and a `source`
  string naming the bench run IDs.

**Targets.** k0 to about 1e-4 on 1E-5 and 1E-6, and about 1e-3 on 1E-7. α to a few ppm/°C on 1E-5 and 1E-6. These
are ambitious for this bench and more than the application needs: sub-100 nV injection, with amplitudes anchored on
in-run controls, where the PSU's own error at low setpoints (+15.9 % at 10 mV, Experiment 3) dominates. §7 states
what is actually achievable.

## 2. Principles carried over from bench-metrology

* **Modulate; use ABBA.** The meter's zero sits near −1.9 µV and wanders by hundreds of nV over minutes. Every
  output measurement here is the difference of polarity-reversed dwells ordered N-I-I-N. That cancels offset, thermal
  EMF and linear drift.
* **60 s dwells.** ADEV·√τ is flat below ~30 s, so 60 s is as good per unit time as longer dwells and keeps ABBA's
  linear-drift assumption honest.
* **Drop the settling samples.** In Experiment 3 the sample straddling a switch was garbage and the next was 2σ low.
  Drop the first 2 s of every dwell.
* **Switch in the divider, never at the source.** The PSU output stays on and constant for the whole of every run.
  Polarity is reversed by K4, which sits upstream of the high leg. Any thermal EMF of K4, K5 or the range-relay
  contacts is therefore in series with R_H and reaches the output divided by ~1/k. At 1E-5 a 1 µV contact EMF becomes
  10 pV. This is why reversal inside the divider is legitimate modulation, where switching the PSU's output relay
  was not.
* **Fixed meter ranges** for a whole run. **UTC timestamps** throughout. `SYST:TIME` is set on the divider at connect.
* **Every transition is recorded when it actually happened** (`schedule.jsonl`), and samples are joined to phases on
  that timestamp.

## 3. Setup

| | |
|---|---|
| Source | UDP3305S-E CH1 into NORMAL IN, set to V_cal, output on for the whole run. |
| V_cal | **20 V recommended.** It halves the statistical errors of 10 V (§7). The as-shipped OVP is 13 V: set OVP to 22 V on the front panel, and a driver ceiling of 20.5 V. 10 V also works, at twice the noise. |
| Current limit | 10 mA. The divider draws 200 µA at most (20 V into 100 kΩ). |
| Meter | HP 3478A, DC V, 5.5 digits, autozero on, fixed range: **30 V at the IN jacks** (Run P, anchors) or **30 mV at the OUT jacks** (Run R). |
| Divider | Connected to the Pi over USB. `SYST:TIME` set at connect. `SYST:BOOT:COUNT?` recorded at start and checked every cycle (bench_handoff.md, "Reset detection"). |
| Temperatures | `TEMP?` from the divider with every meter sample; room temperature joined afterwards from warehouse-db. |

Dissipation at 20 V: 4 mW in the 100 kΩ, 0.4 mW in the 1 MΩ, 40 µW in the 10 MΩ, and 40 nW in the 1 Ω. The
voltage check in §5 bounds any self-heating or voltage-coefficient effect instead of assuming it away.

## 4. The schedule (shared by Runs P and R)

One cycle, repeated for 72 h:

```
for range in 1E-5, 1E-6, 1E-7:
    RANG range; OUTP ON
    ABBA block: POL NORM 60 s, POL INV 60 s, POL INV 60 s, POL NORM 60 s
OUTP OFF: ISOLATE dwell 60 s                  (offset / leakage diagnostic)
```

A cycle takes 13 min, which gives about 330 blocks per range in 72 h. **Run P executes exactly the same schedule**,
even though the meter is not looking at the output then. That keeps the PSU's load pattern (200 / 20 / 2 µA / 0)
identical in both runs, so the PSU model built in P applies unchanged in R.

## 5. The runs

### Run P: PSU characterisation, 72 h

The meter is on the divider's **NORMAL IN jacks** (30 V range) while the schedule runs. It measures the voltage the
divider actually receives, lead drops included.

Output: a model V_in(t) = V0 · [1 + γ (T_room,lagged − T_ref) + δ·t], fitted with the bench repo's joint
`ThermalModel` and `thermal_lag`:
* γ is the PSU's tempco against room temperature;
* δ is its drift;
* there is also a fitted lag to the room sensor.

Also record the residual scatter. That is the PSU's short-term noise, which Run R inherits.

### Run R: ratio, 72 h

Move the meter leads from IN to OUT and set the 30 mV range; change nothing else. Run the same schedule.

**Vin anchors.** Measure IN on the 30 V range for 15 min immediately before Run R, and again immediately after it,
moving the leads by hand. The anchors pin the model's absolute level at both ends. The model then only has to
supply the temperature *shape*, which absorbs PSU aging and the meter-reference drift that Experiment 4 could not
assign.

Per block: signal S = (N₁ + N₂ − I₁ − I₂)/4. Then k_i(t) = S / V_in,model(t), fitted against TMP275 with a
first-order lag per range. The fit gives k0_i and α_i, and β_i only if it is significant.

### Run H (recommended): high legs by ohms, 72 h

This run supplies the tempcos that Run R cannot resolve on 1E-6 and 1E-7 (§7).

* **Setup:** the PSU disconnected from IN, the meter's 4-wire ohms leads on the NORMAL IN jacks, and OUT open.
* **Schedule:** the divider cycles `RANG 1E-5 / 1E-6 / 1E-7` with `OUTP ON` every 10 min. The meter range follows in
  lockstep: 300 kΩ, 3 MΩ, 30 MΩ. This is a scheduled change, not autorange. Drop the first 30 s after each switch.
* **What it reads:** R_H,i + R_L + contact and trace resistance. That is within 1 Ω of R_H,i, which is 10 ppm at
  100 kΩ and constant.
* **The result:** the *differences* α_H,5 − α_H,6 and α_H,5 − α_H,7. The meter's ohms tempco is common to all three
  legs and cancels in the differences, to the extent the three ohms ranges share their reference.

## 6. Combining the results

| Quantity | Source |
|---|---|
| k0_5, α_5 | Run R directly (1E-5 has the best signal). |
| k0_6, k0_7 | Run R directly. Cross-check: k0_5 · (R_H,5 + R_L)/(R_H,i + R_L) from Run H's resistances, at the same T0. |
| α_6, α_7 | **α_5 + (α_H,5 − α_H,i)** from Run H: the 1 Ω tempco is carried across from 1E-5, and the meter's ohms tempco cancels. Run R's direct α_6, α_7 must agree within their (large) errors. Without Run H, record α_6 = α_7 = 0 and put the Run R bound in `u_alpha_ppm`. |
| α_L (for the record) | α_5 + α_H,5. |
| T0 | Round the mean TMP275 over Run R to 0.1 °C, and refer k0 to it. |
| Tmin, Tmax | The TMP275 range observed over all runs used. |

**Free cross-check from Run R alone.** The block-by-block ratios k_5/k_6 and k_6/k_7 cancel V_in and the meter
entirely. Their temperature dependence is α_H,6 − α_H,5 (and α_H,7 − α_H,6), independent of the PSU model. It has to
agree with Run H, and a disagreement points at the PSU model or at lag.

## 7. Uncertainty budget

The per-block noise comes from Experiment 3: ±2.1 nV over 154 ABBA blocks of 60 s dwells, so σ_block ≈ 26 nV.
Natural cycling gives σ_T ≈ 1 °C. For the ~330 blocks per range of Run R, the statistical limits are:

| V_cal | 1E-5 | 1E-6 | 1E-7 |
|---|---|---|---|
| 10 V: k0, and α per °C | 14 ppm | 143 ppm | 1400 ppm |
| 20 V: k0, and α per °C | 7 ppm | 71 ppm | 710 ppm |

Hence Run H: at 20 V, Run R alone resolves α only on 1E-5. The budget uses the bench repo's `uncertainty.py`
split. Only the first two kinds combine; the unbounded terms are reported separately.

| Term | Kind | Bounded by |
|---|---|---|
| ABBA scatter | statistical | Scatter of independent sub-runs (not the fit's formal error). |
| PSU model residual; anchor mismatch before vs after | systematic | Run P residuals, the two anchors. |
| Lag / hysteresis (warming vs cooling fits) | systematic | `directional_tempco`. |
| TMP275 quantisation (0.0625 °C) | systematic | `quantization_attenuation`. |
| Voltage / self-heating coefficient | systematic | Optional check: 1E-5 at V_cal/4, V_cal/2 and V_cal, 1 h each. |
| **Meter range-to-range gain, 30 V vs 30 mV** | **unbounded here** | Enters k0 directly, at the 3478A's accuracy-spec level (hundreds of ppm, not a few). Only a second meter or a reference can close it. |
| Meter input-attenuator tempco (30 V range only) | unbounded here | Does not cancel between Runs P and R. A few ppm/°C at most. |
| Sensor-to-leg gain mismatch (high legs off-island) | unbounded here | The Run H vs Run R cross-check constrains it. |

**Realistic outcome.** k0 is limited by the meter's range-to-range accuracy, not by statistics, at every range except
perhaps 1E-7. α_5 comes out to a few ppm/°C (statistics plus PSU model). α_6 and α_7 are as good as Run H's
differences plus α_5. That meets the targets for α, and for k0 at the meter's own accuracy.

## 8. Write-back

Once the analysis is reviewed, the bench repo writes to the divider:

```
SYST:TIME <now>
CAL:REC 1E-5,<k0>,<T0>,<alpha>,<beta>,<u_k0_ppm>,<u_alpha_ppm>,<Tmin>,<Tmax>,"<date>","<run ids>"
CAL:REC 1E-6,...
CAL:REC 1E-7,...
SYST:ERR?                      -> must be 0 after each CAL:REC (a rejected record changes nothing)
CAL:SAVE                       -> NVS, and appends to /nvd/cal_history.txt
CAL:EXP                        -> /nvd/cal.txt
CAL:REC? 1E-5 / 1E-6 / 1E-7    -> read back and compare against what was sent
```

The `source` field has room for 63 characters. Use the run IDs, e.g.
`"2026-10-01_psu-drift_001+..._divider-ratio_001+..._high-legs_001"`, abbreviated if necessary. The full analysis
lives in the bench repo's report.

**Acceptance.**
1. Each |k0/nominal − 1| is within the part tolerances: 1 % on the 1 Ω plus 0.1 / 0.1 / 1 % on the high legs.
2. The cross-checks in §6 agree within the budget.
3. The before and after anchors agree within the PSU model's residual.

A failure in any of these is investigated, not written.

**Recalibration.** Once a year, after any repair or relay replacement, or if a spot-check disagrees with
`CAL:FACT?` by more than 3u. A spot-check is one 1E-5 ABBA hour plus anchors. `/nvd/cal_history.txt` keeps every
record the instrument has carried. The firmware can only append to it.
