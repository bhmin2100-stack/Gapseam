# Common process parameters: evaluation candidate

Date: 2026-10-29. Reference: `8a31ef4585d4567da20a28a4cdf5edc1e109ec57`.

This branch is an engine/schema feasibility prototype, not a released desktop
parameter editor. `process_parameter_schema` groups every configuration field
without changing its numeric value. Preset names are descriptive only.
`calibrated_response_v1` uses explicit `ResponseParameters`; old 3.10 model keys
remain aliases for the original coefficients. Disabled additional responses
retain the 3.1 calculation. The new model is currently ALD-only.

## Evaluation evidence

An independent archive of the reference source and the candidate each ran:

- 3.1 and 3.10 at original GPC 0.56, 1,045 cycles, **20 Å point spacing**.
- Both models at original **4 Å spacing for 12 cycles**, plus 8-cycle coarse runs.
- Both models at 12.5 Å/cycle for 64 cycles (800 Å), with etch amplitude scaled
  by the same factor. These are accelerated stress tests, not a claim that
  high-GPC trajectories equal the nominal-GPC physical process.
- Asymmetric inputs, pre-existing closed voids, and 3.10 aspect ratios 2 and 5.

All 14 scenarios / 2,360 frames were exactly equal in profiles, voids, and
existing calculation metadata. Only the explicit new response block and
versioned model identity differ. No coordinate tolerance or target fitting
was used. The new default growth expression also matched 42,084 independent
samples; the fill-fraction expression matched 20,001 depth samples exactly.

Individual changes to upper growth, dose transition, aspect response, and
closed-void filling changed the corresponding computed result. Omitting the
ion-growth contribution changed the shape, confirming it cannot be discarded.
Saved process records and exported run JSON retain explicit response settings.

Focused existing/new tests: 135 passed, one optional research comparison skipped.

## Boundaries and remaining work

- Original 4 Å spacing for the entire 1,045 cycles has **not** been replayed.
- The desktop UI does not yet offer this model or its new parameter controls.
  Do not distribute generic candidate presets as desktop-ready files.
- Display grouping and preset application policy are distinct. Calibration
  smoothing still loads as recipe data even if the UI places it in Numerical.
  Keep raw float values; do not reconstruct untouched settings from rounded labels.
- Next Depo starts another stage, not a stateful resume. A 6+6 versus continuous
  12-cycle experiment differed. Dose, closure history, and remaining budgets need
  a separate continuation design before equivalence can be promised.
- Closed-void filling remains an empirical area-budget rule, not an independently
  validated supply or redeposition mechanism. Other structures/materials require
  separate physical validation.
- Timings were recorded while jobs overlapped; they are not a speed benchmark.

The replay loader explicitly handles the new nested response object instead of
coercing every nullable field to a float. Existing presets without the object
keep their previous defaults. Unknown schema fields and invalid response values
are rejected instead of silently dropped.
