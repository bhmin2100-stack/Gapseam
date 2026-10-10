"""Replay verification must reject changed contours and incomplete runs."""
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    'replay_comparator', Path(__file__).parents[1] / 'tools' / 'compare_sfo31_replay.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_comparator_checks_frames_and_voids(tmp_path):
    profile = [[0., 0.], [1., 2.]]
    reference = {'frames': [{'step': 2, 'profile': profile}],
                 'voids': [profile], 'config': {'cycles': 2}}
    replay = {'result': {'frame_steps': [2], 'frame_profiles': [profile],
                         'frame_voids': [[profile]]}, 'config': {}}
    a, b = tmp_path / 'run.json', tmp_path / 'reference.json'
    b.write_text(json.dumps(reference))
    a.write_text(json.dumps(replay))
    assert module.compare(a, b)['passed']
    replay['result']['frame_profiles'] = [[[0., 0.], [1., 2.01]]]
    a.write_text(json.dumps(replay))
    assert not module.compare(a, b)['passed']
    replay['result']['frame_profiles'] = [profile]
    replay['result']['frame_voids'] = [[]]
    a.write_text(json.dumps(replay))
    assert not module.compare(a, b)['passed']
    replay['result']['frame_steps'] = [1]
    a.write_text(json.dumps(replay))
    assert not module.compare(a, b)['passed']
