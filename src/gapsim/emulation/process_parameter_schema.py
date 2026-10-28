"""Lossless parameter-tree adapter used to evaluate the proposed organization.

UI category is deliberately independent of preset application policy: moving
calibration smoothing to Numerical must not make it optional on preset load.
The name is descriptive only, never an engine switch. The desktop editor uses
the same explicit response block and preserves old records on read.
"""
from dataclasses import asdict
from copy import deepcopy
from .trench_depo import TrenchDepoConfig
from .calibrated_response import MODEL, ResponseParameters, parameters
from .parameter_library import GEOMETRY_PARAMETER_FIELDS

VERSION = 1
NUMERICAL = frozenset({
    'symmetry_mode','reparam_ds_a','front_scheme','sputter_smoothing_a',
    'inhibition_smoothing_a','redepo_incident_ray_count','redepo_ray_count',
    'redepo_neighbor_exclusion','redepo_max_distance_a','redepo_soft_los_radius_points',
    'redepo_footprint_radius_sigma','transport_ray_count','numerical_step_a',
    'deposition_max_depo_per_cell_a','deposition_closure_threshold_a',
})
PROCESS = frozenset({'process_type','growth_basis','cycles','angstrom_per_cycle',
                     'cvd_rate_a_per_s','cvd_duration_s'})
GROUPS = ('process','growth','etch_redeposition','inhibition','numerical','advanced','structure')


def group_for(key):
    if key in GEOMETRY_PARAMETER_FIELDS:return 'structure'
    if key in NUMERICAL:return 'numerical'
    if key in PROCESS:return 'process'
    if key.startswith(('deposition_post_closure','deposition_line_open','deposition_residual','lf_','closure_','reflected_')):
        return 'advanced'
    if key in ('inhibition_bottom_boost_pct','inhibition_peald_recombination_pct'):
        return 'growth'
    if key.startswith(('sputter_','redepo_','ion_transmission_')):return 'etch_redeposition'
    if key.startswith(('inhibition_','inhibitor_')):return 'inhibition'
    if key.startswith(('deposition_','cvd_','precursor_','ald_','ion_growth')) or key=='recipe_model':return 'growth'
    return 'advanced'


def to_parameter_tree(config, *, name='User recipe'):
    values=asdict(config)
    model=config.recipe_model
    if model=='sfo310_calibrated_v1' or (model=='legacy_calibrated_v1' and config.process_type=='ald'):
        response=parameters(config) if model=='sfo310_calibrated_v1' else ResponseParameters()
        values['empirical_response']=asdict(response)
        values['recipe_model']=MODEL
    groups={group:{} for group in GROUPS}
    for key,value in values.items():groups[group_for(key)][key]=deepcopy(value)
    return dict(schema_version=VERSION,name=str(name),groups=groups)


def from_parameter_tree(document):
    if document.get('schema_version')!=VERSION:raise ValueError('Unsupported parameter tree version')
    groups=document.get('groups')
    if not isinstance(groups,dict) or set(groups)!=set(GROUPS):raise ValueError('Parameter tree groups are incomplete')
    values={}
    for group,items in groups.items():
        if not isinstance(items,dict):raise ValueError('Parameter groups must be objects')
        for key,value in items.items():
            if key in values:raise ValueError(f'Duplicate parameter: {key}')
            if group_for(key)!=group:raise ValueError(f'Wrong parameter group: {key}')
            values[key]=deepcopy(value)
    required=set(TrenchDepoConfig.__dataclass_fields__)
    if set(values)!=required:raise ValueError(f'Missing/unknown parameters: {sorted(required^set(values))}')
    values['points']=tuple(tuple(p) for p in values['points'])
    values['initial_voids']=tuple(tuple(tuple(p) for p in poly) for poly in values['initial_voids'])
    return TrenchDepoConfig(**values)
