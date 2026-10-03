"""Research feature-scale CVD transport, separate from sputter redeposition.

Two-dimensional, collisionless, diffuse re-emission model. Parameters are
effective sensitivities, NOT calibrated SiO2 recipes. A steady radiance balance
F = sky + K (1-s) F is solved on the current exposed boundary, then normalized
to unit planar growth. No material is removed. Units follow the input points.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from gapsim.engine.segment_index import SegmentIndex
from gapsim.engine.deposition_pipeline import (
    VertexNormalPropagator, normalize_surface_order, init_simulation_state,
    TopologyCleanup, OffsetBoolean, equal_arc_resample, _clip_difference,
    _int_paths_area, _extract_surface_from_solid,
)


@dataclass(frozen=True)
class CVDTransportConfig:
    sticking: float = 0.1
    rays: int = 64
    directional_fraction: float = 0.0
    directional_sigma_deg: float = 12.0
    tolerance: float = 1e-8
    max_iterations: int = 5000

    def __post_init__(self):
        if not 0 < self.sticking <= 1:
            raise ValueError('sticking must be in (0, 1]')
        if self.rays < 8 or self.rays % 2:
            raise ValueError('rays must be even and >= 8')
        if not 0 <= self.directional_fraction <= 1:
            raise ValueError('directional_fraction must be in [0, 1]')
        if not 0 < self.directional_sigma_deg <= 90:
            raise ValueError('directional_sigma_deg must be in (0, 90]')
        if self.tolerance <= 0 or self.max_iterations < 1:
            raise ValueError('invalid iteration controls')


def first_hit(points, index, origin, direction, distance):
    """Closest positive ray/segment intersection (segment index, interpolation)."""
    ox, oy = origin
    dx, dy = direction
    closest = distance
    result = None
    for j in index.ray_candidates(origin, direction, distance):
        ax, ay = points[j]
        bx, by = points[j + 1]
        ex, ey = bx - ax, by - ay
        det = dx * ey - dy * ex
        if abs(det) < 1e-13:
            continue
        rx, ry = ax - ox, ay - oy
        t = (rx * ey - ry * ex) / det
        u = (rx * dy - ry * dx) / det
        if 1e-7 < t < closest and -1e-9 <= u <= 1 + 1e-9:
            closest = t
            result = j, min(1., max(0., u))
    return result


def transport_flux(points: Sequence[tuple[float, float]], cfg=CVDTransportConfig()):
    """Return planar-normalized nonnegative vertex growth and solver diagnostics.

    2D cosine quadrature uses equally spaced sin(theta), giving equal weights.
    Unstuck neutrals are diffuse re-emission, not sputtered substrate material.
    The separate directional component sticks on first impact. Neither model
    includes gas collisions, surface diffusion, plasma chemistry, or nucleation.
    """
    points = normalize_surface_order(points)
    if len(points) < 2:
        raise ValueError('at least two surface points required')
    if not all(math.isfinite(v) for p in points for v in p):
        raise ValueError('finite coordinates required')
    normals = VertexNormalPropagator._vertex_air_normals(points)
    index = SegmentIndex(points)
    extent = max(max(x for x, y in points)-min(x for x, y in points),
                 max(y for x, y in points)-min(y for x, y in points), 1.)
    distance, epsilon = extent * 10, extent * 1e-8
    cosines = []
    for k in range(cfg.rays):
        tangent = -1 + 2 * (k + .5) / cfg.rays
        cosines.append((math.sqrt(1-tangent*tangent), tangent))
    rows, sky = [], []
    for (x, y), (nx, ny) in zip(points, normals):
        origin = x + epsilon * nx, y + epsilon * ny
        weights = {}
        source = 0.
        for c, t in cosines:
            direction = nx*c-ny*t, ny*c+nx*t
            hit = first_hit(points, index, origin, direction, distance)
            if hit is None:
                # Infinite planar continuation at the finite lateral boundary:
                # downward escapes are not incorrectly counted as reactor supply.
                source += (direction[1] > 0) / cfg.rays
            else:
                j, u = hit
                weights[j] = weights.get(j, 0.) + (1-u)/cfg.rays
                weights[j+1] = weights.get(j+1, 0.) + u/cfg.rays
        rows.append(list(weights.items()))
        sky.append(source)
    incoming = [1.] * len(points)
    residual = 0.
    for iteration in range(1, cfg.max_iterations+1):
        next_flux = [f + (1-cfg.sticking)*sum(w*incoming[j] for j, w in row)
                     for f, row in zip(sky, rows)]
        residual = max(abs(a-b) for a, b in zip(incoming, next_flux))
        incoming = next_flux
        if residual <= cfg.tolerance * cfg.sticking:
            break
    else:
        raise RuntimeError(f'CVD transport did not converge: {residual:g}')
    direct = [0.] * len(points)
    if cfg.directional_fraction:
        sigma = math.radians(cfg.directional_sigma_deg)
        angles = [-math.pi/2 + math.pi*(k+.5)/cfg.rays for k in range(cfg.rays)]
        weights = [math.exp(-.5*(a/sigma)**2) for a in angles]
        norm = sum(w*math.cos(a) for w, a in zip(weights, angles))
        for i, ((x, y), (nx, ny)) in enumerate(zip(points, normals)):
            origin = x+epsilon*nx, y+epsilon*ny
            for a, w in zip(angles, weights):
                d = math.sin(a), math.cos(a)
                incidence = max(0., nx*d[0]+ny*d[1])
                if incidence and first_hit(points, index, origin, d, distance) is None:
                    direct[i] += w*incidence/norm
    fraction = cfg.directional_fraction
    growth = [(1-fraction)*f + fraction*g for f, g in zip(incoming, direct)]
    # s*F divided by planar s: F is normalized growth for constant sticking.
    audit = dict(iterations=iteration, residual=residual,
                 error_bound=residual/cfg.sticking,
                 min_flux=min(growth), max_flux=max(growth),
                 direct_sky_min=min(sky), direct_sky_max=max(sky),
                 max_row_sum=max(s+sum(w for j,w in row) for s,row in zip(sky,rows)),
                 reemission_fraction=1-cfg.sticking,
                 model='2d_diffuse_neutral_reemission_plus_optional_directional_flux')
    return growth, audit


def run_cvd_profile(points, *, planar_thickness_a=600., step_a=10., ds_a=20.,
                    transport=CVDTransportConfig(), conformal=False, progress=None):
    """Evolve the exposed surface with a permanent substrate and sealed voids.

    Thickness is planar-equivalent exposure, not seconds or ALD cycles. There is
    no ad-hoc overhang shape. Shadowing and re-emission determine local growth.
    The conformal option is a geometric limit, not an ALD kinetic solver.
    """
    if min(step_a,ds_a)<=0 or planar_thickness_a<0:
        raise ValueError('positive resolution and nonnegative thickness required')
    state=init_simulation_state(points,reparam_ds_a=ds_a)
    original=list(state.solid_paths_i)
    initial=normalize_surface_order(points)
    frames=[dict(thickness_a=0.,profile=initial,voids=[],void_area_a2=0.)]
    steps=max(1,math.ceil(planar_thickness_a/step_a))
    increment=planar_thickness_a/steps
    state.surface.points=equal_arc_resample(initial,ds_a)
    audits=[]
    first_closed=None
    for k in range(1,steps+1):
        surface=state.surface.points
        if conformal:
            flux=[1.]*len(surface)
            audit=dict(iterations=0,residual=0.,error_bound=0.,min_flux=1.,max_flux=1.)
        else:
            flux,audit=transport_flux(surface,transport)
        proposed=VertexNormalPropagator().advance(surface,flux,increment)
        trapped=OffsetBoolean.collect_void_air(state)
        cleaned,solid=TopologyCleanup().cleanup(proposed,state,solid_merge_mode='union')
        # Once a gas pocket disconnects from the reactor, it receives no further
        # supply in this steady-state model. Preserve it explicitly; a polygon
        # spanning the external surface must not fill an old trapped pocket.
        if trapped:
            solid=_clip_difference(solid,trapped)
            cleaned=_extract_surface_from_solid(state,solid,cleaned)
        state.solid_paths_i=solid
        state.surface.points=equal_arc_resample(cleaned,ds_a)
        voids=OffsetBoolean.void_polygons_float(state)
        void_area=_int_paths_area(OffsetBoolean.collect_void_air(state))/state.scale**2
        lost=_int_paths_area(_clip_difference(original,solid))/state.scale**2
        if lost>1e-5:
            raise AssertionError(f'CVD removed original substrate: {lost}')
        if first_closed is None and void_area>ds_a**2:
            first_closed=k*increment
        audit['substrate_loss_a2']=lost
        audits.append(audit)
        frames.append(dict(thickness_a=k*increment,profile=state.surface.points,
                           voids=voids,void_area_a2=void_area))
        if progress:progress(k,steps)
    return dict(frames=frames,first_closed_thickness_a=first_closed,
                audit=dict(max_solver_error=max(a['error_bound'] for a in audits),
                           max_substrate_loss_a2=max(a['substrate_loss_a2'] for a in audits),
                           max_iterations=max(a['iterations'] for a in audits)),
                config=dict(planar_thickness_a=planar_thickness_a,step_a=step_a,
                            ds_a=ds_a,conformal=conformal,
                            transport=transport.__dict__))
