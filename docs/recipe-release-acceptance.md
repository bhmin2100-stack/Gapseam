# GFE ALD / CVD final recipe release

## User requirements

- SFO3.1 is one ALD preset, not the definition of ALD.
- ALD uses GPC in angstrom/cycle and actual cycle count.
- CVD uses deposition rate (D/R) in angstrom/second and duration in seconds.
- Both allow plain conformal growth and optional ion etch, redeposition, inhibition.
- A process preset applies to another structure without replacing its geometry.
- Physical controls have independent meanings; solver settings are separate.
- Parameter popups explain the active calculation, with actual-engine cross-section movies where available and labeled mechanism explanations otherwise.
- Existing calibrated SFO3.1 output remains reproducible at 300 through 2000 angstrom.
- Final packaged GFE, not only source, must be exercised.

## Required evidence before completion

| Requirement | Evidence |
|---|---|
| ALD/CVD units and execution | Planar analytical tests, real GUI run, CVD time playback |
| Conformal growth | Uniform-offset trench test through closure, ALD/CVD dose equivalence |
| Physical transport | Saturation and sticking sensitivity, geometry visibility, convergence |
| Ion etch / redeposition | Independent LOS switch, first-hit transport, mass budget and geometry checks |
| Inhibition | Surface-coverage sensitivity, planar reference normalization, no hidden empirical modifiers |
| SFO3.1 | Original pre-edit baseline and exact regression at all eight doses |
| Preset portability | Save, load, change geometry, preserve runtime; explicit run-default restoration |
| Results and replay | All recipe fields, full geometry and numerical settings roundtrip; seconds in CVD |
| Usability | Screenshots of process selection, growth, etch, inhibition, preset and completed result |
| Help | All visible controls bound, active-model examples, global settings toggle |
| Packaging | Built executable launches and completes ALD/CVD/SFO fixture workflows |

## Scope of physics

The transport model is a two-dimensional, collisionless effective surface model.
Its coefficients need process/material calibration. ALD co-reactant conversion is
assumed complete; adsorption geometry is frozen within each actual ALD cycle.
Ideal conformal growth is a useful explicit limiting model. The historical SFO3.1
model remains identified as calibrated, not relabeled as a first-principles solver.
No density, composition, stress, reactor chemistry or LF-power-to-ion-energy
prediction is claimed.

## Verification state

Automated verification (Windows Python 3.13, Qt offscreen): 624 passed, 18
skipped. A final label/cancel-button-only adjustment was followed by 64 passing
UI checks and 5 existing skips. Skipped tests are not counted as verification.
The dedicated help suite passed 213 checks, including all 94 single-variable
comparisons across 194 actual engine runs and a matching source fingerprint.

The original SFO3.1 1000-cycle baseline exactly matches profiles and voids at
300, 500, 750, 1000, 1250, 1500, 1750 and 2000 angstrom. A separate early-cycle
check confirms active redeposition before closure. Closed voids also survive
continuation and replay; etching can reopen them in the tested case.

Independent numerical checks included a 10-angstrom aperture's analytic sky
flux (0.0499376 at 16/32/64 directions), conformal closure against the geometric
offset solution, mirror symmetry, reverse input ordering, and transport budgets.
Conservation of the integrated transport budget is not a claim of exact clipped
polygon-area conservation; surface discretization error requires convergence.

Three-run local median timings for a public 200-by-400-angstrom trench and
80-angstrom reference dose, ds=10, maximum step=2, 32 directions, without etch
or inhibition: ideal ALD 0.108 s, transport ALD 12.738 s, ideal CVD 0.138 s,
transport CVD 10.397 s. These models produce different profiles and are not an
old-versus-new speedup comparison. Concurrent local work may affect timings.

Native Windows package checks use public synthetic replay fixtures, then click
Run in the actual packaged GFE and inspect the newly exported results. Evidence
is retained in the local final-review-20261004 report folder. Native ALD
Conformal (30 angstrom), CVD Conformal (30 angstrom / 15 seconds), CVD transport
(20 angstrom / 10 seconds), and SFO3.1 preset (5 cycles / 10 angstrom) runs,
units, result rendering and automatic saving passed. All saved profile frames
exactly match both public fixtures and current-source reruns (maximum difference
0 angstrom). SFO3.1 has positive redeposition in all five growth frames; its
12-decimal UI input rounding was recorded separately and did not change profiles.
The final executable was installed at dist/GFE/GFE.exe, with the previous
installation retained as a recoverable backup and the user's data root preserved.

The dynamic report has been visually inspected at 1280x900 and 390x844 with
filter/reset, actual-frame playback, zoom, definition search and source inspection.
It contains public synthetic fixtures, not private SEM or user recipes.
