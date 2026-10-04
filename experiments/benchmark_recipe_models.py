"""Disclosed workload timings, not an old/new speedup claim."""
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import statistics
import time

from gapsim.emulation.trench_depo import TrenchDepoConfig, run_trench_depo


def benchmark():
    points=[(-600.,0.),(-100.,0.),(-100.,-400.),(100.,-400.),(100.,0.),(600.,0.)]
    common=TrenchDepoConfig(points=points,cycles=40,angstrom_per_cycle=2.,
        cvd_rate_a_per_s=2.,cvd_duration_s=40.,reparam_ds_a=10.,numerical_step_a=2.,
        transport_ray_count=32,precursor_sticking=.1,ald_exposure=5.,growth_basis='net_planar',
        sputter_enabled=False,redepo_enabled=False,inhibition_enabled=False)
    records=[]
    for process in ('ald','cvd'):
        for model in ('ideal_conformal_v1','physical_transport_v1'):
            config=replace(common,process_type=process,recipe_model=model)
            run_trench_depo(replace(config,cycles=1,cvd_duration_s=1.))
            times=[]
            for repetition in range(3):
                started=time.perf_counter()
                result=run_trench_depo(config)
                times.append(time.perf_counter()-started)
                print(process,model,repetition+1,round(times[-1],4),flush=True)
            records.append(dict(process=process,model=model,seconds=times,
                median_seconds=statistics.median(times),numerical_steps=result.meta['numerical_steps'],
                final_points=len(result.final_profile),nominal_dose_a=result.meta['nominal_dose_a'],
                bottom_rise_a=min(y for x,y in result.final_profile)+400.))
    sources=['src/gapsim/emulation/process_recipe.py','src/gapsim/engine/surface_kinetics.py',
             'src/gapsim/engine/deposition_pipeline.py','src/gapsim/emulation/trench_depo.py']
    report=dict(created_utc=datetime.now(timezone.utc).isoformat(),python=platform.python_version(),
        workload=dict(trench_width_a=200.,depth_a=400.,lateral_span_a=1200.,nominal_dose_a=80.,
                      mesh_spacing_a=10.,numerical_step_a=2.,rays=32,ald_cycles=40,gpc_a=2.,
                      cvd_rate_a_per_s=2.,cvd_duration_s=40.,precursor_sticking=.1,ald_exposure=5.,
                      etch=False,redeposition=False,inhibition=False),
        method='One warm-up and three sequential wall-clock timings per mode; same geometry, dose and numerical settings.',
        caveat='Different model physics and shapes: timings are workload costs, not old/new speedup or equal-accuracy comparison. Other verification jobs may run concurrently.',
        records=records,source_sha256={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in sources})
    target=Path('C:/Users/bhmin/Documents/GapseamReports/final-review-20261004/recipe-model-benchmark.json')
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(target,flush=True)


if __name__=='__main__':benchmark()
