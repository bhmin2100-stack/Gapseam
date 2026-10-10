"""Compare a saved native GFE run with a supplied frozen research reference.

Input data stays local. This tool does not run the solver, fit a contour, or
modify either input. All reference frames and the final voids must agree.
"""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np


def equal_paths(actual, expected):
    return len(actual)==len(expected) and all(
        np.asarray(a).shape==np.asarray(b).shape and np.array_equal(a,b)
        for a,b in zip(actual,expected))


def compare(replay, reference):
    actual=json.loads(replay.read_text(encoding='utf8'))
    expected=json.loads(reference.read_text(encoding='utf8'))
    result=actual['result']
    steps={step:i for i,step in enumerate(result['frame_steps'])}
    frames=[]
    for frame in expected['frames']:
        i=steps.get(frame['step'])
        a=np.asarray(result['frame_profiles'][i]) if i is not None else np.empty((0,2))
        b=np.asarray(frame['profile'])
        same_shape=a.shape==b.shape
        frames.append(dict(step=frame['step'],same_shape=same_shape,
            max_coordinate_error_a=float(np.max(np.abs(a-b))) if same_shape else None))
    same_voids=equal_paths(result['frame_voids'][-1],expected['voids'])
    complete=result['frame_steps'][-1]==expected['config']['cycles']
    return dict(passed=complete and same_voids and all(f['same_shape'] and f['max_coordinate_error_a']==0 for f in frames),
        cycles=result['frame_steps'][-1],comparisons=frames,same_final_voids=same_voids,
        front_scheme=actual['config'].get('front_scheme'),
        ion_growth_fraction=actual['config'].get('ion_growth_fraction'),
        reference_sha256=hashlib.sha256(reference.read_bytes()).hexdigest(),
        replay=str(replay),reference=str(reference))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--replay',type=Path,required=True)
    p.add_argument('--reference',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    report=compare(args.replay,args.reference)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False))
    raise SystemExit(0 if report['passed'] else 1)
