"""Actual one-field trench sweeps and bounded sensitivity-context search.

Run from the repository root with .venv/Scripts/python.exe.
Only generated report evidence is written; the production engine is untouched.
"""
from dataclasses import asdict, replace
from datetime import datetime, timezone
import argparse
import gzip
import json
from pathlib import Path
import time

from gapsim.emulation.parameter_help import HELP, SHORT_NAMES
from gapsim.emulation.parameter_help_all import EXTRA, LEGACY
from gapsim.emulation.parameter_help_trench import examples, Example, NECK
from gapsim.emulation.trench_depo import run_trench_depo
from build_help_trench_movies import engine_fingerprint, config_id, distance_and_focus, outlines

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'experiments/all-parameter-split-20261003'
APP=OUT/'report-app'
THRESHOLD=10.0
RECESSED=((-700.,0.),(-190.,0.),(-150.,-60.),(-150.,-220.),(-250.,-380.),
          (-250.,-900.),(250.,-900.),(250.,-380.),(150.,-220.),(150.,-60.),(190.,0.),(700.,0.))


def catalog():
    cases=examples(svt=False)
    base=cases['spin_cycles'].config
    cases['spin_depth_closure_threshold']=Example('spin_depth_closure_threshold',
        'deposition_closure_threshold_a',(1.,50.),('1 Å','50 Å'),'diagnostic',
        replace(cases['spin_depth_post_fill_hole_pct'].config, cycles=24))
    legacy={
        'cmb_redepo_source_model':('redepo_source_model',('model2','model3')),
        'spin_redepo_soft_los':('redepo_soft_los_radius_points',(0,8)),
        'chk_reflected_ion':('reflected_ion_enabled',(False,True)),
        'spin_reflected_strength':('reflected_ion_strength_pct',(0.,100.)),
        'spin_reflected_bowing':('reflected_ion_bowing_weight',(0.,2.)),
        'spin_reflected_microtrench':('reflected_ion_microtrench_weight',(0.,2.)),
        'spin_reflected_range':('reflected_ion_range_a',(100.,2000.)),
        'chk_lf_overhang':('lf_overhang_enabled',(False,True)),
        'spin_lf_overhang_dose':('lf_overhang_dose',(0.,3.)),
        'spin_lf_overhang_sputter_gain':('lf_overhang_sputter_gain',(0.,3.)),
        'spin_lf_overhang_redepo_fraction':('lf_overhang_redepo_fraction_pct',(0.,100.)),
        'spin_lf_overhang_survival':('lf_overhang_survival_penalty',(0.,1.)),
        'spin_lf_overhang_width':('lf_overhang_width_a',(20.,500.)),
        'chk_closure_redepo':('closure_redepo_enabled',(False,True)),
        'spin_closure_redepo_efficiency':('closure_redepo_efficiency_pct',(0.,100.)),
        'spin_closure_redepo_shadow_gain':('closure_redepo_shadow_gain',(0.,4.)),
        'spin_closure_redepo_width':('closure_redepo_width_a',(20.,500.)),
        'spin_closure_redepo_survival':('closure_redepo_survival_penalty',(0.,1.)),
        'spin_closure_redepo_smoothing':('closure_redepo_smoothing_a',(0.,300.)),
    }
    etch=cases['spin_redepo_efficiency'].config
    for key,(field,values) in legacy.items():
        cases[key]=Example(key,field,values,tuple(str(v) for v in values),'legacy',etch)
    return cases


def values_for(e):
    if len(e.values)==3:
        return list(e.values)
    lo,hi=e.values
    if isinstance(lo,bool) or isinstance(lo,str) or lo is None or hi is None:
        return [lo,hi]
    mid=getattr(e.config,e.field)
    if not min(lo,hi)<mid<max(lo,hi):mid=(lo+hi)/2
    if isinstance(lo,int) and isinstance(hi,int):
        mid=int(round(mid))
        if e.field=='redepo_incident_ray_count' and mid%2==0:mid+=1
    return list(dict.fromkeys([lo,mid,hi]))


def candidates(e):
    c=e.config
    if e.family=='closure':
        return [('잔류 공급 증가',replace(c,cycles=64,angstrom_per_cycle=9.)),
                ('잔류 공급 감소',replace(c,cycles=48,angstrom_per_cycle=4.,deposition_depth_decay_k=.35)),
                ('긴 Line 잔류 공급',replace(c,cycles=60,angstrom_per_cycle=7.,deposition_line_open_path_factor=.35)),
                ('더 깊은 폐공간',replace(c,cycles=60,points=tuple((x,y*1.5) for x,y in c.points)))]
    if e.family in ('etch','redepo','ions','transmission','smoothing'):
        return [('입구 안쪽으로 들어간 측벽',replace(c,points=RECESSED,cycles=32)),
                ('강한 식각·재증착',replace(c,cycles=36,angstrom_per_cycle=2.,sputter_strength_a_per_cycle=12.,redepo_efficiency_pct=100.)),
                ('넓은 이온 입사 분포',replace(c,points=RECESSED,cycles=32,redepo_incident_sigma_deg=20.,sputter_width_deg=45.)),
                ('수직에 집중한 이온 입사',replace(c,points=RECESSED,cycles=32,redepo_incident_sigma_deg=4.,sputter_width_deg=25.))]
    if e.family=='inhibition':
        return [('억제·CVD 복합 성장',replace(c,cycles=36,angstrom_per_cycle=9.,cvd_enabled=True,cvd_overhang_pct=80.,cvd_bottom_ratio_pct=65.)),
                ('강한 억제와 낮은 하한',replace(c,cycles=36,angstrom_per_cycle=9.,inhibition_strength_pct=100.,inhibition_min_growth_ratio=.01)),
                ('침투 경계가 측벽 가운데',replace(c,cycles=36,angstrom_per_cycle=9.,inhibition_penetration_depth_a=450.)),
                ('넓은 입구의 억제',replace(c,cycles=36,angstrom_per_cycle=9.,deposition_feature_width_a=900.))]
    return [('누적 증착량 증가',replace(c,cycles=36,angstrom_per_cycle=9.)),
            ('입구 안쪽으로 들어간 측벽',replace(c,points=RECESSED,cycles=36,angstrom_per_cycle=8.)),
            ('감쇠와 억제의 복합 성장',replace(c,cycles=36,angstrom_per_cycle=8.,inhibition_enabled=True,inhibition_peald_recombination_pct=100.,deposition_depth_decay_k=.2)),
            ('완만한 감쇠와 넓은 입구',replace(c,cycles=36,angstrom_per_cycle=8.,deposition_depth_decay_k=.2,deposition_feature_width_a=1200.))]


def label(e,v):
    if v in e.values:return e.labels[e.values.index(v)]
    from gapsim.emulation.parameter_help_response import FIELDS
    if e.key in FIELDS:
        _,scale,unit,_,_=FIELDS[e.key]
        return f'{v/scale:g} {unit}'.strip()
    return f'{v:g}'


def compact(value):
    if isinstance(value,float):return round(value,4)
    if isinstance(value,(list,tuple)):return [compact(v) for v in value]
    if isinstance(value,dict):return {k:compact(v) for k,v in value.items()}
    return value


def area(loop):
    if len(loop)<3:return 0.
    return abs(sum(p[0]*q[1]-q[0]*p[1] for p,q in zip(loop,loop[1:]+loop[:1])))/2


def seed_preview():
    """Open a useful real slice while the larger sweep continues separately."""
    cache=json.loads(gzip.decompress((OUT/'simulation-cache.json.gz').read_bytes()))
    e=catalog()['spin_cycles']
    ids=[config_id(replace(e.config,cycles=v)) for v in values_for(e)]
    delta,focus=distance_and_focus(outlines(cache['runs'][ids[0]]),outlines(cache['runs'][ids[-1]]))
    baseline=dict(name='기본 비교 조건',values=values_for(e),labels=[label(e,v) for v in values_for(e)],
                  runs=ids,difference_a=delta,focus=focus,void_difference_a2=0.)
    row=dict(key=e.key,field=e.field,title=SHORT_NAMES[e.key],family=e.family,meaning=HELP[e.key].meaning,
        caution=HELP[e.key].caution,status='단면 변화 확인',baselineDifference=delta,bestDifference=delta,searched=False,
        payload=json.dumps(compact(dict(baseline=baseline,best=baseline,trials=[])),ensure_ascii=False))
    source=dict(label='GFE 실제 계산 · 전체 비교 진행 중',files=['experiments/build_all_parameter_splits.py'])
    data=dict(title='파라미터 하나를 바꿀 때 트랜치 단면이 달라지는 모습',surface='report',buildStatus='creating',
        generatedAt=datetime.now(timezone.utc).isoformat(),status='modeled',filters=[],
        study=dict(caseCount=1,uniqueUsedRuns=len(ids),allExecutedRuns=len(cache['runs']),adaptiveCount=0,improvedCount=0),
        queries={'split_cases':dict(rows=[row],payloadColumns=['payload'],source=source),
                 'simulation_runs':dict(rows=[dict(id=rid,payload=json.dumps(compact(cache['runs'][rid]))) for rid in ids],payloadColumns=['payload'],source=source),
                 'control_audit':dict(rows=[],source=source)})
    (OUT/'reviewed.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')


def build(keys=None):
    OUT.mkdir(parents=True,exist_ok=True)
    fingerprint=engine_fingerprint()
    cache_path=OUT/'simulation-cache.json.gz'
    cache={'engine':fingerprint,'runs':{}}
    if cache_path.exists():
        old=json.loads(gzip.decompress(cache_path.read_bytes()))
        if old['engine']==fingerprint:cache=old
    started=time.perf_counter()
    rows=[]
    def run(c):
        rid=config_id(c)
        if rid not in cache['runs']:
            t=time.perf_counter()
            r=run_trench_depo(c)
            indices=sorted(set(round(i*(len(r.frame_steps)-1)/12) for i in range(13)))
            frames=[dict(step=r.frame_steps[i],profile=r.frame_profiles[i],voids=r.frame_voids[i],
                transport=r.meta.get('frame_transport_lines',[[]]*len(r.frame_steps))[i][:24],
                redepo=r.meta.get('frame_redepo_overlays',[[]]*len(r.frame_steps))[i][::3],
                etch=r.meta.get('frame_etch_overlays',[[]]*len(r.frame_steps))[i][::3]) for i in indices]
            cache['runs'][rid]=dict(config=asdict(c),frames=frames,seconds=time.perf_counter()-t,
                void_area_a2=sum(area(list(v)) for v in r.frame_voids[-1]),
                diagnostics={k:v for k,v in r.meta.items() if k.startswith('deposition_') and not k.startswith('deposition_frame') and isinstance(v,(float,int,str,bool,type(None)))})
        return rid
    def split(e,c,all_values=True):
        # STRICT one-field change, even for toggles. Dependency guards belong
        # to the engine. Do not use Example.configs(), which mimics UI coupling.
        vs=values_for(e) if all_values else [e.values[0],e.values[-1]]
        configs=[replace(c,**{e.field:v}) for v in vs]
        first=asdict(configs[0])
        for cfg in configs[1:]:
            assert {k for k,v in asdict(cfg).items() if v!=first[k]}=={e.field},e.key
        ids=[run(cfg) for cfg in configs]
        a,b=(cache['runs'][ids[i]] for i in (0,-1))
        delta,focus=distance_and_focus(outlines(a),outlines(b))
        return dict(values=vs,labels=[label(e,v) for v in vs],runs=ids,difference_a=delta,focus=focus,
                    void_difference_a2=abs(a['void_area_a2']-b['void_area_a2']))
    for key,e in catalog().items():
        if keys and key not in keys:continue
        entry=(HELP|EXTRA)[key]
        initial=split(e,e.config)
        base=dict(name='기본 비교 조건',**initial)
        trials=[]
        best=base
        subtle=initial['difference_a']<THRESHOLD
        if subtle and e.family not in ('legacy','diagnostic'):
            for name,c in candidates(e):
                # Candidate context is fixed identically for all split values.
                test=split(e,c,False)
                trials.append(dict(name=name,difference_a=test['difference_a'],void_difference_a2=test['void_difference_a2'],runs=test['runs']))
                if test['difference_a']>best['difference_a']+1e-8:
                    best=dict(name=name,**test)
            if best is not base:
                best=dict(name=best['name'],**split(e,replace(e.config,**cache['runs'][best['runs'][0]]['config'])))
        status='호환 항목 · 형상 효과 없음' if e.family=='legacy' else (
            '진단값 · 형상 효과 없음' if e.family=='diagnostic' else
            '수치 해상도' if e.family=='mesh' else
            '작은 차이 · 확대 확인' if best['difference_a']<THRESHOLD else '단면 변화 확인')
        rows.append(dict(key=key,field=e.field,title=SHORT_NAMES.get(key,entry.title),family=e.family,
            meaning=entry.meaning,caution=entry.caution,status=status,
            baselineDifference=initial['difference_a'],bestDifference=best['difference_a'],
            searched=bool(trials),payload=json.dumps(compact(dict(baseline=base,best=best,trials=trials)),ensure_ascii=False,separators=(',',':'))))
        print(f'{len(rows):02d} {key}: {initial["difference_a"]:.3f} -> {best["difference_a"]:.3f} Å; {len(trials)} contexts',flush=True)
        if len(rows)%5==0 or len(rows)==len(catalog()) or keys:
            checkpoint=cache_path.with_suffix('.tmp')
            checkpoint.write_bytes(gzip.compress(json.dumps(cache,separators=(',',':')).encode(),mtime=0))
            checkpoint.replace(cache_path)
    used={rid for row in rows for variant in ('baseline','best') for rid in json.loads(row['payload'])[variant]['runs']}
    run_rows=[dict(id=rid,payload=json.dumps(compact(cache['runs'][rid]),ensure_ascii=False,separators=(',',':'))) for rid in sorted(used)]
    known=set(catalog())
    audit=[dict(key=k,title=v.title,meaning=v.meaning,classification='표시/조작 항목',note=v.caution) for k,v in (HELP|EXTRA).items() if k not in known]
    now=datetime.now(timezone.utc).isoformat()
    source=dict(label='GFE 기본 통합 엔진 · 단일 파라미터 시뮬레이션',provider='local simulator',executedAt=now,
        files=['experiments/build_all_parameter_splits.py','src/gapsim/emulation/trench_depo.py'],
        evidenceFlow=[dict(title='실제 계산',detail='각 조건에서 run_trench_depo 실행. 한 Split 내부에서 목표 필드 하나만 다름.'),
            dict(title='민감도 조건 탐색',detail='기본 최종 경계 차이 10 Å 미만이면 4개 고정 공정 조합의 양 끝값 비교. 가장 큰 경계 차이의 조합에서 중간값까지 실행. 전역 최적값이 아닌 탐색한 조합 중 최대.'),
            dict(title='단면 기록',detail='각 계산에서 최대 13개 실제 Step 프레임. 임의 형상 보간 없음. 보고서 좌표만 0.0001 Å로 반올림.'),
            dict(title='엔진 식별',detail=f'SHA256 {fingerprint}')],
        metricDefinitions=[dict(label='최종 경계 차이 (Å)',definition='양방향 경계 꼭짓점에서 상대 경계 선분까지 거리의 최대 표본값. 폐공간 포함.',componentIds=['split-player','split-index']),
            dict(label='폐공간 면적 (Å²)',definition='최종 폐공간 다각형 면적의 합.',componentIds=['split-player'])])
    snapshot=dict(title='파라미터 하나를 바꿀 때 트랜치 단면이 달라지는 모습',surface='report',buildStatus='creating',
        generatedAt=now,status='modeled',filters=[],report=dict(asOf='2026-10-03'),
        queries={'split_cases':dict(rows=rows,payloadColumns=['payload'],source=source),
                 'simulation_runs':dict(rows=run_rows,payloadColumns=['payload'],source=source),
                 'control_audit':dict(rows=audit,source=dict(label='GFE 도움말·조절 항목 목록',files=['src/gapsim/emulation/parameter_help_all.py']))},
        study=dict(engine=fingerprint,thresholdA=THRESHOLD,caseCount=len(rows),uniqueUsedRuns=len(used),
            allExecutedRuns=len(cache['runs']),adaptiveCount=sum(r['searched'] for r in rows),
            improvedCount=sum(r['bestDifference']>r['baselineDifference']+1e-8 for r in rows),
            elapsedSeconds=time.perf_counter()-started))
    target=APP/'src/data.json' if (APP/'src/data.json').exists() else OUT/'reviewed.json'
    if target.exists() and target==APP/'src/data.json':
        previous=json.loads(target.read_text(encoding='utf-8'))
        snapshot.update({k:previous[k] for k in ('id','legacyPresentationTitle') if k in previous})
    target.write_text(json.dumps(snapshot,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (OUT/'verification.json').write_text(json.dumps(snapshot['study'],indent=2),encoding='utf-8')
    print(json.dumps(snapshot['study'],indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--keys',nargs='+')
    parser.add_argument('--seed-preview',action='store_true')
    args=parser.parse_args()
    seed_preview() if args.seed_preview else build(args.keys)
