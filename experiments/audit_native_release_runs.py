"""Compare saved packaged-GFE runs with public fixtures and source reruns.

This audits persisted outputs. Actual native click/visual evidence belongs to
the root agent's UI verification; this script does not manufacture such proof.
"""
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

from gapsim.emulation.trench_depo import run_trench_depo
from gapsim.emulation.trench_depo_export import load_trench_depo_run
from gapsim.engine.run_logger import write_json


ROOT=Path('C:/Users/bhmin/Documents/GapseamReports/final-review-20261004')


def sha(value):
    return hashlib.sha256(json.dumps(value,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def profile_difference(actual,expected):
    a,b=np.asarray(actual,dtype=float),np.asarray(expected,dtype=float)
    def directed(points,line):
        starts=line[:-1];segments=np.diff(line,axis=0)
        squares=np.sum(segments*segments,axis=1)
        maximum=0.
        for point in points:
            t=np.divide(np.sum((point-starts)*segments,axis=1),squares,
                        out=np.zeros(len(squares)),where=squares>0)
            projected=starts+np.clip(t,0,1)[:,None]*segments
            maximum=max(maximum,float(np.min(np.linalg.norm(projected-point,axis=1))))
        return maximum
    exact=actual==expected
    return dict(exact=exact,actual_points=len(a),expected_points=len(b),
        max_corresponding_point_distance_a=float(np.max(np.linalg.norm(a-b,axis=1))) if len(a)==len(b) else None,
        symmetric_vertex_to_segment_distance_a=0. if exact else max(directed(a,b),directed(b,a)),
        actual_profile_sha256=sha(actual),expected_profile_sha256=sha(expected))


def main():
    manifest=json.loads((ROOT/'qa-fixtures/manifest.json').read_text(encoding='utf-8'))
    targets={item['name']:item for item in manifest['cases']}
    required={'ald-conformal-30A','cvd-physical-20A','sfo31-5cycles','cvd-conformal-30A'}
    records=[]
    for path in sorted((ROOT/'native-qa/runs/trench_depo_emulation').rglob('에뮬레이터재생_*.json')):
        config,result,note=load_trench_depo_run(path)
        if config.recipe_model=='legacy_calibrated_v1' and config.cycles==5:
            name='sfo31-5cycles'
        elif config.process_type=='ald' and config.recipe_model=='ideal_conformal_v1':
            name='ald-conformal-30A'
        elif config.process_type=='cvd' and config.recipe_model=='physical_transport_v1':
            name='cvd-physical-20A'
        elif config.process_type=='cvd' and config.recipe_model=='ideal_conformal_v1':
            name='cvd-conformal-30A'
        else:
            records.append(dict(path=str(path),unrecognized=True));continue
        target=targets[name]
        fixture_config,fixture,_=load_trench_depo_run(target['path'])
        rerun=run_trench_depo(config)
        comparison=profile_difference(result.final_profile,fixture.final_profile)
        source_comparison=profile_difference(result.final_profile,rerun.final_profile)
        actual_fields=asdict(config);fixture_fields=asdict(fixture_config)
        differences={key:dict(native=actual_fields[key],fixture=fixture_fields[key])
                     for key in actual_fields if actual_fields[key]!=fixture_fields[key]}
        checks=dict(process_type=config.process_type==target['process_type'],
            recipe_model=config.recipe_model==target['recipe_model'],growth_basis=config.growth_basis==target['growth_basis'],
            nominal_dose_a=result.meta.get('nominal_dose_a')==target['expected_nominal_dose_a'],
            frame_count=len(result.frame_profiles)==target['expected_frames'],
            frame_steps_equal=result.frame_steps==fixture.frame_steps,
            voids_equal=result.frame_voids==fixture.frame_voids,
            capture_state=bool(result.meta['redepo_active'])==target['expected_redepo_active'],
            source_replay_exact=source_comparison['exact'],
            all_source_frames_exact=result.frame_profiles==rerun.frame_profiles,
            all_fixture_frames_exact=result.frame_profiles==fixture.frame_profiles,
            fixture_profile_within_1e_6_a=comparison['symmetric_vertex_to_segment_distance_a']<=1e-6)
        if config.process_type=='cvd':
            checks['actual_elapsed_time_s']=result.meta['frame_times_s'][-1]==target['duration_s']
            checks['deposition_rate']=config.cvd_rate_a_per_s==target['deposition_rate_a_per_s']
        else:
            checks['cycles']=config.cycles==target['cycles']
            checks['gpc']=config.angstrom_per_cycle==target['gpc_a']
        if name=='sfo31-5cycles':
            checks['positive_redeposited_area']=result.meta['redepo_total_mass_last']>0
            checks['positive_redepo_frames']=any(bool(f) for f in result.meta['frame_redepo_overlays'])
        gifs=[]
        for gif in path.parent.glob('*.gif'):
            with Image.open(gif) as image:
                gifs.append(dict(path=str(gif),size=list(image.size),frames=image.n_frames,format=image.format))
        record=dict(case=name,path=str(path),all_checks_pass=all(checks.values()),checks=checks,
            input_differences=differences,fixture_profile=comparison,source_rerun_profile=source_comparison,
            all_source_frames_exact=result.frame_profiles==rerun.frame_profiles,
            all_fixture_frames_exact=result.frame_profiles==fixture.frame_profiles,
            actual_nominal_dose_a=result.meta['nominal_dose_a'],
            actual_redepo_area_last=result.meta['redepo_total_mass_last'],
            frames_with_positive_redepo=sum(bool(f) for f in result.meta['frame_redepo_overlays']),
            gif_outputs=gifs)
        records.append(record)
        print(name,record['all_checks_pass'],comparison['exact'],comparison['symmetric_vertex_to_segment_distance_a'],flush=True)
    present={r['case'] for r in records if 'case' in r}
    audit=dict(created_utc=datetime.now(timezone.utc).isoformat(),
        scope='Persisted packaged-native runs compared against synthetic QA fixtures and current source reruns. UI clicks were performed and documented separately by root agent.',
        required_cases=sorted(required),missing_cases=sorted(required-present),
        required_cases_pass=required<=present and all(r['all_checks_pass'] for r in records if r.get('case') in required),
        profile_tolerance_a=1e-6,records=records)
    output=ROOT/'native-qa-audit.json'
    write_json(output,audit)
    print(output,flush=True)
    if not audit['required_cases_pass']:raise SystemExit('Native QA output comparison incomplete or failed')


if __name__=='__main__':main()
