import math
from dataclasses import replace

import numpy as np
import pytest

from gapsim.engine.incident_ions import visible_from_direction, source_integral
from gapsim.emulation.incident_presets import incident_study_preset, INCIDENT_PRESET_DOSES
from gapsim.emulation.trench_depo import equal_arc_resample, vertex_air_normals, run_trench_depo


def brute_visible(points, angle):
    p = np.asarray(points, dtype=float)
    u = np.array([math.sin(angle), math.cos(angle)])
    result = []
    cross = lambda a, b: a[0]*b[1]-a[1]*b[0]
    for origin in p:
        blocked = False
        for a, b in zip(p, p[1:]):
            v, w = b-a, a-origin
            den = cross(u,v)
            if abs(den) < 1e-10:
                if abs(cross(w,u)) < 1e-8 and max((a-origin)@u,(b-origin)@u)>1e-6:
                    blocked = True
                    break
                continue
            t, s = cross(w,v)/den, cross(w,u)/den
            if t > 1e-6 and -1e-8 <= s <= 1+1e-8:
                blocked = True
                break
        result.append(not blocked)
    return np.array(result)


@pytest.mark.parametrize('angle', [-40,-20,-10,0,10,20,40])
def test_visibility_matches_independent_intersections(angle):
    for shape in [
        [(-100,0),(-25,0),(-25,-220),(25,-220),(25,0),(100,0)],
        [(-100,10),(-30,10),(-5,-30),(-20,-65),(-20,-220),(20,-220),(20,-65),(5,-30),(30,10),(100,10)],
    ]:
        p = equal_arc_resample(shape, 5)
        np.testing.assert_array_equal(visible_from_direction(p,math.radians(angle)),brute_visible(p,math.radians(angle)))


def test_flat_backface_empty_and_bottom_visibility():
    p = [(-10,0),(0,0),(10,0)]
    raw, exposed, _ = source_integral(p,[(0,1)]*3)
    np.testing.assert_allclose(raw, exposed)
    assert exposed[0] > 0
    np.testing.assert_array_equal(source_integral(p,[(0,-1)]*3)[1],0)
    assert len(source_integral([],[])[0])==0
    trench = [(-100,0),(-25,0),(-25,-220),(0,-220),(25,-220),(25,0),(100,0)]
    assert visible_from_direction(trench,0)[3]
    assert not visible_from_direction(trench,math.radians(20))[3]


def test_symmetry_and_shadow_only_reduces_source():
    p = equal_arc_resample([(-100,0),(-25,0),(-25,-220),(25,-220),(25,0),(100,0)],5)
    raw, exposed, _ = source_integral(p,vertex_air_normals(p))
    assert np.all(exposed<=raw+1e-12)
    assert np.sum(raw-exposed)>0
    np.testing.assert_allclose(exposed,exposed[::-1],atol=1e-9)


@pytest.mark.parametrize('kw', [dict(sigma=0),dict(sigma=float('nan')),dict(sigma=21),dict(rays=4),dict(rays=2),dict(rays=103),dict(rays=3.5)])
def test_invalid_incident_settings_rejected(kw):
    with pytest.raises(ValueError):
        source_integral([(0,0)],[(0,1)],**kw)


@pytest.mark.parametrize('dose', INCIDENT_PRESET_DOSES)
def test_builtin_presets_have_exact_requested_gross_dose(dose):
    cfg = incident_study_preset(dose)
    assert cfg.cycles*cfg.angstrom_per_cycle==dose
    assert cfg.redepo_incident_los_enabled and cfg.redepo_enabled
    assert cfg.sputter_strength_a_per_cycle==8/3
    assert not cfg.ion_transmission_enabled


def test_zero_capture_keeps_incident_source_model():
    cfg = replace(incident_study_preset(),cycles=2, redepo_efficiency_pct=0)
    result = run_trench_depo(cfg)
    assert result.meta['redepo_incident_los_enabled']
    assert result.meta['incident_source_model']=='gaussian_cosine_yield_geometric_visibility'


def test_disabling_new_source_restores_legacy_model():
    cfg = replace(incident_study_preset(),cycles=2,redepo_incident_los_enabled=False)
    assert run_trench_depo(cfg).meta['incident_source_model']=='legacy'
