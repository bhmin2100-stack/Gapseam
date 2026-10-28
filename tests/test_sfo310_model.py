from dataclasses import asdict, replace

import pytest

from gapsim.emulation import sfo310_model
from gapsim.emulation.sfo31_verified import sfo310_config, verified_sfo31_config
from gapsim.emulation.trench_depo import run_trench_depo


def test_sfo310_uses_nominal_dose_and_does_not_leak_into_sfo31(monkeypatch):
    legacy = replace(verified_sfo31_config(), cycles=3, reparam_ds_a=40.)
    before = asdict(run_trench_depo(legacy))
    seen = []
    response = sfo310_model.growth_response

    def record(state, cfg, values, *, cycle_index):
        adjusted = response(state, cfg, values, cycle_index=cycle_index)
        seen.append((cycle_index, state.meta['_neck_research_nominal_dose_a']))
        return adjusted

    monkeypatch.setattr(sfo310_model, 'growth_response', record)
    cfg = replace(sfo310_config(), cycles=3, reparam_ds_a=40.)
    result = run_trench_depo(cfg)
    assert result.meta['recipe_model'] == 'sfo310_calibrated_v1'
    assert result.meta['nominal_dose_a'] == pytest.approx(3 * .56)
    assert seen
    assert all(dose == pytest.approx(cycle * .56) for cycle, dose in seen)
    assert sfo310_model.nominal_gpc.get() is None
    assert asdict(run_trench_depo(legacy)) == before


def test_sfo310_rejects_cvd_instead_of_misapplying_ald_calibration():
    with pytest.raises(ValueError, match='calibrated for ALD'):
        run_trench_depo(replace(sfo310_config(), process_type='cvd', front_scheme='legacy'))
