# Fixed-repeat recipe integration

## What changed

The native GFE runner now supports an orientation-dependent front solver and an
ion-weighted growth contribution as ordinary serialized recipe settings. A run
uses the same settings on every cycle. There is no terminal finishing stage,
target-contour replacement, or cycle-dependent recipe switch.

The process preset and input structure are separate library entries. Loading a
process preset does not replace an arbitrary user structure. Select the input
separately in step 1's structure library. The process pane has one Apply action;
it loads saved calculation settings by default, keeps the current cycle/time
unless the optional saved-duration checkbox is checked, and never locks dose
editing. Existing library
files are backed up before an explicit replacement; unrelated entries remain.

Since 0.2.1, selecting **SFO3.1** reads the shipped `sfo31_verified.json`
directly. It does not depend on successful registration into a writable local
library. Older or user-edited same-name recipes appear as **SFO3.1 (저장본)**;
they remain available without overwriting the original library. Identical
saved copies are omitted from the menu to avoid duplicate entries. A fresh or
unreadable library still offers the built-in process. User saves remain editable.
Applying the built-in process verifies GPC, model, key switches and cycles before
showing success. The input structure is still selected separately.

## Controls

- **Front solver** is a numerical method, not a physical process parameter.
- **Ion-weighted growth fraction** weights the local arrival field; it is an
  effective model coefficient, not an independently measured ion fraction.
- **Redeposition distance limit** is a numerical transport horizon in angstroms,
  not a gas mean free path.
- **Symmetry** is a boundary/numerical option. It should not make an asymmetric
  input structure symmetric without an explicit user choice.
- **Inhibition law** selects the response law without introducing a separate
  finishing recipe.

These settings have help descriptions and single-variable example simulations.
Examples use generic demonstration structures, not a prediction for every
geometry. When the profile change is too small to see, the help distinguishes
an explanatory diagram from an actual simulated profile.

## Reproduction and limitations

For reference reproduction, select the reference structure in step 1, select
the process preset in step 3, enable saved cycle/time and calculation settings,
click Apply, then the normal Run button. For another target structure or dose,
keep that input and edit cycles after applying the process. The saved
run JSON includes the input structure, recipe, frame steps, and void geometry.
`tools/compare_sfo31_replay.py` compares a saved native run against a separately
supplied frozen reference. It checks every reference snapshot and final voids;
it neither fits nor modifies either input.

Matching a frozen numerical reference demonstrates software reproducibility.
It does not independently validate the material model or establish accuracy
for other structures, doses, or equipment.

Production tests can run without local research scripts. An optional research
cross-check is skipped when those scripts are absent; analytic front tests,
preset persistence, and the normal UI run/export tests remain enabled.

Run tests with `QT_QPA_PLATFORM=offscreen` and `python -m pytest -q`.
