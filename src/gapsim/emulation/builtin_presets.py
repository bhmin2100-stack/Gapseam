"""Shipped, read-only recipe and structure entries, independent of user files."""
from dataclasses import asdict, replace
from .sfo31_verified import verified_sfo31_config, sfo310_config, STRUCTURE_NAME
from .sfo31_verified import SAVED_PRESET_KEY, SAVED_PRESET_KEY_310
from .response_ui import normalized_values
from .depth_formula import MODEL as DEPTH_MODEL, PRESET_LAWS, Parameters

BOTTOM_UP_PRESET = '하부 우선 ALD (시험)'
RECIPE_NAMES = ('SFO3.1', 'SFO3.10', 'SFO3.10-HAR (시험)', 'SFO3.11', *PRESET_LAWS, BOTTOM_UP_PRESET)
# Qt stores these tuple keys as Python objects. Preserve the exported legacy
# objects so callers can still locate an existing user copy with findData().
SAVED_RECIPE_KEYS = dict(zip(RECIPE_NAMES[:2], (SAVED_PRESET_KEY, SAVED_PRESET_KEY_310)))
SAVED_RECIPE_KEYS.update({name: ('saved', name) for name in RECIPE_NAMES[2:]})
STRUCTURE_NAMES = (STRUCTURE_NAME, '사진 구조 CD365 H1839', '테이퍼 Trench CD264 H5000')


def recipe_config(name):
    if name not in RECIPE_NAMES:
        raise KeyError(name)
    if name == BOTTOM_UP_PRESET:
        from .trench_depo import TrenchDepoConfig
        # The same inhibitor + precursor sequence repeats each cycle. Existing
        # Langmuir/transport solver, no depth-polynomial clipping or cavity fill.
        return TrenchDepoConfig(recipe_model='physical_transport_v1',
            process_type='ald', growth_basis='net_planar', angstrom_per_cycle=1., cycles=200,
            precursor_sticking=.01, ald_exposure=10., inhibition_enabled=True,
            inhibitor_sticking=.7, inhibitor_exposure=2., transport_ray_count=32,
            reparam_ds_a=20., numerical_step_a=5.,
            deposition_post_closure_fill_pct_hole=0., deposition_post_closure_fill_pct_line=0.)
    if name in PRESET_LAWS:
        from .trench_depo import TrenchDepoConfig
        return TrenchDepoConfig(recipe_model=DEPTH_MODEL,
            # Revised source-equation unit. Keep Parameters' legacy nm fallback
            # so saved configurations are never silently reinterpreted.
            depth_formula=asdict(Parameters(law=PRESET_LAWS[name], depth_unit='A')),
            process_type='ald', growth_basis='gross', angstrom_per_cycle=1., cycles=550,
            reparam_ds_a=20., numerical_step_a=5.,
            deposition_post_closure_fill_pct_hole=0., deposition_post_closure_fill_pct_line=0.)
    cfg = verified_sfo31_config() if name=='SFO3.1' else sfo310_config()
    values = normalized_values(asdict(cfg))
    if name==RECIPE_NAMES[2]: values['empirical_response']['har_enabled']=True
    if name=='SFO3.11':
        # CD264 taper / 55nm field calibration (2026-11-01). Empirical response;
        # no target contour and no post-closure filling. Geometry stays separate.
        values['empirical_response'].update(
            har_enabled=True, har_growth_floor=1.673,
            har_depth_power=.7, closure_enabled=False,
            har_upper_center_cd=.69, har_upper_halfwidth_cd=.3, har_upper_gain=.4,
            upper_gain=0., relief_center_cd=1.1, relief_halfwidth_cd=.6, relief_gain=.4,
            deep_early_gain=0., deep_middle_gain=0.)
        values['deposition_post_closure_fill_pct_hole']=0.
        values['deposition_post_closure_fill_pct_line']=0.
        values['cycles']=982  # 0.56 A/cycle -> 549.92 A reference-plane growth.
        values['reparam_ds_a']=50.  # Optional numerical default from the HAR replay.
    return replace(cfg, **values)


def recipe_record(name):
    return {'name':name, 'emulator_number':0, 'config':asdict(recipe_config(name))}


def structure_config(name):
    base = verified_sfo31_config()
    if name==STRUCTURE_NAME: return base
    if name==STRUCTURE_NAMES[1]:
        # User-confirmed photo dimensions in nm, converted once to Angstroms.
        cds=(365,192,156,140,159,125,122,119,102,64,37)
        depths=(0,52,95,264,285,295,375,413,799,1680,1839)
        left=[(-cd*5., -depth*10.) for cd,depth in zip(cds,depths)]
        points=((-3650.,0.),*left,*[(-x,y) for x,y in reversed(left)],(3650.,0.))
        return replace(base, points=points, initial_voids=(), deposition_feature_width_a=3650., deposition_feature_depth_a=18390., deposition_feature_length_a=None)
    if name==STRUCTURE_NAMES[2]:
        width,depth,field=2640.,50000.,7920.
        # Measured full CD at each depth, both in nm; mirror about x=0.
        dimensions=((0.,264.),(205.,243.),(504.,231.),(3880.,151.),(5000.,86.))
        left=[(-cd*5.,-z*10.) for z,cd in dimensions]
        points=((-field,0.),*left,*[(-x,y) for x,y in reversed(left)],(field,0.))
        return replace(base, points=points, initial_voids=(), deposition_feature_width_a=width, deposition_feature_depth_a=depth, deposition_feature_length_a=None)
    raise KeyError(name)


def structure_values(name):
    from .parameter_library import GEOMETRY_PARAMETER_FIELDS
    c=asdict(structure_config(name))
    return {k:c[k] for k in GEOMETRY_PARAMETER_FIELDS}
