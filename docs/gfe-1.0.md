# GFE 1.0

The process pane has six categories: execution, growth/transport,
etch/redeposition, inhibition, calibrated response, and numerical accuracy.
ALD and CVD retain conformal defaults. The calibrated-response editor is ALD-only;
changing to CVD selects the supported conformal model.

## Shared recipe parameters

`calibrated_response_v1` is the shared model. Built-in SFO3.1, SFO3.10, and
SFO3.10-HAR (experimental) use that key and explicit coefficient records.
Preset names do not select an equation. Old ALD model keys migrate in memory
when loaded into the editor; old files are not rewritten automatically.

All response coefficients, switches, dose thresholds, reference choices and
closure settings are editable. Raw float values remain exact until an input is
edited; display formatting does not refit coefficients. Existing field-level
help distinguishes active empirical responses from physical transport.

SFO3.1 disables the additional growth and closure response. SFO3.10 enables
depth/dose/aspect growth and empirical closure filling. HAR additionally enables
a smooth AR 7–10 transition, deep-growth floor and upper band, fill-budget
extension, and fill-rate increase. These are empirical coefficients, not
independently validated material properties or a physical supply model for
closed cavities. Every cycle uses the same expression; no finishing stage is
appended. Next Depo remains a new stage, not stateful continuous resume.

## Presets and geometry

The program always supplies the three recipes and these separate structures,
even if user libraries are empty or read-only:

- CD242 nm / depth702 nm, original rounded-corner reference coordinates.
- CD365 nm / depth1839 nm, confirmed photo dimensions and piecewise-linear walls.
- CD230 nm / depth5000 nm, straight-wall approximation confirmed for this task.

Process Apply never replaces the structure. Saved cycle/time and pure numerical
settings remain optional; users can change cycle count after applying a recipe.
Same-name user recipes remain separate from built-ins. Saving a modified built-in
structure creates a user copy. Built-ins cannot be deleted through the library UI.

## Verification protocol

`experiments/verify_v1_matrix.py prepare` uses the real Qt preset controls to
prepare nine configurations. The run mode executes independent source trees;
compare hashes every frame, final surface and closed-void polygon. GPC remains
0.56 Å/cycle for 1045 cycles. Comparison spacing is 20 Å for the first two
structures and 50 Å for the deep structure. These full-dose comparisons are
not a full-duration convergence validation at the preset's 4 Å spacing.

Reference 3.1/3.10 source: commit `8a31ef4`. HAR reference: preserved local research
source snapshot under the verification output directory, separately hashed.
Evidence and the interactive comparison report are stored outside the repository
under `GapseamReports/gfe-v1-validation-20261029`.

The version increment does not imply new physical validation. Publishing to
GitHub and local packaging are separate actions.

## Completed validation (2026-10-29)

- Nine independent baseline/candidate pairs passed exact comparison: 9414
  saved frames, final profiles, closed-void polygons, normalized metadata and
  input settings. The stated 20/50 Angstrom evaluation spacing applies.
- Full suite: 858 passed, 19 skipped (248.41 seconds). An earlier redirected
  run with extra global test-data overrides emitted a Windows/Qt access
  violation; the clean-environment full run completed, including cancellation.
  The cause of that intermittent diagnostic has not been established.
- Packaged GFE 1.0.0: inspected all three recipe/structure entries, applied HAR,
  observed GPC 0.56 and 1045 cycles with unchanged geometry, edited to 3 cycles,
  and completed a real worker run. Then loaded the full 1045-cycle SFO3.1
  validation history and observed its final result and 585.2 Angstrom label.
- Help profiles were regenerated: 99 entries from 202 actual simulations.
