"""Pruned footprint lists must be bit-for-bit identical to the original sums."""
from bisect import bisect_left, bisect_right
from dataclasses import replace
import math
import random

import pytest

from gapsim.engine.reflection_footprint import ReflectionFootprintIndex
from gapsim.emulation import trench_depo as engine
from gapsim.emulation.incident_presets import sfo31_preset


class OriginalFootprint:
    def __init__(self, points, normals, arc_coordinates, areas, center_x):
        self.points, self.normals, self.arc = points, normals, arc_coordinates
        self.areas, self.center_x = areas, center_x

    def weights(self, *, hit_side, hit_arc, sigma, radius):
        target_weights = []
        left = bisect_left(self.arc, hit_arc-radius)
        right = bisect_right(self.arc, hit_arc+radius)
        for target_idx in range(left, right):
            tx, _ty = self.points[target_idx]
            if target_idx >= len(self.arc):
                continue
            if (-1 if float(tx) < self.center_x else 1) != hit_side:
                continue
            if target_idx < len(self.normals) and abs(float(self.normals[target_idx][0])) < .12:
                continue
            ds = abs(float(self.arc[target_idx])-hit_arc)
            if ds > radius:
                continue
            weight = self.areas[target_idx]*math.exp(-.5*(ds/max(sigma, 1e-9))**2)
            if weight > 0.:
                target_weights.append((target_idx, weight))
        return target_weights


@pytest.mark.parametrize('seed', range(8))
def test_scalar_weights_and_sum_match_exactly(seed):
    rng = random.Random(seed)
    points = [(rng.choice([-1.,0.,1.])*rng.random()*100, rng.random()*50) for _ in range(150)]
    normals = [(rng.choice([0., .119999, .12, .120001, -.12, 1.]),1.) for _ in points]
    arc = engine._model6_arc_coordinates(points)
    areas = [rng.uniform(1e-9,100) for _ in points]
    original = OriginalFootprint(points, normals, arc, areas, 0.)
    optimized = ReflectionFootprintIndex(points, normals, arc, areas, 0.)
    for _ in range(40):
        kwargs = dict(hit_side=rng.choice([-1,1]), hit_arc=rng.uniform(-100,arc[-1]+100),
                      sigma=rng.choice([0.,1e-12,1.,100.,1000.]), radius=rng.uniform(0,2000))
        expected = original.weights(**kwargs)
        actual = optimized.weights(**kwargs)
        assert actual == expected
        assert sum(w for _,w in actual) == sum(w for _,w in expected)


@pytest.mark.parametrize('efficiency', [0.,90.])
def test_complete_redep_frames_and_budget_match_original(monkeypatch, efficiency):
    cfg = replace(sfo31_preset(), cycles=8, reparam_ds_a=10.,
        points=((5000.,0.),(1150.,0.),(1150.,-5000.),
                (-1150.,-5000.),(-1150.,0.),(-5000.,0.)),
        growth_basis='net_planar', angstrom_per_cycle=.56,
        sputter_strength_a_per_cycle=1.86, sputter_width_deg=20.,
        redepo_distance_power=47., redepo_emit_power=8.,
        redepo_max_distance_a=5000., redepo_efficiency_pct=efficiency)
    optimized = engine.run_trench_depo(cfg)
    monkeypatch.setattr(engine,'ReflectionFootprintIndex',OriginalFootprint)
    original = engine.run_trench_depo(cfg)
    assert optimized.frame_profiles == original.frame_profiles
    assert optimized.frame_voids == original.frame_voids
    assert optimized.meta['frame_redepo_overlays'] == original.meta['frame_redepo_overlays']
    assert optimized.meta['redepo_debug_summary_last'] == original.meta['redepo_debug_summary_last']
