"""Analytic checks of the shipped solvers, without local research imports."""
import numpy as np
import pytest
from gapsim.engine import orientation_front as angular
from gapsim.engine import scalar_front as scalar


def test_scalar_interval_extrema():
    assert scalar.hamiltonian(-.5,.5,1.)==pytest.approx(-np.sqrt(1.25))
    assert scalar.hamiltonian(.5,-.5,1.)==pytest.approx(-1.)
    assert scalar.hamiltonian(-.5,.5,-1.)==pytest.approx(1.)
    assert scalar.hamiltonian(.5,-.5,-1.)==pytest.approx(np.sqrt(1.25))


def test_scalar_planar_translation():
    p=np.column_stack((np.arange(-20,21),np.zeros(41)))
    q,audit=scalar.advance(p,np.full(41,3.))
    np.testing.assert_allclose(q,p+[0,3],rtol=0,atol=1e-10)
    assert audit['max_cfl']<=.35+1e-12
    assert audit['fallback_vertices']==0


@pytest.mark.parametrize('spacing',[1.,.5])
def test_scalar_wedge_etch_and_growth(spacing):
    z=np.arange(-80,80+spacing/2,spacing)
    p=np.column_stack((.5*np.abs(z),-z))[::-1]
    normals=np.tile([-1.,0.],(len(p),1));middle=len(p)//2
    eroded,_=scalar.advance(p,np.full(len(p),-10.),normals=normals)
    grown,_=scalar.advance(p,np.full(len(p),10.),normals=normals)
    exact=p[:,0]+10*np.sqrt(1.25)
    np.testing.assert_allclose(np.asarray(eroded)[middle-25:middle+26,0],exact[middle-25:middle+26],rtol=0,atol=1e-8)
    k=round(5/spacing)
    def turn(q):
        return np.degrees(np.arctan((q[middle+k][0]-q[middle][0])/5)-np.arctan((q[middle][0]-q[middle-k][0])/5))
    assert turn(eroded)>50 and turn(grown)<40


def test_angular_plane_projected_yield():
    p=np.column_stack((np.arange(-20,21)*10.,np.zeros(41)))
    n=np.tile([0.,1.],(41,1))
    directions,w=angular.angular_quadrature(p,5.,25)
    expected=-angular.hamiltonian(np.zeros(41),n,np.tile([1.,0.],(41,1)),directions,w,np.ones(41),2.,45.,14.,80.)
    q,audit=angular.advance(p,n,np.ones(41),strength=2,amplitude=1,sigma=5,rays=25,peak=45,width=14,clamp=80)
    np.testing.assert_allclose(np.asarray(q)[:,1],expected,rtol=0,atol=1e-10)
    assert audit['max_cfl']<=.35+1e-12


def test_angular_reflection_equivariance():
    p=np.column_stack((np.arange(-30,31)*10.,np.sin(np.arange(-30,31)/6)*8))
    n=scalar.raw_normals(p);v=np.ones(len(p))*.4
    kw=dict(strength=.5,amplitude=1,sigma=5,rays=25,peak=55,width=14,clamp=80)
    q,_=angular.advance(p,n,v,**kw)
    r,_=angular.advance(p[::-1]*[-1,1],n[::-1]*[-1,1],v,**kw)
    np.testing.assert_allclose(np.asarray(q)[::-1]*[-1,1],r,rtol=0,atol=1e-10)
