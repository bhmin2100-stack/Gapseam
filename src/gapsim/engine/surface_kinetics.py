"""Reduced, collisionless 2D neutral transport and self-limiting adsorption.

The precursor pulse is represented by an effective incident dose/site capacity,
not pulse seconds or a complete multi-reactant ALD chemistry. Occupied sites
reemitting neutrals are distinct from sputtered film fragments.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np

from .cvd_transport import first_hit
from .deposition_pipeline import (
    SimulationCanceled, VertexNormalPropagator, normalize_surface_order,
)
from .segment_index import SegmentIndex


@dataclass(frozen=True)
class NeutralTransportKernel:
    points: list
    sky: np.ndarray
    row: np.ndarray
    column: np.ndarray
    weight: np.ndarray

    def incoming(self, sticking, initial=None, *, tolerance=1e-8,
                 max_iterations=5000, cancel_check=None):
        """Solve F = sky + K[(1-s)F] with spatially varying active-site s."""
        probability = np.broadcast_to(np.asarray(sticking, dtype=float), self.sky.shape)
        if not np.all(np.isfinite(probability)) or np.any(probability < 0) or np.any(probability > 1):
            raise ValueError('sticking probability must be finite and in [0, 1]')
        incoming = np.ones_like(self.sky) if initial is None else np.asarray(initial, dtype=float).copy()
        for iteration in range(1, max_iterations + 1):
            if iteration % 32 == 0 and cancel_check and cancel_check():
                raise SimulationCanceled()
            next_flux = self.sky + np.bincount(
                self.row, weights=self.weight * ((1-probability)*incoming)[self.column],
                minlength=len(self.sky))
            residual = float(np.max(np.abs(next_flux-incoming)))
            incoming = next_flux
            if residual <= tolerance:
                return incoming, dict(iterations=iteration, residual=residual)
        raise RuntimeError(f'Neutral transport did not converge: residual={residual:g}')


def _angular_visibility(points,origin,normal):
    """Exact blocked intervals and sky view factor in a 2D cosine hemisphere.

    Segment endpoints bound their angular occlusion interval. Clipping each
    segment to the forward hemisphere and unioning those intervals resolves
    arbitrarily narrow open apertures without depending on quadrature rays.
    """
    p=np.asarray(points,dtype=float)-origin
    nx,ny=normal
    forward=p[:,0]*nx+p[:,1]*ny
    tangent=-p[:,0]*ny+p[:,1]*nx
    active=np.maximum(forward[:-1],forward[1:])>1e-12
    a,b=forward[:-1][active].copy(),forward[1:][active].copy()
    ta,tb=tangent[:-1][active].copy(),tangent[1:][active].copy()
    behind=a<=0
    ta[behind]+=(tb[behind]-ta[behind])*(-a[behind])/(b[behind]-a[behind]);a[behind]=0.
    behind=b<=0
    tb[behind]+=(ta[behind]-tb[behind])*(-b[behind])/(a[behind]-b[behind]);b[behind]=0.
    angle_a,angle_b=np.arctan2(ta,a),np.arctan2(tb,b)
    left,right=np.minimum(angle_a,angle_b),np.maximum(angle_a,angle_b)
    substantial=right-left>1e-12
    left,right=left[substantial],right[substantial]
    order=np.argsort(left)
    left,right=left[order],right[order]
    blocked=[]
    if len(left):
        envelope=np.maximum.accumulate(right)
        starts=np.concatenate(([0],np.flatnonzero(left[1:]>envelope[:-1]+1e-12)+1))
        ends=np.concatenate((starts[1:]-1,[len(left)-1]))
        blocked=[(float(left[i]),float(envelope[j])) for i,j in zip(starts,ends)]
    blocked_mass=sum(.5*(math.sin(b)-math.sin(a)) for a,b in blocked)
    clear=[];previous=-math.pi/2
    for left,right in blocked:
        if left>previous:clear.append((previous,left))
        previous=max(previous,right)
    if previous<math.pi/2:clear.append((previous,math.pi/2))
    horizon=math.atan2(-ny,nx)
    while horizon>math.pi/2:horizon-=math.pi
    while horizon<-math.pi/2:horizon+=math.pi
    sky=0.
    for left,right in clear:
        cuts=[left]+([horizon] if left<horizon<right else [])+[right]
        for a,b in zip(cuts,cuts[1:]):
            theta=(a+b)/2
            if ny*math.cos(theta)+nx*math.sin(theta)>0:
                sky+=.5*(math.sin(b)-math.sin(a))
    return blocked,max(0.,min(1.,blocked_mass)),max(0.,min(1.,sky))


def build_neutral_kernel(points, rays=32, *, cancel_check=None):
    if isinstance(rays, bool) or int(rays) != rays or rays < 8 or rays % 2:
        raise ValueError('neutral transport rays must be an even integer >= 8')
    points = normalize_surface_order(points)
    if len(points) < 2 or not all(math.isfinite(v) for p in points for v in p):
        raise ValueError('at least two finite surface points required')
    normals = VertexNormalPropagator._vertex_air_normals(points)
    index = SegmentIndex(points)
    extent = max(np.ptp(np.asarray(points), axis=0).max(), 1.)
    distance, epsilon = extent*10, extent*1e-8
    cosine = [(math.sqrt(1-t*t), t) for t in (-1+2*(k+.5)/rays for k in range(rays))]
    row, column, weights, sky = [], [], [], []
    for i, ((x,y),(nx,ny)) in enumerate(zip(points,normals)):
        if i % 32 == 0 and cancel_check and cancel_check():
            raise SimulationCanceled()
        origin = x+epsilon*nx, y+epsilon*ny
        blocked,blocked_mass,source=_angular_visibility(points,origin,(nx,ny))
        local_weights={}
        for c,t in cosine:
            direction = nx*c-ny*t, ny*c+nx*t
            hit = first_hit(points,index,origin,direction,distance)
            if hit is not None:
                j,u=hit
                local_weights[j]=local_weights.get(j,0.)+(1-u)/rays
                local_weights[j+1]=local_weights.get(j+1,0.)+u/rays
        # Preserve the analytically known open/blocked solid-angle partition.
        # A small obstacle missed by every fixed ray gets an interval-midpoint
        # fallback; wall-to-wall distribution still converges with ray count.
        if not local_weights and blocked_mass>1e-14:
            for left,right in blocked:
                theta=(left+right)/2;c,t=math.cos(theta),math.sin(theta)
                hit=first_hit(points,index,origin,(nx*c-ny*t,ny*c+nx*t),distance)
                if hit is not None:
                    j,u=hit;weight=.5*(math.sin(right)-math.sin(left))
                    local_weights[j]=local_weights.get(j,0.)+(1-u)*weight
                    local_weights[j+1]=local_weights.get(j+1,0.)+u*weight
        total=sum(local_weights.values())
        if total:
            for j,w in local_weights.items():
                row.append(i);column.append(j);weights.append(w*blocked_mass/total)
        sky.append(source)
    return NeutralTransportKernel(points,np.asarray(sky),np.asarray(row,dtype=int),
                                  np.asarray(column,dtype=int),np.asarray(weights))


def adsorption_coverage(kernel: NeutralTransportKernel, *, sticking=.1,
                        exposure=5., integration_step=.25, site_availability=None,
                        cancel_check: Callable | None=None):
    """Langmuir coverage coupled to steady molecular-flow transport.

    E is initial reaction probability times incident molecules/site on a flat
    surface; its analytic flat coverage is 1-exp(-E). Clean-surface sticking
    controls penetration; the effective sticking becomes s0*(1-theta). An
    exponential midpoint update preserves 0<=theta<=1. Sites reset per ALD cycle.
    """
    if not math.isfinite(sticking) or not 0 < sticking <= 1:
        raise ValueError('adsorption sticking must be in (0, 1]')
    if not math.isfinite(exposure) or exposure < 0:
        raise ValueError('exposure must be finite and nonnegative')
    if not math.isfinite(integration_step) or integration_step <= 0:
        raise ValueError('integration_step must be positive and finite')
    coverage = np.zeros(len(kernel.sky))
    available = np.ones(len(kernel.sky)) if site_availability is None else np.asarray(site_availability,dtype=float)
    if available.shape!=coverage.shape or not np.all(np.isfinite(available)) or np.any(available<0) or np.any(available>1):
        raise ValueError('site availability must contain one fraction in [0, 1] per surface point')
    incoming = np.ones(len(kernel.sky))
    count = max(1, math.ceil(exposure/integration_step))
    dt = exposure/count
    max_iterations, max_residual = 0, 0.
    for _ in range(count):
        if cancel_check and cancel_check():
            raise SimulationCanceled()
        incoming, audit = kernel.incoming(sticking*available*(1-coverage),incoming,cancel_check=cancel_check)
        midpoint = 1-(1-coverage)*np.exp(-.5*dt*incoming)
        middle_flux, middle_audit = kernel.incoming(sticking*available*(1-midpoint),incoming,cancel_check=cancel_check)
        coverage = 1-(1-coverage)*np.exp(-dt*middle_flux)
        incoming = middle_flux
        max_iterations = max(max_iterations,audit['iterations'],middle_audit['iterations'])
        max_residual = max(max_residual,audit['residual'],middle_audit['residual'])
    return coverage, dict(planar_coverage=-math.expm1(-exposure),
                          min_coverage=float(min(coverage)),max_coverage=float(max(coverage)),
                          integration_steps=count,max_iterations=max_iterations,
                          max_residual=max_residual,
                          model='langmuir_variable_sticking_collisionless_2d')


def sputtered_redeposition(points, removed_depth, *, sticking, rays=32, cancel_check=None):
    """Conservative 2D cosine-law fragment emission with geometric first impact.

    Returns normal redeposition depth and an area-per-unit-line-length budget.
    Noncaptured fragments escape this one-flight approximation; no arbitrary
    depth or distance attenuation and no precursor re-emission are included.
    """
    if not 0 <= sticking <= 1:
        raise ValueError('fragment sticking must be in [0, 1]')
    normals = VertexNormalPropagator._vertex_air_normals(points)
    p = np.asarray(points,dtype=float)
    lengths = np.linalg.norm(np.diff(p,axis=0),axis=1)
    areas = np.zeros(len(p));areas[:-1]+=.5*lengths;areas[1:]+=.5*lengths
    removed = np.maximum(0,np.asarray(removed_depth))*areas
    captured = np.zeros(len(p));transport_lines=[]
    total = float(removed.sum())
    extent = max(np.ptp(p,axis=0).max(),1.)
    index=SegmentIndex(points)
    for i,(origin0,normal,mass) in enumerate(zip(points,normals,removed)):
        if mass <= 1e-15 or sticking <= 0:
            continue
        if i % 32 == 0 and cancel_check and cancel_check():
            raise SimulationCanceled()
        nx,ny=normal; x,y=origin0
        origin=x+extent*1e-8*nx,y+extent*1e-8*ny
        for k in range(rays):
            t=-1+2*(k+.5)/rays;c=math.sqrt(1-t*t)
            direction=nx*c-ny*t,ny*c+nx*t
            hit=first_hit(points,index,origin,direction,extent*10)
            if hit is None:
                continue
            j,u=hit;amount=float(mass)*sticking/rays
            captured[j]+=(1-u)*amount;captured[j+1]+=u*amount
            if len(transport_lines)<128:
                target=(1-u)*p[j]+u*p[j+1]
                transport_lines.append([x,y,float(target[0]),float(target[1]),amount])
    deposited=float(captured.sum())
    return np.divide(captured,areas,out=np.zeros_like(captured),where=areas>0), dict(
        total_removed_mass=total,total_redepo_mass=deposited,
        escaped_mass=max(0.,total-deposited),capture_ratio=deposited/total if total else 0.,
        conservation_error=abs(total-deposited-max(0.,total-deposited)),
        mass_units='A2_per_unit_out_of_plane_length',transport_lines=transport_lines,
        model='2d_cosine_first_hit_single_flight')
