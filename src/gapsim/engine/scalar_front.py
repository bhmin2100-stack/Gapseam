"""Versioned local-chart Godunov update for frozen scalar normal speeds.

H(p)=-V*sqrt(1+p*p); Godunov selects its exact interval extremum, including0.
This is not a full level-set or nonclassical shock solver. Flux/visibility are
recomputed by the surrounding trench solver; they are frozen within each call.
No target depth, corner pinning, curvature fitting or negative diffusion.
"""
import math
import numpy as np


def hamiltonian(left, right, speed):
    left,right,speed=np.broadcast_arrays(left,right,speed)
    hl=-speed*np.sqrt(1+left*left);hr=-speed*np.sqrt(1+right*right)
    lo=np.minimum(hl,hr);hi=np.maximum(hl,hr)
    contains=(np.minimum(left,right)<=0)&(np.maximum(left,right)>=0)
    lo=np.where(contains,np.minimum(lo,-speed),lo)
    hi=np.where(contains,np.maximum(hi,-speed),hi)
    return np.where(left<=right,lo,hi)


def raw_normals(points):
    edges=np.diff(points,axis=0)
    length=np.linalg.norm(edges,axis=1)
    tangent=edges/np.maximum(length[:,None],1e-15)
    normals=np.column_stack((-tangent[:,1],tangent[:,0]))
    combined=np.vstack((normals[0],normals[:-1]+normals[1:],normals[-1]))
    return combined/np.maximum(np.linalg.norm(combined,axis=1)[:,None],1e-15)


def advance(points, displacements, *, normals=None, cfl=.35, max_substeps=2048):
    """Move an ordered open boundary toward its left (air) side for positive V.

    Local tangent charts retain both one-sided slopes. Degenerate charts fall
    back to normal movement explicitly counted in diagnostics. Cut-plane x
    anchors remain fixed. First-order numerical diffusion remains possible.
    """
    p=np.asarray(points,float);v=np.asarray(displacements,float)
    if p.ndim!=2 or p.shape[1]!=2 or len(p)<2 or v.shape!=(len(p),):
        raise ValueError('Aligned polyline and displacement arrays required')
    if not np.isfinite(p).all() or not np.isfinite(v).all() or not 0<cfl<=.5:
        raise ValueError('Finite data and CFL in (0,.5] required')
    if not isinstance(max_substeps,int) or max_substeps<1:raise ValueError('Invalid substep limit')
    supplied=None if normals is None else np.asarray(normals,float)
    if supplied is not None and (supplied.shape!=p.shape or not np.isfinite(supplied).all()):
        raise ValueError('Aligned finite normal array required')
    original=p.copy();p=p.copy();remaining=1.;steps=0;fallback=0;chart_count=0
    if not np.any(v):return p.tolist(),dict(substeps=0,fallback_vertices=0,chart_vertices=0,max_cfl=0.)
    observed_cfl=0.
    while remaining>1e-12:
        if steps>=max_substeps:raise RuntimeError('Local graph CFL substep limit reached')
        n=raw_normals(p) if supplied is None else supplied.copy()
        n/=np.maximum(np.linalg.norm(n,axis=1)[:,None],1e-15)
        t=np.column_stack((n[:,1],-n[:,0]))
        before=p[1:-1]-p[:-2];after=p[2:]-p[1:-1]
        ub=np.sum(before*t[1:-1],axis=1);ua=np.sum(after*t[1:-1],axis=1)
        scale=np.maximum(np.minimum(np.linalg.norm(before,axis=1),np.linalg.norm(after,axis=1)),1e-12)
        good=(ub>scale*1e-6)&(ua>scale*1e-6)&(np.minimum(ub,ua)>1e-8)
        dl=np.divide(np.sum(before*n[1:-1],axis=1),ub,out=np.zeros_like(ub),where=good)
        dr=np.divide(np.sum(after*n[1:-1],axis=1),ua,out=np.zeros_like(ua),where=good)
        rate=v.copy();rate[1:-1]=np.where(good,-hamiltonian(dl,dr,v[1:-1]),v[1:-1])
        # |dH/dp|<=|V|. Frozen local charts use this conservative speed bound.
        ratio=np.divide(np.abs(v[1:-1]),np.minimum(ub,ua),out=np.zeros_like(ub),where=good)
        max_ratio=float(np.max(ratio,initial=0.))
        dt=min(remaining,cfl/max_ratio if max_ratio>0 else remaining)
        if dt<1e-12:raise RuntimeError('Local graph spacing collapsed')
        p+=dt*rate[:,None]*n
        p[[0,-1],0]=original[[0,-1],0]
        remaining-=dt;steps+=1;fallback+=int(np.count_nonzero(~good));chart_count+=int(good.sum())
        observed_cfl=max(observed_cfl,dt*max_ratio)
    if not np.isfinite(p).all():raise RuntimeError('Nonfinite propagated geometry')
    return p.tolist(),dict(substeps=steps,fallback_vertices=fallback,chart_vertices=chart_count,max_cfl=observed_cfl)


def area_change(before, after):
    """Signed solid area change with common fixed bottom and cut-plane anchors."""
    a=np.asarray(before,float);b=np.asarray(after,float)
    base=min(a[:,1].min(),b[:,1].min())-1.
    def area(p):
        q=np.vstack((p,[p[-1,0],base],[p[0,0],base]));r=np.roll(q,-1,axis=0)
        return -.5*np.sum(q[:,0]*r[:,1]-r[:,0]*q[:,1])
    return float(area(b)-area(a))
