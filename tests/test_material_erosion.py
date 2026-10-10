import numpy as np
import pytest
from gapsim.engine.material_erosion import allocate_erosion,normal_film_thickness,shadow_growth_ratio

def test_film_then_substrate_at_same_dose():
    d,f,s=allocate_erosion([3,3,3],[1,0,np.inf],.2)
    assert d==pytest.approx([1.4,.6,3])
    assert f+s==pytest.approx(d)
    assert allocate_erosion([3,3],[1,0],1)[0]==pytest.approx([3,3])
    assert allocate_erosion([3,3],[1,0],0)[0]==pytest.approx([1,0])

def test_remaining_material_and_mirror():
    polygon=[[(-100,-100),(100,-100),(100,0),(-100,0)]]
    t=normal_film_thickness([[-1,2],[1,2],[0,-1]],[[0,1],[0,1],[0,1]],polygon,10)
    assert t==pytest.approx([2,2,0])
    assert np.isinf(normal_film_thickness([[0,2]],[[0,1]],[],10)[0])

def test_ray_tilt_hole_and_no_intersection():
    outer=[(-100,-100),(100,-100),(100,100),(-100,100)]
    hole=[(-20,-20),(-20,20),(20,20),(20,-20)]
    assert normal_film_thickness([[0,0]],[[0,1]],[outer,hole],10)==pytest.approx([2])
    assert np.isinf(normal_film_thickness([[20,20]],[[1,0]],[outer],10)[0])

def test_growth_has_independent_reference_limits():
    assert shadow_growth_ratio([0,1],1.4,20)==pytest.approx([1.4,1])
    assert shadow_growth_ratio([0,.3,1],1,20)==pytest.approx([1,1,1])
    assert np.all(np.diff(shadow_growth_ratio(np.linspace(0,1,20),1.4,20))<=0)

@pytest.mark.parametrize('ratio',[-1,float('nan')])
def test_reject_invalid_ratio(ratio):
    with pytest.raises(ValueError):allocate_erosion([1],[0],ratio)
