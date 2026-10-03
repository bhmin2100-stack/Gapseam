"""2D incident-ion radiance/yield integration over geometrically open directions.

This is a calibrated-input model, not an RF/sheath/charging solver. The default
angular width is a research assumption; energy dependence is not represented.
"""
from __future__ import annotations

import math
import numpy as np


def visible_from_direction(points, angle):
    """Exact upper envelope of the polyline in upstream ray coordinates."""
    p = np.asarray(points, dtype=float)
    if len(p) == 0:
        return np.zeros(0, dtype=bool)
    sn, cs = math.sin(angle), math.cos(angle)
    q = p[:, 0] * cs - p[:, 1] * sn
    h = p[:, 0] * sn + p[:, 1] * cs
    signs = np.sign(np.diff(q))
    nz = np.flatnonzero(signs)
    if not len(nz):
        return h >= h.max() - 1e-7
    signs[:nz[0]] = signs[nz[0]]
    for i in np.flatnonzero(signs == 0):
        signs[i] = signs[i-1]
    cuts = [0] + (np.flatnonzero(signs[1:] != signs[:-1]) + 1).tolist() + [len(q)-1]
    envelope = np.full(len(q), -np.inf)
    for a, b in zip(cuts, cuts[1:]):
        rq, rh = q[a:b+1], h[a:b+1]
        if rq[-1] < rq[0]:
            rq, rh = rq[::-1], rh[::-1]
        unique, starts = np.unique(rq, return_index=True)
        heights = np.maximum.reduceat(rh, starts)
        if len(unique) == 1:
            mask = np.abs(q-unique[0]) < 1e-9
            envelope[mask] = np.maximum(envelope[mask], heights[0])
        else:
            envelope = np.maximum(envelope, np.interp(q, unique, heights, left=-np.inf, right=-np.inf))
    return h >= envelope - 1e-7


def validate_incident_parameters(sigma, rays):
    sigma = float(sigma)
    if not math.isfinite(sigma) or not 0.1 <= sigma <= 20.0:
        raise ValueError("Incident ion sigma must be between 0.1 and 20 degrees")
    if isinstance(rays, bool) or not math.isfinite(float(rays)) or int(rays) != rays or not 3 <= rays <= 101 or int(rays) % 2 == 0:
        raise ValueError("Incident ion directions must be an odd integer between 3 and 101")
    return sigma, int(rays)


def source_integral(points, normals, *, sigma=10., rays=25, peak=55., width=40., amplitude=1.):
    """Return unshadowed yield, exposed yield and exposed flux per unit radiance.

    Incoming Gaussian radiance is normalized over +/-4 sigma. Projection onto
    the local surface is explicit; unilluminated/back-facing areas emit nothing.
    No smoothing across an occlusion boundary is performed on the source field.
    """
    sigma, rays = validate_incident_parameters(sigma, rays)
    if len(points) != len(normals):
        raise ValueError("One air-side normal is required per surface point")
    if not math.isfinite(width) or width <= 0:
        raise ValueError("Yield width must be positive and finite")
    if not len(points):
        return tuple(np.zeros(0) for _ in range(3))
    angles = np.linspace(-4*sigma, 4*sigma, rays)
    weights = np.exp(-0.5*(angles/sigma)**2)
    weights[[0, -1]] *= .5
    weights /= weights.sum()
    normals = np.asarray(normals)
    raw, exposed, flux = (np.zeros(len(points)) for _ in range(3))
    for angle, weight in zip(angles, weights):
        rad = math.radians(angle)
        cosine = np.clip(normals @ np.array([math.sin(rad), math.cos(rad)]), 0, 1)
        incidence = np.degrees(np.arccos(cosine))
        response = amplitude*np.exp(-.5*((incidence-peak)/width)**2)
        incident = weight*cosine
        clear = visible_from_direction(points, rad)
        raw += incident*response
        exposed += incident*response*clear
        flux += incident*clear
    return raw, exposed, flux
