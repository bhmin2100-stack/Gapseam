"""Physical recipe contracts: user units, transport, saturation and budgets."""
from dataclasses import replace
import math

import numpy as np
import pytest

from gapsim.emulation.trench_depo import TrenchDepoConfig, run_trench_depo, _replace_sweep_config
from gapsim.emulation.incident_presets import sfo31_preset
from gapsim.engine.cvd_transport import CVDTransportConfig, transport_flux
from gapsim.engine.deposition_pipeline import SimulationCanceled, equal_arc_resample
from gapsim.engine.surface_kinetics import build_neutral_kernel, adsorption_coverage, sputtered_redeposition


FLAT=[(-100.,0.),(100.,0.)]
TRENCH=[(-100.,0.),(-25.,0.),(-25.,-100.),(25.,-100.),(25.,0.),(100.,0.)]


def cfg(**kw):
    return replace(TrenchDepoConfig(points=TRENCH,recipe_model='physical_transport_v1',
        cycles=3,angstrom_per_cycle=1.,reparam_ds_a=5.,numerical_step_a=1.,transport_ray_count=16),**kw)


@pytest.mark.parametrize('model',['ideal_conformal_v1','physical_transport_v1'])
@pytest.mark.parametrize('process',['ald','cvd'])
def test_reference_growth_matches_user_units(model,process):
    config=cfg(points=FLAT,recipe_model=model,process_type=process,cycles=7,angstrom_per_cycle=1.3,
               cvd_rate_a_per_s=.7,cvd_duration_s=13.)
    result=run_trench_depo(config)
    assert np.asarray(result.final_profile)[:,1]==pytest.approx(9.1,abs=.01)
    assert result.meta['nominal_dose_a']==pytest.approx(9.1)
    if process=='ald':
        assert result.frame_steps==list(range(8))
        assert result.meta['frame_cycle_counts']==list(range(8))
        assert result.meta['frame_times_s']==[]
    else:
        assert result.meta['frame_times_s'][-1]==pytest.approx(13)
        assert result.meta['frame_cycle_counts']==[]


@pytest.mark.parametrize('model',['legacy_calibrated_v1','ideal_conformal_v1','physical_transport_v1'])
def test_cvd_uses_rate_and_time_not_unused_ald_controls(model):
    one=cfg(recipe_model=model,process_type='cvd',cvd_rate_a_per_s=2.,cvd_duration_s=3.)
    two=replace(one,cycles=700,angstrom_per_cycle=30.)
    a,b=run_trench_depo(one),run_trench_depo(two)
    assert a.final_profile==b.final_profile
    assert a.meta['frame_times_s']==b.meta['frame_times_s']
    assert a.meta['nominal_dose_a']==6.


def test_cvd_equal_supplied_dose_has_same_shape_without_time_dependent_reaction():
    base=cfg(process_type='cvd',cvd_rate_a_per_s=2.,cvd_duration_s=3.)
    a=run_trench_depo(base)
    b=run_trench_depo(replace(base,cvd_rate_a_per_s=.5,cvd_duration_s=12.))
    assert a.final_profile==b.final_profile
    assert a.meta['frame_times_s'][-1]!=b.meta['frame_times_s'][-1]


@pytest.mark.parametrize('process',['ald','cvd'])
@pytest.mark.parametrize('basis,expected',[('gross',1.5),('net_planar',2.)])
def test_planar_net_growth_compensates_removal_exactly_once(process,basis,expected):
    config=cfg(points=FLAT,process_type=process,growth_basis=basis,
        cycles=1,angstrom_per_cycle=2.,cvd_rate_a_per_s=2.,cvd_duration_s=1.,
        sputter_enabled=True,sputter_strength_a_per_cycle=.5,
        sputter_peak_angle_deg=45.,sputter_width_deg=35.)
    result=run_trench_depo(config)
    assert np.asarray(result.final_profile)[:,1]==pytest.approx(expected,abs=.015)
    assert result.meta['planar_net_growth_per_unit']==expected


def test_variable_sticking_kernel_matches_planar_cvd_calibration():
    points=equal_arc_resample(FLAT,5)
    kernel=build_neutral_kernel(points,32)
    computed,audit=kernel.incoming(.1)
    expected,_=transport_flux(points,CVDTransportConfig(sticking=.1,rays=32))
    np.testing.assert_allclose(computed,expected,atol=2e-7)
    assert audit['residual']<=1e-8


@pytest.mark.parametrize('width',[2.,10.,50.])
@pytest.mark.parametrize('rays',[16,32,64])
def test_analytic_sky_resolves_narrow_open_aperture(width,rays):
    points=[(-100.,0.),(-width/2,0.),(-width/2,-100.),(0.,-100.),
            (width/2,-100.),(width/2,0.),(100.,0.)]
    flux,_=build_neutral_kernel(points,rays).incoming(1.)
    expected=(width/2)/math.sqrt(100**2+(width/2)**2)
    assert flux[3]==pytest.approx(expected,rel=1e-5)


def test_ideal_conformal_closed_trench_converges_to_round_offset():
    points=[(-200.,0.),(-20.,0.),(-20.,-100.),(20.,-100.),(20.,0.),(200.,0.)]
    a=run_trench_depo(cfg(points=points,recipe_model='ideal_conformal_v1',
        angstrom_per_cycle=2.,cycles=12,reparam_ds_a=2.,numerical_step_a=1.))
    b=run_trench_depo(cfg(points=points,recipe_model='ideal_conformal_v1',
        angstrom_per_cycle=2.,cycles=12,reparam_ds_a=2.,numerical_step_a=.25))
    expected=math.sqrt(24.**2-20.**2)
    for result in (a,b):
        assert min(y for x,y in result.final_profile)==pytest.approx(expected,abs=.35)
        assert max(y for x,y in result.final_profile)==pytest.approx(24.,abs=.01)
        assert result.meta['deposition_closure_detected']
        assert result.meta['deposition_closure_kind']=='filled'
    assert abs(min(y for x,y in a.final_profile)-min(y for x,y in b.final_profile))<.12


def test_local_step_limit_includes_focused_redeposition():
    result=run_trench_depo(cfg(cycles=2,angstrom_per_cycle=2.,sputter_enabled=True,
        sputter_strength_a_per_cycle=2.,sputter_width_deg=30.,redepo_enabled=True,
        redepo_efficiency_pct=100.,reparam_ds_a=2.,numerical_step_a=1.))
    assert result.meta['max_local_step_a']<=.8+1e-10
    assert result.meta['redepo_total_mass']>0


@pytest.mark.parametrize('model',['legacy_calibrated_v1','ideal_conformal_v1','physical_transport_v1'])
def test_continuation_preserves_sealed_void_geometry(model):
    cavity=[(-10.,-10.),(10.,-10.),(10.,-30.),(-10.,-30.)]
    result=run_trench_depo(cfg(points=FLAT,initial_voids=[cavity],recipe_model=model))
    assert len(result.frame_voids[0])==1
    assert result.frame_voids[0]==result.frame_voids[-1]
    assert result.meta['recipe_config']['initial_voids']==[cavity]


def test_etch_can_reopen_carried_sealed_void():
    cavity=[(-10.,-10.),(10.,-10.),(10.,-30.),(-10.,-30.)]
    result=run_trench_depo(cfg(points=FLAT,initial_voids=[cavity],recipe_model='ideal_conformal_v1',
        angstrom_per_cycle=0.,cycles=1,sputter_enabled=True,sputter_strength_a_per_cycle=15.,
        sputter_peak_angle_deg=0.,sputter_width_deg=80.))
    assert len(result.frame_voids[0])==1
    assert result.frame_voids[-1]==[]
    assert min(y for x,y in result.final_profile)<-25


def test_overlay_display_compaction_does_not_change_transport_budgets(monkeypatch):
    import gapsim.emulation.trench_depo as trench_module
    config=cfg(cycles=1,angstrom_per_cycle=2.,sputter_enabled=True,
        sputter_strength_a_per_cycle=.5,sputter_width_deg=40.,redepo_enabled=True,
        redepo_efficiency_pct=80.,reparam_ds_a=1.,numerical_step_a=.1)
    compact=run_trench_depo(config)
    monkeypatch.setattr(trench_module,'_compact_redepo_overlay_samples',lambda samples,**kw:list(samples))
    full=run_trench_depo(config)
    assert len(full.meta['frame_etch_overlays'][-1])>650
    assert max(map(len,compact.meta['frame_etch_overlays']))<=650
    assert max(map(len,compact.meta['frame_redepo_overlays']))<=650
    assert compact.final_profile==full.final_profile
    for key in ('redepo_total_removed_mass','redepo_total_mass','redepo_total_mass_last',
                'redepo_total_removed_mass_last','redepo_capture_ratio_last'):
        assert compact.meta[key]==full.meta[key]


def test_flat_langmuir_saturation_and_zero_exposure():
    kernel=build_neutral_kernel(FLAT,16)
    for exposure in (0.,.2,1.,5.,15.):
        coverage,audit=adsorption_coverage(kernel,sticking=.2,exposure=exposure)
        np.testing.assert_allclose(coverage,1-math.exp(-exposure),atol=1e-12)
        assert audit['planar_coverage']==pytest.approx(1-math.exp(-exposure))
    low,_=adsorption_coverage(kernel,exposure=10.)
    high,_=adsorption_coverage(kernel,exposure=20.)
    assert max(high-low)<.00005


def test_ald_exposure_reaches_deep_sites_and_is_numerically_converged():
    points=equal_arc_resample(TRENCH,5)
    kernel=build_neutral_kernel(points,32)
    bottom=int(np.argmin(np.asarray(points)[:,1]))
    low,_=adsorption_coverage(kernel,sticking=.5,exposure=.5)
    high,_=adsorption_coverage(kernel,sticking=.5,exposure=8.)
    assert high[bottom]>low[bottom]*3
    coarse,_=adsorption_coverage(kernel,sticking=.5,exposure=3.,integration_step=.25)
    fine,_=adsorption_coverage(kernel,sticking=.5,exposure=3.,integration_step=.05)
    np.testing.assert_allclose(coarse,fine,atol=.002)
    assert np.all(high<=1) and np.all(low>=0)


def test_ald_saturation_resets_only_on_real_cycles():
    a=run_trench_depo(cfg(numerical_step_a=1.))
    b=run_trench_depo(cfg(numerical_step_a=.25))
    assert a.meta['ald_coverage_reset_count']==b.meta['ald_coverage_reset_count']==3
    assert a.frame_steps==b.frame_steps==[0,1,2,3]
    assert b.meta['numerical_steps']>a.meta['numerical_steps']
    assert abs(min(y for x,y in a.final_profile)-min(y for x,y in b.final_profile))<.1


def test_geometry_portability_uses_current_points_not_saved_reference_dimensions():
    a=cfg(deposition_feature_width_a=2.,deposition_feature_depth_a=10000.)
    b=replace(a,deposition_feature_width_a=2000.,deposition_feature_depth_a=1.)
    assert run_trench_depo(a).final_profile==run_trench_depo(b).final_profile
    wide=replace(a,points=[(x*2,y) for x,y in TRENCH])
    a_result,wide_result=run_trench_depo(a),run_trench_depo(wide)
    assert min(y for x,y in wide_result.final_profile)>min(y for x,y in a_result.final_profile)


def test_fragment_budget_and_neutral_reemission_are_separate():
    points=equal_arc_resample(TRENCH,5)
    removed=np.full(len(points),.5)
    deposited,audit=sputtered_redeposition(points,removed,sticking=.8,rays=32)
    assert 0<audit['total_redepo_mass']<audit['total_removed_mass']
    assert audit['total_removed_mass']==pytest.approx(audit['total_redepo_mass']+audit['escaped_mass'])
    assert min(deposited)>=0
    no_fragments=run_trench_depo(cfg(redepo_enabled=True,sputter_enabled=False))
    assert no_fragments.meta['redepo_total_mass']==0.
    assert not no_fragments.meta['redepo_active']


def test_ion_visibility_does_not_depend_on_fragment_capture():
    result=run_trench_depo(cfg(sputter_enabled=True,sputter_strength_a_per_cycle=.3,
                         redepo_enabled=False,redepo_incident_los_enabled=False))
    assert result.meta['redepo_incident_los_enabled']
    assert not result.meta['redepo_active']
    assert result.meta['redepo_total_removed_mass']>0
    legacy=replace(sfo31_preset(),cycles=1,redepo_enabled=False)
    old_result=run_trench_depo(legacy)
    assert old_result.meta['redepo_incident_los_enabled']
    assert old_result.meta['incident_source_model']=='gaussian_cosine_yield_geometric_visibility'


def test_inhibition_is_planar_calibrated_and_geometry_derived():
    base=cfg(points=FLAT,inhibition_enabled=True,inhibitor_exposure=1.)
    result=run_trench_depo(base)
    assert np.asarray(result.final_profile)[:,1]==pytest.approx(3.,abs=.01)
    changed=replace(base,inhibition_penetration_depth_a=1.,inhibition_strength_pct=99.,
                    inhibition_bottom_boost_pct=99.)
    assert run_trench_depo(changed).final_profile==result.final_profile
    trench_result=run_trench_depo(replace(base,points=TRENCH))
    assert trench_result.meta['transport_last']['inhibition']['min_coverage']<1-math.exp(-1)


@pytest.mark.parametrize('process',['ald','cvd'])
def test_zero_run_and_cancellation(process):
    result=run_trench_depo(cfg(process_type=process,cycles=0,cvd_duration_s=0))
    assert result.frame_steps==[0]
    assert result.meta['numerical_steps']==0
    with pytest.raises(SimulationCanceled):
        run_trench_depo(cfg(process_type=process),cancel_check=lambda:True)


@pytest.mark.parametrize('patch',[dict(recipe_model='invalid'),dict(process_type='bad'),
    dict(precursor_sticking=0),dict(ald_exposure=0),dict(growth_basis='bad'),
    dict(transport_ray_count=9),dict(numerical_step_a=0),dict(cvd_duration_s=float('nan'),process_type='cvd')])
def test_invalid_physical_recipe_rejected(patch):
    with pytest.raises(ValueError):run_trench_depo(cfg(**patch))


@pytest.mark.parametrize('field,value',[('cvd_rate_a_per_s',2.),('cvd_duration_s',4.),
    ('precursor_sticking',.5),('ald_exposure',2.),('inhibitor_sticking',.2),
    ('inhibitor_exposure',2.),('numerical_step_a',.5),('transport_ray_count',16)])
def test_physical_fields_support_single_value_splits(field,value):
    changed=_replace_sweep_config(cfg(),field,value)
    assert getattr(changed,field)==value
    if field=='transport_ray_count':assert isinstance(changed.transport_ray_count,int)
