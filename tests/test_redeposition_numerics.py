import math
import random
import unittest
from dataclasses import replace

from gapsim.engine.segment_index import SegmentIndex
from gapsim.engine.profile_regularization import damp_mesh_oscillations, fair_profile_implicit
from gapsim.emulation.trench_depo import (
    _model6_first_opposite_reflection_hit, vertex_air_normals,
    TrenchDepoConfig, run_trench_depo,
)


class RedepositionNumericsTest(unittest.TestCase):
    @staticmethod
    def signed_area(points):
        return .5*math.fsum(x*v-y*u for (x,y),(u,v) in zip(points,points[1:]+points[:1]))

    def test_implicit_fairing_reduces_ripple_preserves_area_and_broad_peak(self):
        clean = [(float(i),20*math.exp(-((i-100)/30)**2)) for i in range(201)]
        noisy = [(x,y+.15*math.sin(2*math.pi*x/10)) for x,y in clean]
        # 10 A ripple versus a 60 A-wide intended bulge: separated scales.
        filtered = fair_profile_implicit(noisy,length_a=3.)
        before = sum((noisy[i][1]-clean[i][1])**2 for i in range(20,181))
        after = sum((filtered[i][1]-clean[i][1])**2 for i in range(20,181))
        self.assertLess(after,before*.1)
        self.assertAlmostEqual(self.signed_area(filtered),self.signed_area(noisy),places=7)
        self.assertAlmostEqual(filtered[100][1],clean[100][1],delta=.05)
        self.assertEqual(filtered[0],noisy[0])
        self.assertEqual(filtered[-1],noisy[-1])

    def test_implicit_fairing_nonuniform_straight_and_corners_are_fixed(self):
        line = [(float(i*i), float(2*i*i)) for i in range(20)]
        self.assertEqual(fair_profile_implicit(line),line)
        corner = [(0.,0.),(1.,0.),(2.,0.),(2.,-1.),(2.,-2.),(2.,-3.)]
        self.assertEqual(fair_profile_implicit(corner),corner)
        self.assertEqual(fair_profile_implicit(corner,length_a=0),corner)
        self.assertEqual(fair_profile_implicit([]),[])

    def test_implicit_fairing_reversal_and_translation_invariance(self):
        points = [(i*2., 8*math.sin(i/8)+.1*math.cos(i*2)) for i in range(70)]
        result = fair_profile_implicit(points,length_a=8)
        reverse = fair_profile_implicit(points[::-1],length_a=8)[::-1]
        translated = fair_profile_implicit([(x+500,y-300) for x,y in points],length_a=8)
        for a,b,c in zip(result,reverse,translated):
            self.assertAlmostEqual(a[0],b[0],places=7)
            self.assertAlmostEqual(a[1],b[1],places=7)
            self.assertAlmostEqual(a[0],c[0]-500,places=7)
            self.assertAlmostEqual(a[1],c[1]+300,places=7)

    def test_bvh_matches_exhaustive_ray_hits_on_concave_surface(self):
        points = [(500.,0.), (180.,0.), (160.,-80.), (210.,-200.),
                  (170.,-400.), (100.,-800.), (-100.,-800.),
                  (-170.,-400.), (-210.,-200.), (-160.,-80.), (-180.,0.), (-500.,0.)]
        normals = vertex_air_normals(points)
        index = SegmentIndex(points)
        rng = random.Random(726)
        for _ in range(500):
            i = rng.randrange(len(points))
            angle = rng.uniform(-math.pi, math.pi)
            kwargs = dict(source_index=i,direction=(math.cos(angle),math.sin(angle)),
                          center_x=0.,neighbor_exclusion=0,max_distance_a=1200.)
            self.assertEqual(
                _model6_first_opposite_reflection_hit(points,normals,**kwargs),
                _model6_first_opposite_reflection_hit(points,normals,segment_index=index,**kwargs))

    def test_grid_noise_is_reduced_while_broad_bulge_is_preserved(self):
        clean = [(float(i),20*math.exp(-((i-100)/30)**2)) for i in range(201)]
        noisy = [(x,y+0.10*(-1)**i) for i,(x,y) in enumerate(clean)]
        filtered = damp_mesh_oscillations(noisy)
        before = sum((noisy[i][1]-clean[i][1])**2 for i in range(10,191))
        after = sum((filtered[i][1]-clean[i][1])**2 for i in range(10,191))
        self.assertLess(after,before*.1)
        self.assertAlmostEqual(filtered[100][1],clean[100][1],delta=.03)
        # Integrated bulge area should not be erased by numerical damping.
        self.assertAlmostEqual(sum(y for x,y in filtered),sum(y for x,y in clean),delta=.5)

    def test_straight_surfaces_and_sharp_corners_do_not_drift(self):
        points = [(float(i),2.*i) for i in range(20)]
        self.assertEqual(damp_mesh_oscillations(points),points)
        corner = [(0.,0.),(1.,0.),(2.,0.),(2.,-1.),(2.,-2.),(2.,-3.)]
        self.assertEqual(damp_mesh_oscillations(corner),corner)
        self.assertEqual(SegmentIndex([]).ray_candidates((0,0),(1,0),100),[])

    def test_corner_redeposition_pinches_off_but_zero_capture_stays_open(self):
        config = TrenchDepoConfig(
            points=((1000.,0.),(250.,0.),(250.,-2200.),(-250.,-2200.),(-250.,0.),(-1000.,0.)),
            emulator_number=0, cycles=50, angstrom_per_cycle=3., reparam_ds_a=10.,
            sputter_enabled=True, sputter_strength_a_per_cycle=8., sputter_smoothing_a=20.,
            redepo_enabled=True, redepo_efficiency_pct=90.,
            redepo_emit_power=10., redepo_distance_power=100.,
        )
        result = run_trench_depo(config)
        control = run_trench_depo(replace(config, redepo_efficiency_pct=0.))
        first_closed = next(i for i,v in enumerate(result.frame_voids) if v)
        self.assertGreater(first_closed, 25)
        self.assertLess(first_closed, 45)
        self.assertFalse(any(control.frame_voids))
        # Broad inward growth near the upper wall exists before closure.
        def upper_wall_x(profile):
            return min(x for x,y in profile if x > 0 and -500 < y < -100)
        self.assertLess(upper_wall_x(result.frame_profiles[25]),
                        upper_wall_x(control.frame_profiles[25]) - 30.)
        def area(polygons):
            return sum(abs(sum(a[0]*b[1]-a[1]*b[0] for a,b in
                       zip(p,p[1:]+p[:1]))) * .5 for p in polygons)
        self.assertAlmostEqual(area(result.frame_voids[first_closed]),
                               area(result.frame_voids[-1]), places=4)


if __name__ == '__main__': unittest.main()
