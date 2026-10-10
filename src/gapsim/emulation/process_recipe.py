"""ALD/CVD recipe execution with physical units separate from solver steps.

Three versioned models share one recipe interface. The calibrated legacy model
replays historical SFO3.1; the ideal conformal model is a uniform-growth limit;
the transport model adds collisionless neutral supply and ALD site saturation.
All are feature-scale effective models, not reactor/plasma chemistry solvers.
"""
from __future__ import annotations

from dataclasses import asdict, replace
import math

import numpy as np

from gapsim.engine.deposition_pipeline import (
    OffsetBoolean, SimulationCanceled, TopologyCleanup, VertexNormalPropagator,
    _clip_difference, _clip_intersection, _extract_surface_from_solid, _int_paths_area,
    equal_arc_resample, init_simulation_state,
)
from gapsim.engine.incident_ions import source_integral
from gapsim.engine.surface_kinetics import (
    adsorption_coverage, build_neutral_kernel, sputtered_redeposition,
)

RECIPE_MODELS = ('legacy_calibrated_v1', 'ideal_conformal_v1', 'physical_transport_v1')


def apply_initial_voids(state,voids):
    """Restore geometric voids from a preceding stage, independent of recipe."""
    paths=[]
    for polygon in voids:
        if len(polygon)<3 or not all(len(p)==2 and all(math.isfinite(float(v)) for v in p) for p in polygon):
            raise ValueError('Initial voids require finite polygons with at least three points')
        paths.append([(round(float(x)*state.scale),round(float(y)*state.scale)) for x,y in polygon])
    if paths:
        state.solid_paths_i=_clip_difference(state.solid_paths_i,paths)
        state.surface.points=_extract_surface_from_solid(state,state.solid_paths_i,state.surface.points)


def _finite(value, name, *, positive=False):
    value=float(value)
    if not math.isfinite(value) or (value <= 0 if positive else value < 0):
        raise ValueError(f'{name} must be finite and {"positive" if positive else "nonnegative"}')
    return value


def recipe_nominal_dose(config):
    """Reference-plane amount in Angstrom, never a trench-local thickness."""
    if config.process_type == 'cvd':
        return _finite(config.cvd_rate_a_per_s,'CVD rate')*_finite(config.cvd_duration_s,'CVD duration')
    if config.process_type != 'ald':
        raise ValueError('process_type must be ald or cvd')
    if isinstance(config.cycles,bool) or int(config.cycles)!=config.cycles or config.cycles<0:
        raise ValueError('ALD cycles must be a nonnegative integer')
    return int(config.cycles)*_finite(config.angstrom_per_cycle,'ALD GPC')


def _planar_legacy_etch(config):
    if not config.sputter_enabled or int(config.emulator_number or 0) not in (0, 2, 3, 6):
        return 0.
    amplitude=config.sputter_strength_a_per_cycle*config.sputter_peak_pct/100.
    if config.redepo_incident_los_enabled:
        return float(source_integral([(-1.,0.),(1.,0.)],[(0.,1.)]*2,
            sigma=config.redepo_incident_sigma_deg,rays=config.redepo_incident_ray_count,
            peak=config.sputter_peak_angle_deg,width=config.sputter_width_deg,amplitude=amplitude)[1][0])
    return amplitude*math.exp(-.5*(config.sputter_peak_angle_deg/config.sputter_width_deg)**2)


def _planar_legacy_growth_ratio(config):
    """Use the same inhibition field as the solver on its reference plane."""
    if not config.inhibition_enabled or int(config.emulator_number or 0) not in (0, 5):
        return 1.
    from .trench_depo import compute_inhibition_deposition_factors
    names = ('inhibition_strength_pct', 'inhibition_penetration_depth_a',
             'inhibition_decay_power', 'inhibition_min_growth_ratio',
             'inhibition_bottom_boost_pct', 'inhibition_peald_recombination_pct',
             'inhibition_smoothing_a')
    ratio = float(compute_inhibition_deposition_factors(
        [(-1., 0.), (1., 0.)], process_model=config.inhibition_process_model,
        **{name: _finite(getattr(config, name), name) for name in names})[0])
    if not math.isfinite(ratio) or ratio < 1e-8:
        raise ValueError('Planar inhibition leaves too little growth to calibrate net GPC')
    return ratio


def dispatch_recipe(config, *, progress_cb=None, detail_cb=None, cancel_check=None):
    """Return a recipe result, or None to execute the byte-compatible old path."""
    if config.recipe_model not in RECIPE_MODELS:
        raise ValueError(f'Unsupported recipe model: {config.recipe_model}')
    if config.growth_basis not in ('gross','net_planar'):
        raise ValueError('growth_basis must be gross or net_planar')
    dose=recipe_nominal_dose(config)
    if config.recipe_model != 'legacy_calibrated_v1':
        return run_physical_recipe(config,progress_cb=progress_cb,detail_cb=detail_cb,cancel_check=cancel_check)
    if config.process_type == 'ald' and config.growth_basis == 'gross':
        return None
    from .trench_depo import run_trench_depo
    if config.process_type == 'cvd':
        duration=_finite(config.cvd_duration_s,'CVD duration')
        max_step=_finite(config.numerical_step_a,'numerical step',positive=True)
        removal=_finite(config.sputter_strength_a_per_cycle,'etch rate') if config.sputter_enabled else 0.
        count=max(1,math.ceil(max(dose,removal*duration)/max_step)) if duration else 0
        dt=duration/count if count else 0.
        inner=replace(config,process_type='ald',growth_basis='gross',cycles=count,
                      angstrom_per_cycle=config.cvd_rate_a_per_s*dt,
                      sputter_strength_a_per_cycle=removal*dt)
    else:
        count=config.cycles;dt=None
        inner=replace(config,growth_basis='gross')
    if config.growth_basis == 'net_planar':
        inner=replace(inner,angstrom_per_cycle=(inner.angstrom_per_cycle+_planar_legacy_etch(inner))
                      /_planar_legacy_growth_ratio(inner))
    result=run_trench_depo(inner,progress_cb=progress_cb,detail_cb=detail_cb,cancel_check=cancel_check)
    metadata=dict(result.meta,process_type=config.process_type,recipe_model=config.recipe_model,
                  recipe_config=asdict(config),
                  growth_basis=config.growth_basis,nominal_dose_a=dose,
                  cvd_rate_a_per_s=config.cvd_rate_a_per_s,cvd_duration_s=config.cvd_duration_s,
                  frame_times_s=[i*dt for i in result.frame_steps] if dt is not None else [],
                  frame_cycle_counts=result.frame_steps if dt is None else [],
                  frame_doses_a=[dose*i/count if count else 0. for i in result.frame_steps],
                  numerical_steps=count)
    return replace(result,meta=metadata)


def _arc_fraction(points):
    distances=np.linalg.norm(np.diff(np.asarray(points),axis=0),axis=1)
    arc=np.concatenate(([0.],np.cumsum(distances)))
    return arc/max(float(arc[-1]),1e-20)


def _growth_ratios(points,config,*,cancel_check=None):
    physical=config.recipe_model == 'physical_transport_v1'
    needs_transport=physical or config.inhibition_enabled
    kernel=build_neutral_kernel(points,config.transport_ray_count,cancel_check=cancel_check) if needs_transport else None
    audit={}
    available=np.ones(len(points));planar_available=1.;inhibition_audit=None
    if config.inhibition_enabled:
        coverage,inhibition_audit=adsorption_coverage(kernel,sticking=config.inhibitor_sticking,
            exposure=config.inhibitor_exposure,cancel_check=cancel_check)
        available=np.maximum(0.,1-coverage)
        planar_available=math.exp(-config.inhibitor_exposure)
        if planar_available<1e-8:
            raise ValueError('Inhibitor exposure leaves too few planar sites to calibrate growth')
    if not physical:
        ratios=np.ones(len(points))
    elif config.process_type=='ald':
        if config.ald_exposure <= 0:
            raise ValueError('ALD exposure must be positive for a calibrated GPC')
        coverage,audit=adsorption_coverage(kernel,sticking=config.precursor_sticking,
                                          exposure=config.ald_exposure,site_availability=available,
                                          cancel_check=cancel_check)
        ratios=coverage/audit['planar_coverage']
    else:
        ratios,audit=kernel.incoming(config.precursor_sticking*available,cancel_check=cancel_check)
    if config.inhibition_enabled:
        # GPC/rate is measured on the exposed reference plane at this recipe.
        # Therefore suppression of that plane is included exactly once.
        ratios*=available/planar_available
        audit=dict(audit,inhibition=inhibition_audit)
    return ratios,audit


def _ion_ratio(points,config):
    normals=VertexNormalPropagator._vertex_air_normals(points)
    parameters=dict(sigma=config.redepo_incident_sigma_deg,rays=config.redepo_incident_ray_count,
                    peak=config.sputter_peak_angle_deg,width=config.sputter_width_deg)
    _,exposed,flux=source_integral(points,normals,**parameters)
    planar=float(source_integral([(-1.,0.),(1.,0.)],[(0.,1.)]*2,**parameters)[1][0])
    if planar<1e-10:
        raise ValueError('Angular yield is negligible on the reference plane; change yield angle/width')
    return exposed/planar,flux


def _advance_surface(state,deltas,ds):
    if min(deltas)>=0 and float(np.ptp(deltas))<=1e-12:
        # The legacy fixed 0.25A arc tolerance is deliberately left unchanged.
        # New numerical refinement also refines circle tessellation, otherwise
        # many tiny offsets converge to a faceted rather than circular front.
        amount=float(deltas[0])
        solid=OffsetBoolean.grow_solid_external_air_limited(state,dr_ref=amount,
                             arc_tolerance_a=min(.005,max(amount*.002,1/state.scale)))
        clean=_extract_surface_from_solid(state,solid,state.surface.points)
        state.solid_paths_i=solid
        state.surface.points=equal_arc_resample(clean,ds)
        return
    proposed=VertexNormalPropagator().advance(state.surface.points,deltas,1.)
    trapped=OffsetBoolean.collect_void_air(state)
    clean,solid=TopologyCleanup().cleanup(proposed,state,
                     solid_merge_mode='candidate' if min(deltas)<-1e-12 else 'union')
    if trapped:
        solid=_clip_difference(solid,trapped)
        clean=_extract_surface_from_solid(state,solid,clean)
    state.solid_paths_i=solid
    state.surface.points=equal_arc_resample(clean,ds)


def run_physical_recipe(config,*,progress_cb=None,detail_cb=None,cancel_check=None):
    from .trench_depo import TrenchDepoResult, _compact_redepo_overlay_samples
    dose=recipe_nominal_dose(config)
    ds=_finite(config.reparam_ds_a,'surface spacing',positive=True)
    numerical_step=_finite(config.numerical_step_a,'numerical step',positive=True)
    rate=_finite(config.angstrom_per_cycle if config.process_type=='ald' else config.cvd_rate_a_per_s,'growth')
    etch_rate=_finite(config.sputter_strength_a_per_cycle,'planar etch') if config.sputter_enabled else 0.
    gross_rate=rate+(etch_rate if config.growth_basis=='net_planar' else 0.)
    for value,name in [(config.precursor_sticking,'precursor sticking'),(config.inhibitor_sticking,'inhibitor sticking')]:
        if not math.isfinite(value) or not 0<value<=1:
            raise ValueError(f'{name} must be in (0, 1]')
    _finite(config.ald_exposure,'ALD exposure')
    _finite(config.inhibitor_exposure,'inhibitor exposure')
    if not 0<=config.redepo_efficiency_pct<=100:
        raise ValueError('fragment sticking percent must be in [0, 100]')
    if int(config.transport_ray_count)!=config.transport_ray_count or config.transport_ray_count<8 or config.transport_ray_count%2:
        raise ValueError('transport rays must be an even integer >= 8')
    is_ald=config.process_type=='ald'
    duration=float(config.cycles) if is_ald else _finite(config.cvd_duration_s,'CVD duration')
    outer_count=config.cycles if is_ald else max(1,math.ceil(duration*max(gross_rate,etch_rate)/numerical_step)) if duration else 0
    outer_dt=1. if is_ald else duration/outer_count if outer_count else 0.
    state=init_simulation_state(config.points,units='A',reparam_ds_a=ds)
    apply_initial_voids(state,config.initial_voids)
    from gapsim.engine.symmetry import configure, constrain
    configure(state, config.symmetry_mode)
    constrain(state, ds)
    initial_y_min=min(y for x,y in state.surface.points)
    initial_y_max=max(y for x,y in state.surface.points)
    internal_rectangle=[(state.x_left_i,round(initial_y_min*state.scale)),
                        (state.x_right_i,round(initial_y_min*state.scale)),
                        (state.x_right_i,round(initial_y_max*state.scale)),
                        (state.x_left_i,round(initial_y_max*state.scale))]
    initial_trench_air=_clip_difference([internal_rectangle],state.solid_paths_i) if initial_y_max>initial_y_min else []
    state.surface.points=equal_arc_resample(state.surface.points,ds)
    profiles=[list(state.surface.points)];voids=[OffsetBoolean.void_polygons_float(state)]
    steps=[0];times=[0.];doses=[0.];redepo_overlays=[[]];etch_overlays=[[]];transport_lines=[[]]
    total_removed=total_redeposited=0.;numerical_steps=0;first_closed=None;max_local_step=0.;closure_kind=None
    last_audit={};last_budget={};last_ion_flux=[]
    if progress_cb:progress_cb(0,outer_count)
    for outer in range(outer_count):
        if cancel_check and cancel_check():raise SimulationCanceled()
        reference=list(state.surface.points)
        ratios,last_audit=_growth_ratios(reference,config,cancel_check=cancel_check)
        arc=_arc_fraction(reference)
        ion_max=float(max(_ion_ratio(reference,config)[0])) if etch_rate else 0.
        bound=max(gross_rate*float(max(ratios)),etch_rate*ion_max)
        local_limit=min(numerical_step,.4*ds)
        substeps=max(1,math.ceil(outer_dt*bound/local_limit))
        proposed_increment=outer_dt/substeps
        remaining=outer_dt
        substep=0
        cycle_redepo=[];cycle_etch=[];cycle_lines=[]
        while remaining>max(outer_dt*1e-12,1e-15):
            if cancel_check and cancel_check():raise SimulationCanceled()
            increment=min(proposed_increment,remaining)
            points=state.surface.points
            # One ALD site state per actual cycle, not one reset per solver step.
            local=np.interp(_arc_fraction(points),arc,ratios)
            if not is_ald and substep:
                local,last_audit=_growth_ratios(points,config,cancel_check=cancel_check)
            growth=gross_rate*increment*local
            removed=np.zeros(len(points));redeposited=np.zeros(len(points))
            if etch_rate:
                ion,last_ion_flux=_ion_ratio(points,config)
                removed=etch_rate*increment*ion
                redeposited,last_budget=sputtered_redeposition(points,removed,
                    sticking=config.redepo_efficiency_pct/100. if config.redepo_enabled else 0.,
                    rays=config.transport_ray_count,cancel_check=cancel_check)
            component_max=max(float(max(growth+redeposited)),float(max(removed)))
            if component_max>local_limit:
                scale=local_limit/component_max
                increment*=scale;growth*=scale;removed*=scale;redeposited*=scale
                if etch_rate:
                    for key in ('total_removed_mass','total_redepo_mass','escaped_mass','conservation_error'):
                        last_budget[key]*=scale
                    last_budget['transport_lines']=[line[:4]+[line[4]*scale] for line in last_budget['transport_lines']]
            if etch_rate:
                total_removed+=last_budget['total_removed_mass'];total_redeposited+=last_budget['total_redepo_mass']
                cycle_etch.extend([[float(x),float(y),float(v)] for (x,y),v in zip(points,removed) if v>1e-10])
                cycle_redepo.extend([[float(x),float(y),float(v)] for (x,y),v in zip(points,redeposited) if v>1e-10])
                cycle_lines.extend(last_budget['transport_lines'][:16])
            delta=growth+redeposited-removed
            max_local_step=max(max_local_step,float(np.max(np.abs(delta))))
            _advance_surface(state,delta,ds)
            constrain(state, ds)
            numerical_steps+=1
            remaining=max(0.,remaining-increment)
            substep+=1
            if detail_cb:detail_cb(dict(kind='recipe_substep',process_type=config.process_type,
                 step=outer,substep=substep,substeps=max(substeps,substep),total=outer_count,points=len(points)))
        elapsed=(outer+1)*outer_dt
        steps.append(outer+1);times.append(elapsed);doses.append(rate*elapsed)
        profiles.append(list(state.surface.points));voids.append(OffsetBoolean.void_polygons_float(state))
        # Movie overlays are display samples. Scalar transport budgets above
        # retain every source/target contribution independently of this cap.
        redepo_overlays.append(_compact_redepo_overlay_samples(cycle_redepo,max_points=650))
        etch_overlays.append(_compact_redepo_overlay_samples(cycle_etch,max_points=650))
        transport_lines.append(cycle_lines[:128])
        area=_int_paths_area(OffsetBoolean.collect_void_air(state))/state.scale**2
        if first_closed is None:
            open_initial_air=_clip_intersection(OffsetBoolean.collect_external_air(state),initial_trench_air) if initial_trench_air else []
            filled=bool(initial_trench_air) and _int_paths_area(open_initial_air)/state.scale**2<1e-5
            if area>ds*ds or filled:
                first_closed=outer+1
                closure_kind='sealed_void' if area>1e-5 else 'filled'
        if progress_cb:progress_cb(outer+1,outer_count)
    metadata=dict(version=2,units={'length':'A','y_down_is_negative':True},
        symmetry=dict(state.meta.get('symmetry', {})),
        process_type=config.process_type,recipe_model=config.recipe_model,growth_basis=config.growth_basis,
        recipe_config=asdict(config),
        growth_model=config.recipe_model,propagation='surface_normal_transport',
        cycles=outer_count,angstrom_per_cycle=config.angstrom_per_cycle,
        cvd_rate_a_per_s=config.cvd_rate_a_per_s,cvd_duration_s=config.cvd_duration_s,
        nominal_dose_a=dose,frame_times_s=[] if is_ald else times,
        frame_cycle_counts=steps if is_ald else [],frame_doses_a=doses,
        numerical_steps=numerical_steps,numerical_step_a=numerical_step,reparam_ds_a=ds,
        max_local_step_a=max_local_step,transport_last=last_audit,
        ald_planar_coverage=-math.expm1(-config.ald_exposure) if is_ald and config.recipe_model=='physical_transport_v1' else None,
        ald_coverage_reset_count=outer_count if is_ald else 0,
        precursor_reemission_model='neutral_diffuse_site_balance' if config.recipe_model=='physical_transport_v1' else 'off',
        sputter_enabled=config.sputter_enabled,sputter_active=bool(etch_rate),
        sputter_model='planar_calibrated_gaussian_yield_geometric_visibility' if etch_rate else 'off',
        redepo_incident_los_enabled=bool(etch_rate),incident_source_model='gaussian_cosine_yield_geometric_visibility',
        redepo_enabled=config.redepo_enabled,redepo_active=total_redeposited>0,
        redepo_model='cosine_first_hit_single_flight' if config.redepo_enabled else 'off',
        redepo_total_removed_mass=total_removed,redepo_total_mass=total_redeposited,
        redepo_total_removed_mass_last=last_budget.get('total_removed_mass',0.),
        redepo_total_mass_last=last_budget.get('total_redepo_mass',0.),
        redepo_capture_ratio_last=last_budget.get('capture_ratio',0.),
        redepo_debug_summary_last=last_budget,frame_redepo_overlays=redepo_overlays,
        overlay_sampling='display_only_above_10pct_frame_peak_max650_samples',
        frame_etch_overlays=etch_overlays,frame_transport_lines=transport_lines,
        deposition_closure_detected=first_closed is not None,deposition_closure_step=first_closed,
        deposition_closure_kind=closure_kind,
        inhibition_enabled=config.inhibition_enabled,inhibition_model='transported_langmuir_blocked_sites' if config.inhibition_enabled else 'off',
        planar_growth_input_basis=config.growth_basis,
        planar_gross_growth_per_unit=gross_rate,planar_etch_per_unit=etch_rate,
        planar_net_growth_per_unit=gross_rate-etch_rate,
        limitations=['2D collisionless effective model','ALD co-reactant conversion assumed complete',
                     'ALD geometry frozen for adsorption within one cycle','no gas phase chemistry or ion energy solver',
                     'inhibitor coverage is effective per-cycle/quasi-steady, no desorption history'])
    return TrenchDepoResult(frame_steps=steps,frame_profiles=profiles,frame_voids=voids,
                           final_profile=list(state.surface.points),meta=metadata)
