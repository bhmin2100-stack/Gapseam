# Dent Analysis Addon

Copy this whole folder into the GFE addon folder:

```text
addons/dent-analysis/
```

GFE loads `addon.json` at startup. The addon adds:

- a progress-panel control for selecting a dent region and optional slope reference line
- a result-panel graph and table for dent depth by cycle or thickness
- `result.meta["dent_analysis"]` so saved result JSON includes the dent analysis payload

