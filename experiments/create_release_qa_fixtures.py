"""Public deterministic recipe fixtures for packaged GFE UI acceptance.

Only synthetic geometry and public defaults are used. Production replay
serialization/loading is exercised; GIF rendering is intentionally unnecessary.
"""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

from gapsim.emulation.incident_presets import sfo31_preset
from gapsim.emulation.process_recipe import recipe_nominal_dose
from gapsim.emulation.trench_depo import TrenchDepoConfig, run_trench_depo
from gapsim.emulation.trench_depo_export import result_to_payload, load_trench_depo_run
from gapsim.engine.run_logger import write_json


ROOT=Path('C:/Users/bhmin/Documents/GapseamReports/final-review-20261004/qa-fixtures')
POINTS=((-600.,0.),(-100.,0.),(-100.,-400.),(100.,-400.),(100.,0.),(600.,0.))


def profile_sha(profile):
    return hashlib.sha256(json.dumps(profile,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    base=TrenchDepoConfig(points=POINTS,recipe_model='ideal_conformal_v1',process_type='ald',
        growth_basis='net_planar',cycles=6,angstrom_per_cycle=5.,reparam_ds_a=10.,
        numerical_step_a=2.,transport_ray_count=32,precursor_sticking=.1,
        sputter_enabled=False,redepo_enabled=False,inhibition_enabled=False)
    cases=[
        ('ald-conformal-30A',base,'ALD 균일 증착 · 5 Å/cycle × 6 cycle = 30 Å'),
        ('cvd-physical-20A',replace(base,recipe_model='physical_transport_v1',process_type='cvd',
            cvd_rate_a_per_s=2.,cvd_duration_s=10.),'CVD 물리 수송 · 2 Å/s × 10 s = 20 Å'),
        ('sfo31-5cycles',replace(sfo31_preset(),cycles=5),'SFO3.1 ALD · 원래 구조 · 2 Å/cycle × 5 cycle = 10 Å'),
        ('cvd-conformal-30A',replace(base,process_type='cvd',cvd_rate_a_per_s=2.,cvd_duration_s=15.),
            'CVD 균일 증착 · 2 Å/s × 15 s = 30 Å'),
    ]
    manifest=[]
    for name,config,note in cases:
        result=run_trench_depo(config)
        path=ROOT/f'{name}.json'
        write_json(path,result_to_payload(config,result,request_note=note))
        loaded_config,loaded_result,loaded_note=load_trench_depo_run(path)
        rerun=run_trench_depo(loaded_config)
        if result.final_profile!=loaded_result.final_profile or result.final_profile!=rerun.final_profile:
            raise AssertionError(f'Replay/recipe rerun mismatch: {name}')
        expected=recipe_nominal_dose(config)
        if result.meta['nominal_dose_a']!=expected:
            raise AssertionError(f'Unit-dose mismatch: {name}')
        if name.startswith('sfo31') and not result.meta['redepo_active']:
            raise AssertionError('SFO3.1 fixture must contain actual redeposition')
        item=dict(name=name,path=str(path),note=note,public_synthetic=True,
            process_type=config.process_type,recipe_model=config.recipe_model,growth_basis=config.growth_basis,
            cycles=config.cycles if config.process_type=='ald' else None,
            gpc_a=config.angstrom_per_cycle if config.process_type=='ald' else None,
            duration_s=config.cvd_duration_s if config.process_type=='cvd' else None,
            deposition_rate_a_per_s=config.cvd_rate_a_per_s if config.process_type=='cvd' else None,
            expected_nominal_dose_a=expected,expected_frames=len(result.frame_profiles),
            expected_numerical_steps=result.meta.get('numerical_steps'),
            expected_final_profile_sha256=profile_sha(result.final_profile),
            expected_final_points=len(result.final_profile),
            expected_top_y_a=max(y for x,y in result.final_profile),
            expected_min_y_a=min(y for x,y in result.final_profile),
            expected_redepo_active=result.meta['redepo_active'],
            expected_last_time_s=result.meta.get('frame_times_s',[])[-1] if config.process_type=='cvd' else None,
            replay_roundtrip_exact=True,recipe_rerun_exact=True,
            native_ui_checks=['Open replay file in packaged GFE','Verify process/model/units and dose',
                              'Run once using the displayed parameters','Save result JSON',
                              'Compare nominal dose, process/model, final profile hash and active redeposition'])
        manifest.append(item)
        print(name,expected,'A',len(result.frame_profiles),'frames',flush=True)
    write_json(ROOT/'manifest.json',dict(kind='gfe_public_release_qa',cases=manifest))
    print(ROOT/'manifest.json',flush=True)


if __name__=='__main__':main()
