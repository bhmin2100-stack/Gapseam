import pytest

from gapsim.engine.cvd_transport import CVDTransportConfig, transport_flux, run_cvd_profile


def trench():
    return [(-100,0),(-25,0),(-25,-25),(-25,-50),(-25,-75),(-25,-100),
            (0,-100),(25,-100),(25,-75),(25,-50),(25,-25),(25,0),(100,0)]


@pytest.mark.parametrize('s',[.02,.2,1.])
def test_planar_growth_is_one(s):
    f,a=transport_flux([(-100,0),(0,0),(100,0)],CVDTransportConfig(sticking=s,rays=32))
    assert f==pytest.approx([1,1,1],abs=1e-8)
    assert a['error_bound']<1e-7


def test_reemission_increases_bottom_supply_without_etching():
    low,a=transport_flux(trench(),CVDTransportConfig(sticking=.02,rays=64))
    high,b=transport_flux(trench(),CVDTransportConfig(sticking=1.,rays=64))
    assert low[6]>high[6]*2
    assert all(0<=v<=1+1e-8 for v in low+high)
    assert low==pytest.approx(list(reversed(low)),abs=1e-7)
    assert high==pytest.approx(list(reversed(high)),abs=1e-7)
    assert a['max_row_sum']<=1+1e-12


def test_directional_planar_calibration():
    f,a=transport_flux([(-100,0),(0,0),(100,0)],CVDTransportConfig(directional_fraction=1,rays=32))
    assert f==pytest.approx([1,1,1],abs=1e-8)


@pytest.mark.parametrize('kw',[{'sticking':0},{'sticking':1.1},{'rays':7},{'directional_fraction':-1}])
def test_invalid_parameters(kw):
    with pytest.raises(ValueError):CVDTransportConfig(**kw)


def test_profile_growth_never_removes_substrate_and_has_sealed_void():
    result=run_cvd_profile(trench(),planar_thickness_a=60,step_a=2,ds_a=5,
                           transport=CVDTransportConfig(sticking=.2,rays=32))
    assert result['audit']['max_substrate_loss_a2']==0
    assert result['audit']['max_solver_error']<1e-7
    assert result['first_closed_thickness_a'] is not None
    areas=[f['void_area_a2'] for f in result['frames'] if f['void_area_a2']>25]
    assert len(areas)>2
    assert min(areas)==pytest.approx(max(areas),abs=.001)


def test_planar_evolution_matches_nominal_thickness():
    result=run_cvd_profile([(-100,0),(100,0)],planar_thickness_a=10,step_a=2,ds_a=10)
    assert [y for x,y in result['frames'][-1]['profile']]==pytest.approx([10]*len(result['frames'][-1]['profile']),abs=.01)
