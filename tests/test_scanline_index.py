"""Candidate pruning must preserve the original scanline result exactly."""
from dataclasses import replace
import random

import pytest

from gapsim.engine.scanline_index import ScanlineIndex
from gapsim.emulation import trench_depo as engine
from gapsim.emulation.incident_presets import sfo31_preset


@pytest.mark.parametrize('seed', range(8))
def test_random_folded_profiles_match_full_scan(seed):
    rng = random.Random(seed)
    points = [(rng.uniform(-100,100), rng.uniform(-200,20)) for _ in range(120)]
    index = ScanlineIndex(points)
    probes = [p[1]+delta for p in points for delta in (0., -1e-9, 1e-9)]
    probes += [rng.uniform(-250,50) for _ in range(80)]
    for y in probes:
        actual = engine._line_intersections_at_y(points, y,
                                                 segment_candidates=index.candidates(y))
        assert actual == engine._line_intersections_at_y(points, y)


@pytest.mark.parametrize('points', [[], [(0.,0.)], [(0.,0.),(10.,0.)],
    [(0.,0.),(0.,-10.),(10.,-10.),(10.,0.)],
    [(0.,0.),(1.,1e-9),(2.,1.001e-9),(3.,-1e-9)],
    [(0.,0.),(0.,-10.),(0.,0.),(0.,-10.)]])
def test_horizontal_duplicates_and_epsilon_boundaries(points):
    index = ScanlineIndex(points)
    for y in (-10.-1e-9, -10., -1e-9, 0., 1e-9, 1.001e-9, 20.):
        assert engine._line_intersections_at_y(points, y,
            segment_candidates=index.candidates(y)) == engine._line_intersections_at_y(points, y)


def test_long_monotonic_wall_prunes_without_losing_hits():
    points = [(0.,-float(y)) for y in range(10001)]
    index = ScanlineIndex(points)
    hits = index.candidates(-5000.5)
    assert hits == [5000]
    assert engine._line_intersections_at_y(points, -5000.5,
        segment_candidates=hits) == [0.]


def test_complete_inhibited_redep_replay_matches_unindexed_scan(monkeypatch):
    config = replace(sfo31_preset(), cycles=8, reparam_ds_a=10.,
        points=((5000.,0.),(1150.,0.),(1150.,-5000.),
                (-1150.,-5000.),(-1150.,0.),(-5000.,0.)),
        growth_basis='net_planar', angstrom_per_cycle=.56,
        sputter_strength_a_per_cycle=1.86, sputter_width_deg=20.,
        redepo_distance_power=47., redepo_emit_power=8.,
        redepo_max_distance_a=5000., inhibition_enabled=True,
        inhibition_strength_pct=10., inhibition_process_model='peald',
        inhibition_bottom_boost_pct=0., inhibition_peald_recombination_pct=0.)
    optimized = engine.run_trench_depo(config)
    class FullScan:
        def __init__(self, points):
            self.n = len(points)
        def candidates(self, _y):
            return range(self.n-1)
    monkeypatch.setattr(engine, 'ScanlineIndex', FullScan)
    original = engine.run_trench_depo(config)
    assert optimized.frame_steps == original.frame_steps
    assert optimized.frame_profiles == original.frame_profiles
    assert optimized.frame_voids == original.frame_voids
    assert optimized.meta['inhibition_debug_summary_last'] == original.meta['inhibition_debug_summary_last']
    assert optimized.meta['frame_redepo_overlays'] == original.meta['frame_redepo_overlays']
