import pytest
from gapsim.emulation.trench_depo import TrenchDepoConfig,run_trench_depo
from gapsim.emulation.trench_depo_export import result_to_payload,payload_to_trench_run


@pytest.mark.parametrize('mode',['auto','off'])
def test_new_replay_retains_explicit_boundary(mode):
    config=TrenchDepoConfig(cycles=0,symmetry_mode=mode)
    payload=result_to_payload(config,run_trench_depo(config),request_note='')
    restored,result,note=payload_to_trench_run(payload)
    assert restored.symmetry_mode==mode
    assert result.final_profile==run_trench_depo(config).final_profile


def test_old_replay_continuation_does_not_change_boundary():
    config=TrenchDepoConfig(cycles=0,symmetry_mode='off')
    payload=result_to_payload(config,run_trench_depo(config),request_note='')
    del payload['config']['symmetry_mode']
    restored,result,note=payload_to_trench_run(payload)
    assert restored.symmetry_mode=='off'
