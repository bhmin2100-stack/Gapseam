"""Per-run reflection boundary for symmetric geometry and centered sources.

This is a numerical constraint, not smoothing or a new physical coefficient.
Legacy callers can select off for exact replay of older calibrations.
"""
import numpy as np
from . import deposition_pipeline as p


def configure(state, mode):
    if mode not in ('auto', 'off'):
        raise ValueError('symmetry_mode must be auto or off')
    center = (state.x_left_i + state.x_right_i) // 2
    representable = 2 * center == state.x_left_i + state.x_right_i
    mirror = [[(2 * center-x, y) for x, y in path[::-1]]
              for path in state.solid_paths_i]
    difference = p._clip_difference(state.solid_paths_i, mirror)
    reverse_difference = p._clip_difference(mirror, state.solid_paths_i)
    # Require exact integer-grid geometry, including all internal voids. Never
    # repair an approximately symmetric or intentionally asymmetric input.
    active = mode == 'auto' and representable and not difference and not reverse_difference
    state.meta['symmetry'] = dict(mode=mode, active=active, axis_a=center/state.scale,
        method='left_half_reflection_boundary', steps=0, max_area_change_a2=0.,
        total_area_change_a2=0.)
    return state.meta['symmetry']


def resample(state, points, ds, base=p.equal_arc_resample):
    sampled = np.asarray(base(points, ds), dtype=float)
    audit = state.meta.get('symmetry', {})
    if audit.get('active') and len(sampled) > 1:
        reflected = sampled[::-1].copy()
        reflected[:, 0] = 2*audit['axis_a']-reflected[:, 0]
        sampled = (sampled+reflected)/2
    return [tuple(point) for point in sampled.tolist()]


def constrain(state, ds):
    audit = state.meta.get('symmetry', {})
    if not audit.get('active'):
        return
    center = round(audit['axis_a'] * state.scale)
    box = [(state.x_left_i, state.y_top_i), (center, state.y_top_i),
           (center, state.y_bot_i), (state.x_left_i, state.y_bot_i)]
    before = p._int_paths_area(state.solid_paths_i)
    left = p._clip_intersection(state.solid_paths_i, [box])
    right = [[(2*center-x, y) for x, y in path[::-1]] for path in left]
    state.solid_paths_i = p._clip_union(left, right)
    change = (p._int_paths_area(state.solid_paths_i)-before)/state.scale**2
    audit['steps'] += 1
    audit['max_area_change_a2'] = max(audit['max_area_change_a2'], abs(change))
    audit['total_area_change_a2'] += change
    surface = p._extract_surface_from_solid(state, state.solid_paths_i, state.surface.points)
    state.surface.points = resample(state, surface, ds)
