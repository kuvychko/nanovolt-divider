# Calibration data

The small, durable data behind each result in [docs/calibration.md](../docs/calibration.md): enough to
check every number there and to compare against your own build. The raw per-sample logs are not
kept here; they run to hundreds of megabytes per step.

One directory per step, named by date and step:

```
calibration/
  YYYY-MM-DD_supply/        step 1
  YYYY-MM-DD_high-legs/     step 2
  YYYY-MM-DD_null/          step 3
  YYYY-MM-DD_ratio/         step 4
  YYYY-MM-DD_injection/     step 5
  records/                  CAL:REC values written to the instrument
```

Each step directory holds:

* `summary.json`: the conditions (instruments, setpoints, duration, TMP275 span), the fitted
  coefficients and their uncertainties.
* Per-dwell or per-block CSV where the result is built from blocks: one row per block with its UTC
  time, range, polarity pattern, mean, scatter, sample count and TMP275 reading.
* The figures used in the results section.

All timestamps are UTC (ISO 8601). Temperatures are TMP275 readings in °C. Voltages are in volts and
resistances in ohms unless a column name says otherwise.
