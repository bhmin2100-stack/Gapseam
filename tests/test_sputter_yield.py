import math
import numpy as np
import pytest
from gapsim.engine.sputter_yield import yamamura_yield,yamamura_integral


def test_yield_peak_and_grazing_limit():
    peak=72.;f=2.36;cp=math.cos(math.radians(peak))
    assert yamamura_yield([cp,0],peak,f)==pytest.approx([1,0])
    assert yamamura_yield([1],peak,f)[0]==pytest.approx(math.exp(f*(math.log(cp)+1-cp)))
    samples=np.linspace(0,1,10001)
    assert np.all((yamamura_yield(samples)>=0)&(yamamura_yield(samples)<=1))
    assert abs(samples[np.argmax(yamamura_yield(samples))]-cp)<1e-4


def test_source_flat_reference_backface_and_mirror():
    p=[(-10.,0),(0.,0),(10.,0)];n=[(0.,1.)]*3
    raw,exposed,flux=yamamura_integral(p,n,sigma=8,exponent=5)
    assert raw==pytest.approx(exposed) and np.all(flux>0)
    assert raw==pytest.approx(raw[::-1])
    assert yamamura_integral(p,[(0.,-1.)]*3)[1]==pytest.approx([0,0,0])


@pytest.mark.parametrize('f',[0,-1,float('inf')])
def test_invalid_material_exponent_is_rejected(f):
    with pytest.raises(ValueError):yamamura_yield([.5],exponent=f)
