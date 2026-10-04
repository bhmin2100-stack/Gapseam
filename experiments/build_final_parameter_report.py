"""Prepare reviewed, public synthetic SVT evidence for the final Data report.

No user presets, structures, SEM, credentials, or absolute source paths are read.
The snapshot records actual calculated frames, not interpolated invented shapes.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path

from build_help_trench_movies import engine_fingerprint
from gapsim.emulation.parameter_help import HELP, SHORT_NAMES, effective_help
from gapsim.emulation.parameter_help_all import EXTRA
from gapsim.emulation.parameter_help_trench import ASSET, examples, recipe_note
from gapsim.emulation.trench_depo import TrenchDepoConfig

ROOT=Path(__file__).resolve().parents[1]
MODELS={'legacy_calibrated_v1':'기존 보정', 'ideal_conformal_v1':'Conformal',
        'physical_transport_v1':'수송·표면 반응'}


def rounded(value):
    if isinstance(value,float):return round(value,3)
    if isinstance(value,list):return [rounded(v) for v in value]
    if isinstance(value,dict):return {key:rounded(v) for key,v in value.items()}
    return value


def build(output, *, allow_stale=False, complete=False):
    asset=ROOT/'src/gapsim/emulation'/ASSET
    data=json.loads(gzip.decompress(asset.read_bytes()))
    current=engine_fingerprint()
    matches=current==data['engine_sha256']
    if not matches and not allow_stale:
        raise ValueError('Help movies do not match the current engine. Regenerate before final report.')
    cases=[]
    for key,case in data['cases'].items():
        base_key=key.split('@')[0]
        runs=[data['runs'][rid] for rid in case['runs']]
        c=TrenchDepoConfig(**runs[1 if len(runs)==3 else 0]['config'])
        entry=effective_help(base_key,HELP[base_key],c)
        before=runs[0]['config']
        for run in runs[1:]:
            changes={name for name,value in before.items() if value!=run['config'][name]}
            if changes!={case['field']}:
                raise ValueError(f'{key}: confounded comparison {changes}')
        cases.append(dict(id=key,key=base_key,title=SHORT_NAMES.get(base_key,entry.title),
            model=MODELS[c.recipe_model],model_key=c.recipe_model,process=c.process_type.upper(),
            family=case['family'],difference_a=case['difference_a'],
            labels_json=json.dumps(case['labels'],ensure_ascii=False),
            run_ids_json=json.dumps(case['runs']),focus_x=case['focus'][0],focus_y=case['focus'][1],
            context=case['context'],meaning=entry.meaning,low=entry.low,high=entry.high,
            caution=entry.caution,note=recipe_note({**case,'runs':runs}),
            parameter_field=case['field']))
    run_rows=[]
    for key,run in data['runs'].items():
        frames=run['frames']
        # Keep recorded frames only. Seven sampled frames limit mobile memory;
        # 0.001 A rounding has a <=0.00071 A Euclidean coordinate error.
        indices=sorted({round(i*(len(frames)-1)/6) for i in range(7)})
        compact=dict(config=run['config'],frames=[frames[i] for i in indices],
                     captured_mass=run['captured_mass'],removed_mass=run['removed_mass'])
        run_rows.append(dict(id=key,payload_json=json.dumps(rounded(compact),ensure_ascii=False,separators=(',',':'))))
    definitions=[dict(id=key,title=SHORT_NAMES.get(key,entry.title),meaning=entry.meaning,
        low=entry.low,high=entry.high,caution=entry.caution,kind=entry.kind,
        category='공정·계산' if key in HELP else '구조·표시·저장',
        has_svt=any(case['key']==key for case in cases)) for key,entry in {**HELP,**EXTRA}.items()]
    now=datetime.now(timezone.utc).isoformat()
    sources=dict(provider='GFE local production simulator',classification='synthetic modeled fixture',
        executedAt=now,files=['src/gapsim/emulation/help_trench_examples.json.gz',
            'src/gapsim/emulation/parameter_help_trench.py','src/gapsim/emulation/parameter_help.py'],
        evidenceFlow=[dict(title='합성 트랜치와 단일 변수 비교',detail='공개 코드의 TRENCH/NECK/RECESSED 합성 좌표와 정해진 예시 조건. 회사 구조·SEM·사용자 프리셋은 읽지 않음.'),
          dict(title='현재 엔진 실행',detail='experiments/build_help_trench_movies.py; engine SHA256 '+data['engine_sha256']),
          dict(title='비교 범위',detail='각 case의 실제 입력에서 해당 field 하나만 달라지는지 검사. 최종 외곽과 폐공간의 대칭 vertex-to-segment 표본 최대 거리를 difference_a로 기록.'),
          dict(title='보고서 표시 변환',detail='실제 저장 프레임 중 최대 7개 선택, 좌표 0.001 Å 반올림. 보간 형상을 만들지 않음. 각 case 내부 X/Y 공통 축척. Difference는 반올림 전 원본 좌표 기준.')],
        caveats=['실제 막질·장비 검증 결과가 아닌 합성 구조에서의 모델 민감도 비교.',
          '경계 차이는 두 파라미터 값의 민감도이며 정확도·오차·SEM 일치도 점수가 아님.',
          '다른 파라미터 case의 배경 조건은 다를 수 있어 case 사이 차이 크기를 물리 중요도 순위로 해석하지 않음.'])
    existing_id=json.loads(output.read_text(encoding='utf-8')).get('id') if output.exists() else None
    snapshot=dict(id=existing_id or 'report:gfe-final-parameter-validation-20261004',title='GFE ALD·CVD 최종 파라미터 검증',
        surface='report',buildStatus='complete' if complete and matches else 'creating',status='modeled',
        generatedAt=now,filters=[],report=dict(asOf='2026-10-04',audience='공정 엔지니어'),
        verification=dict(engineMatches=matches,engine_sha256=data['engine_sha256'],singleVariableChecked=True,
                          caseCount=len(cases),runCount=len(run_rows),definitionCount=len(definitions)),
        queries={
          'svt_cases':dict(rows=cases,payloadColumns=['labels_json','run_ids_json'],source={**sources,
            'metricDefinitions':[dict(label='최종 경계 표본 차이',definition='저값과 고값의 최종 외곽·폐공간 경계에서 표본 꼭짓점→상대 경계 선분 거리를 양방향 평가한 최대값. Å 단위. 실측 오차가 아님.',componentIds=['svt-viewer','svt-catalog'])]}),
          'svt_runs':dict(rows=run_rows,payloadColumns=['payload_json'],source=sources),
          'parameter_definitions':dict(rows=definitions,source=sources)})
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(snapshot,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print(json.dumps(dict(output=str(output),cases=len(cases),runs=len(run_rows),definitions=len(definitions),bytes=output.stat().st_size,engineMatches=matches)))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--allow-stale',action='store_true')
    parser.add_argument('--complete',action='store_true')
    args=parser.parse_args()
    build(args.output,allow_stale=args.allow_stale,complete=args.complete)
