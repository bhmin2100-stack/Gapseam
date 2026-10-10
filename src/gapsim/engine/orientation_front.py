"""Versioned orientation-aware front update; no fitted target coordinates.

In each local graph, use both one-sided slopes and re-evaluate projected ion
yield at trial normals. Visibility and arriving redeposition mass are frozen
within a transport step, NOT the angle-dependent erosion speed. Sampled
Godunov interval extrema are an approximation, checked by sample refinement.
This is not the fourth-order undercompressive-shock model of Holmes-Cerfon.
"""
import math
import numpy as np
from gapsim.engine import incident_ions as ions


def angular_quadrature(points, sigma, rays):
    sigma, rays = ions.validate_incident_parameters(sigma, rays)
    angles = np.radians(np.linspace(-4*sigma, 4*sigma, rays))
    weights = np.exp(-.5*(np.degrees(angles)/sigma)**2)
    weights[[0, -1]] *= .5
    weights /= weights.sum()
    directions = np.column_stack((np.sin(angles), np.cos(angles)))
    visible = np.column_stack([ions.visible_from_direction(points, a) for a in angles])
    return directions, visible * weights


def hamiltonian(slopes, normals, tangent, directions, weights, arrival, amplitude, peak, width, clamp, extra=None):
    root = np.sqrt(1 + slopes*slopes)
    candidate = (normals - slopes[:, None]*tangent)/root[:, None]
    cosine = np.clip(candidate @ directions.T, 0., 1.)
    theta = np.degrees(np.arccos(cosine))
    etch = amplitude*np.sum(weights*cosine*np.exp(-.5*((theta-peak)/width)**2), axis=1)
    if extra is not None:
        ed,ew,eg,ep,ewidth=extra
        ec=np.clip(candidate @ ed.T,0.,1.)
        etch+=amplitude*eg*np.sum(ew*ec*np.exp(-.5*((np.degrees(np.arccos(ec))-ep)/ewidth)**2),axis=1)
    return -(arrival - np.minimum(etch, clamp))*root


def advance(points, normals, arrival, *, strength, amplitude, sigma, rays, peak, width, clamp, samples=9, spectrum=None):
    if samples < 3 or samples % 2 == 0:
        raise ValueError('Odd interval sample count >=3 required')
    if width <= 0 or strength < 0 or not 0 <= amplitude:
        raise ValueError('Nonnegative strengths and positive angular width required')
    p = np.asarray(points, float).copy()
    n = np.asarray(normals, float)
    v = np.asarray(arrival, float)
    if p.shape != n.shape or v.shape != (len(p),) or not all(np.isfinite(x).all() for x in (p,n,v)):
        raise ValueError('Aligned finite geometry and arrivals required')
    directions, weights = angular_quadrature(p, sigma, rays)
    extra=None
    if spectrum:
        ed,ew=angular_quadrature(p,spectrum['sigma'],rays)
        extra=(ed,ew,spectrum['gain'],spectrum['peak'],spectrum['width'])
    n /= np.maximum(np.linalg.norm(n, axis=1)[:, None], 1e-15)
    tangent = np.column_stack((n[:, 1], -n[:, 0]))
    original = p.copy()
    remaining = 1.
    count = fallbacks = 0
    max_cfl = 0.
    amp = strength*amplitude
    # |dH/dp| <= arrival + amp*(2 + max |dY/dtheta|), since weights sum<=1.
    bound = v + amp*(2 + 1/(math.radians(width)*math.sqrt(math.e)))
    if spectrum:
        bound+=amp*spectrum['gain']*(2+1/(math.radians(spectrum['width'])*math.sqrt(math.e)))
    while remaining > 1e-12:
        before, after = p[1:-1]-p[:-2], p[2:]-p[1:-1]
        ub = np.sum(before*tangent[1:-1], axis=1)
        ua = np.sum(after*tangent[1:-1], axis=1)
        good = (ub > 1e-6) & (ua > 1e-6)
        dl = np.divide(np.sum(before*n[1:-1], axis=1), ub, out=np.zeros_like(ub), where=good)
        dr = np.divide(np.sum(after*n[1:-1], axis=1), ua, out=np.zeros_like(ua), where=good)
        left, right = np.r_[0.,dl,0.], np.r_[0.,dr,0.]
        low, high = np.minimum(left,right), np.maximum(left,right)
        minimum, maximum = np.full(len(p), np.inf), np.full(len(p), -np.inf)
        for a in np.linspace(0, 1, samples):
            slope = low + a*(high-low)
            h = hamiltonian(slope,n,tangent,directions,weights,v,amp,peak,width,clamp,extra)
            minimum, maximum = np.minimum(minimum,h), np.maximum(maximum,h)
        # Also evaluate p=0 wherever the interval crosses it.
        h0 = hamiltonian(np.zeros(len(p)),n,tangent,directions,weights,v,amp,peak,width,clamp,extra)
        zero = (low <= 0) & (high >= 0)
        minimum = np.where(zero,np.minimum(minimum,h0),minimum)
        maximum = np.where(zero,np.maximum(maximum,h0),maximum)
        rate = -np.where(left <= right,minimum,maximum)
        rate[1:-1] = np.where(good,rate[1:-1],-h0[1:-1])
        ratio = np.divide(bound[1:-1],np.minimum(ub,ua),out=np.zeros_like(ub),where=good)
        max_ratio = np.max(ratio,initial=0.)
        dt = min(remaining,.35/max_ratio if max_ratio else remaining)
        if dt < 1e-10 or count >= 2048:
            raise RuntimeError('Angular front local chart collapsed')
        p += dt*rate[:,None]*n
        p[[0,-1],0] = original[[0,-1],0]
        remaining -= dt
        count += 1
        fallbacks += int((~good).sum())
        max_cfl = max(max_cfl,float(dt*max_ratio))
    return p.tolist(),dict(substeps=count,fallback_vertices=fallbacks,max_cfl=max_cfl)
