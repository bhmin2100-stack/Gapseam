"""Shipped, read-only recipe and structure entries, independent of user files."""
from dataclasses import asdict, replace
from .sfo31_verified import verified_sfo31_config, sfo310_config, STRUCTURE_NAME
from .sfo31_verified import SAVED_PRESET_KEY, SAVED_PRESET_KEY_310
from .response_ui import normalized_values

RECIPE_NAMES = ('SFO3.1', 'SFO3.10', 'SFO3.10-HAR (시험)', 'SFO3.11')
# Qt stores these tuple keys as Python objects. Preserve the exported legacy
# objects so callers can still locate an existing user copy with findData().
SAVED_RECIPE_KEYS = dict(zip(RECIPE_NAMES[:2], (SAVED_PRESET_KEY, SAVED_PRESET_KEY_310)))
SAVED_RECIPE_KEYS.update({name: ('saved', name) for name in RECIPE_NAMES[2:]})
STRUCTURE_NAMES = (STRUCTURE_NAME, '사진 구조 CD365 H1839', '깊은 Trench CD230 H5000')


def recipe_config(name):
    if name not in RECIPE_NAMES:
        raise KeyError(name)
    cfg = verified_sfo31_config() if name=='SFO3.1' else sfo310_config()
    values = normalized_values(asdict(cfg))
    if name==RECIPE_NAMES[2]: values['empirical_response']['har_enabled']=True
    if name=='SFO3.11':
        # Frozen width/length candidate (2026-10-31). Empirical response only;
        # no target contour and no post-closure filling. Geometry stays separate.
        values['empirical_response'].update(
            har_enabled=True, har_growth_floor=9.93533549067577,
            har_depth_power=.7, closure_enabled=False,
            upper_gain=0., relief_gain=0., deep_early_gain=0., deep_middle_gain=0.)
        values['deposition_post_closure_fill_pct_hole']=0.
        values['deposition_post_closure_fill_pct_line']=0.
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
        width,depth,field=2300.,50000.,6900.
        points=((-field,0.),(-width/2,0.),(-width/2,-depth),(width/2,-depth),(width/2,0.),(field,0.))
        return replace(base, points=points, initial_voids=(), deposition_feature_width_a=width, deposition_feature_depth_a=depth, deposition_feature_length_a=None)
    raise KeyError(name)


def structure_values(name):
    from .parameter_library import GEOMETRY_PARAMETER_FIELDS
    c=asdict(structure_config(name))
    return {k:c[k] for k in GEOMETRY_PARAMETER_FIELDS}
