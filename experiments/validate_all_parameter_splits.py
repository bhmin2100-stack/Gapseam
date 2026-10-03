"""Verify strict single-field sweeps, displayed coordinates and fresh engine replays."""
from dataclasses import replace
import argparse
import gzip
import json
import math

from build_all_parameter_splits import OUT, APP, catalog, compact, HELP, EXTRA
from build_help_trench_movies import distance_and_focus, outlines, engine_fingerprint
from gapsim.emulation.trench_depo import run_trench_depo


def validate(complete=False):
    data=json.loads((APP/'src/data.json').read_text(encoding='utf-8'))
    cache=json.loads(gzip.decompress((OUT/'simulation-cache.json.gz').read_bytes()))
    assert cache['engine']==engine_fingerprint()==data['study']['engine']
    rows=data['queries']['split_cases']['rows']
    audit=data['queries']['control_audit']['rows']
    assert {r['key'] for r in rows}|{r['key'] for r in audit}==set(HELP)|set(EXTRA)
    assert len({r['key'] for r in rows})==len(rows)==len(catalog())
    displayed={r['id']:json.loads(r['payload']) for r in data['queries']['simulation_runs']['rows']}
    checked=0
    for row in rows:
        p=json.loads(row['payload'])
        for s in [p['baseline'],p['best']]+p['trials']:
            runs=[cache['runs'][i] for i in s['runs']]
            first=runs[0]['config']
            for run in runs[1:]:
                assert {k for k,v in run['config'].items() if v!=first[k]}=={row['field']},row['key']
            delta,_=distance_and_focus(outlines(runs[0]),outlines(runs[-1]))
            assert abs(delta-s['difference_a'])<.000051,(row['key'],delta,s['difference_a'])
            checked+=1
        assert abs(p['best']['difference_a']-max([p['baseline']['difference_a']]+[t['difference_a'] for t in p['trials']]))<.000051
    for rid,run in displayed.items():
        assert run==compact(cache['runs'][rid]),rid
        steps=[f['step'] for f in run['frames']]
        assert steps==sorted(set(steps)) and steps[0]==0 and steps[-1]==run['config']['cycles']
        for frame in run['frames']:
            assert len(frame['profile'])>=2
            for poly in [frame['profile']]+frame['voids']:
                assert all(len(pt)==2 and all(math.isfinite(v) for v in pt) for pt in poly)
    replay=[]
    for key in ('cvd_overhang_pct','spin_redepo_emit_power','spin_depth_post_fill_hole_pct','spin_depth_closure_threshold'):
        row=next(r for r in rows if r['key']==key)
        rid=json.loads(row['payload'])['best']['runs'][-1]
        stored=cache['runs'][rid]
        cfg=replace(catalog()[key].config,**stored['config'])
        actual=run_trench_depo(cfg)
        for frame in stored['frames']:
            index=actual.frame_steps.index(frame['step'])
            assert compact(frame['profile'])==compact(actual.frame_profiles[index]),key
            assert compact(frame['voids'])==compact(actual.frame_voids[index]),key
        replay.append(key)
    verification=data['study']|dict(singleFieldScenariosChecked=checked,displayedRunsChecked=len(displayed),
        catalogControlsCovered=len(rows)+len(audit),freshReplays=replay,passed=True)
    (OUT/'verification.json').write_text(json.dumps(verification,indent=2),encoding='utf-8')
    if complete:
        data['buildStatus']='complete'
        numerical={'spin_incident_rays','spin_inhibition_smoothing','spin_sputter_smoothing'}
        for row in rows:
            if row['family']=='mesh' or row['key'] in numerical:row['status']='수치 근사 · 공정 세기 아님'
        (APP/'src/data.json').write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print(json.dumps(verification,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--complete',action='store_true')
    validate(parser.parse_args().complete)
