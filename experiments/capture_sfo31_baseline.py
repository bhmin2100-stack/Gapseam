"""Capture the full versioned SFO3.1 comparison fixture before recipe integration."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

from gapsim.emulation.incident_presets import incident_study_preset, INCIDENT_PRESET_DOSES
from gapsim.emulation.trench_depo import run_trench_depo


if __name__ == '__main__':
    target = Path('C:/Users/bhmin/Documents/GapseamReports/final-review-20261004/sfo31-baseline.json')
    verify = '--verify' in sys.argv
    if target.exists() and not verify:
        raise SystemExit('Baseline already exists; refusing to overwrite it.')
    baseline = json.loads(target.read_text(encoding='utf-8')) if verify else None
    config = incident_study_preset(2000)
    engine = Path('src/gapsim/emulation/trench_depo.py')
    fingerprint = hashlib.sha256(engine.read_bytes()).hexdigest()
    result = run_trench_depo(config, progress_cb=lambda i,n: print(f'{i}/{n}', flush=True) if i % 100 == 0 else None)
    frames = {str(d): dict(profile=result.frame_profiles[d//2], voids=result.frame_voids[d//2])
              for d in INCIDENT_PRESET_DOSES}
    target.parent.mkdir(parents=True, exist_ok=True)
    if verify:
        differences = [dose for dose in frames if frames[dose] != baseline['frames'][dose]]
        # JSON uses lists while the in-memory engine uses point tuples.
        normalized = json.loads(json.dumps(frames))
        differences = [dose for dose in normalized if normalized[dose] != baseline['frames'][dose]]
        audit = dict(exact_profiles_and_voids=not differences, differing_doses_a=differences,
                     compared_doses_a=list(INCIDENT_PRESET_DOSES),baseline_engine_sha256=baseline['engine_sha256'],
                     current_engine_sha256=fingerprint,legacy_redepo_active=result.meta['redepo_active'])
        output = target.with_name('sfo31-regression.json')
        output.write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
        print(audit)
        if differences:raise SystemExit('SFO3.1 regression found')
    else:
        target.write_text(json.dumps(dict(engine_sha256=fingerprint, config=asdict(config), frames=frames), ensure_ascii=False), encoding='utf-8')
        print(target)
