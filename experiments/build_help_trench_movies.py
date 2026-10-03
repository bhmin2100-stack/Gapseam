"""Generate bundled help movies from the production simulator, never cartoons.

Run from repository root: .venv/Scripts/python.exe experiments/build_help_trench_movies.py
--keys key1 key2 generates a subset for quick recipe inspection; rerun without
--keys to complete. Compatible results are reused by recipe + engine hash.
"""
from dataclasses import asdict
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from gapsim.emulation import parameter_help_trench as catalog
from gapsim.emulation.trench_depo import run_trench_depo

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT/'src/gapsim/emulation'/catalog.ASSET


def engine_fingerprint():
    paths = sorted((ROOT/'src/gapsim/engine').rglob('*.py')) + [
        ROOT/'src/gapsim/emulation/trench_depo.py',
        ROOT/'src/gapsim/emulation/model4_redeposition.py',
    ]
    h = hashlib.sha256()
    for path in paths:
        h.update(str(path.relative_to(ROOT)).replace('\\', '/').encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def config_id(config):
    return hashlib.sha256(json.dumps(asdict(config), sort_keys=True).encode()).hexdigest()[:20]


def distance_and_focus(a, b):
    """Symmetric vertex-to-segment difference including trapped void outlines."""
    best, focus = 0., (0., 0.)
    for first, second in ((a, b), (b, a)):
        pts = np.array([p for path in first for p in path], dtype=float)
        starts = np.array([p for path in second for p in path[:-1]], dtype=float)
        ends = np.array([p for path in second for p in path[1:]], dtype=float)
        if not len(pts) or not len(starts):
            continue
        ab = ends-starts
        denom = np.maximum(1e-16, np.sum(ab*ab, axis=1))
        for chunk in np.array_split(pts, max(1, len(pts)//64)):
            ap = chunk[:, None, :]-starts[None, :, :]
            t = np.clip(np.sum(ap*ab, axis=2)/denom, 0., 1.)
            d = np.linalg.norm(ap-t[:, :, None]*ab, axis=2).min(axis=1)
            idx = int(d.argmax())
            if d[idx] > best:
                best, focus = float(d[idx]), tuple(float(v) for v in chunk[idx])
    return best, focus


def outlines(run):
    f = run['frames'][-1]
    return [f['profile']] + [loop+[loop[0]] for loop in f['voids'] if loop]


def build(keys=None):
    fingerprint = engine_fingerprint()
    data = dict(version=catalog.VERSION, engine_sha256=fingerprint, runs={}, cases={})
    if OUTPUT.exists():
        previous = json.loads(gzip.decompress(OUTPUT.read_bytes()))
        if previous.get('engine_sha256') == fingerprint and previous.get('version') == catalog.VERSION:
            data['runs'] = previous['runs']
    for key, example in catalog.examples().items():
        if keys and key not in keys:
            continue
        run_ids = []
        for config in example.configs():
            run_id = config_id(config)
            run_ids.append(run_id)
            if run_id in data['runs']:
                continue
            start = time.perf_counter()
            result = run_trench_depo(config)
            indices = sorted(set(round(i*config.cycles/12) for i in range(13)))
            frames = []
            for i in indices:
                frames.append(dict(step=result.frame_steps[i], profile=result.frame_profiles[i],
                    voids=result.frame_voids[i],
                    transport=result.meta.get('frame_transport_lines', [[]]*len(result.frame_steps))[i][:16],
                    etch=result.meta.get('frame_etch_overlays', [[]]*len(result.frame_steps))[i][::3],
                    redepo=result.meta.get('frame_redepo_overlays', [[]]*len(result.frame_steps))[i][::3]))
            data['runs'][run_id] = dict(config=asdict(config), frames=frames,
                captured_mass=result.meta.get('redepo_total_mass_last', 0.),
                removed_mass=result.meta.get('redepo_total_removed_mass_last', 0.))
            print(f'{key}: {example.field}={getattr(config, example.field)} / {time.perf_counter()-start:.2f}s', flush=True)
        a, b = (data['runs'][rid] for rid in run_ids)
        delta, focus = distance_and_focus(outlines(a), outlines(b))
        data['cases'][key] = dict(key=key, field=example.field, family=example.family,
                                 labels=example.labels, runs=run_ids, difference_a=delta, focus=focus)
    used = {rid for case in data['cases'].values() for rid in case['runs']}
    data['runs'] = {key: run for key, run in data['runs'].items() if key in used}
    OUTPUT.write_bytes(gzip.compress(json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode(), mtime=0))
    print(f'{len(data["cases"])} cases, {len(data["runs"])} runs, {OUTPUT.stat().st_size} bytes', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--keys', nargs='+')
    build(parser.parse_args().keys)
