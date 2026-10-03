"""Mesh-scale fourth-order damping; it is not a material diffusion model.

The paired Laplacian has response 1 - L**2/4: unlike ordinary averaging,
attenuation of long wavelength features starts at fourth order. Endpoints and
resolved sharp corners stay fixed. This must not replace time-step refinement.
"""
from __future__ import annotations

import math


def fair_profile_implicit(points, *, length_a=10.0, fixed_mask=None):
    """Normal-only, area-constrained implicit fourth-order numerical fairing.

    Solve (I + length**4 D2.T D2) for displacement in O(N), using actual
    segment lengths. This is numerical regularization, NOT surface diffusion.
    Endpoints and resolved corners (turn >= 45 degrees) are pinned. Signed
    polygon area, closed by the fixed endpoint chord, is restored afterwards;
    topology/void handling remains the caller's responsibility. fixed_mask can
    additionally pin inactive material, preventing smoothing into an unetched
    flat bottom. It has the same length as points.
    """
    p = [(float(x), float(y)) for x, y in points]
    n = len(p)
    if fixed_mask is not None and len(fixed_mask) != n:
        raise ValueError("fixed_mask must have one entry per profile point")
    if n < 5 or length_a <= 0:
        return p
    fixed = [True] * n
    normals = [(0., 0.)] * n
    rows = []
    for i in range(1, n - 1):
        ux, uy = p[i][0] - p[i-1][0], p[i][1] - p[i-1][1]
        vx, vy = p[i+1][0] - p[i][0], p[i+1][1] - p[i][1]
        h, k = math.hypot(ux, uy), math.hypot(vx, vy)
        if min(h, k) < 1e-9 or (ux*vx + uy*vy) / (h*k) <= math.sqrt(.5):
            continue
        fixed[i] = bool(fixed_mask[i]) if fixed_mask is not None else False
        tx, ty = ux + vx, uy + vy
        norm = math.hypot(tx, ty)
        if not fixed[i]:
            normals[i] = (-ty / norm, tx / norm)
        rows.append((i, (2/(h*(h+k)), -2/(h*k), 2/(k*(h+k)))))
    a, b, c = [1.] * n, [0.] * n, [0.] * n
    rx, ry = [0.] * n, [0.] * n
    lam = float(length_a)**4
    for i, coefficients in rows:
        ids = (i-1, i, i+1)
        kx = sum(v*p[j][0] for j, v in zip(ids, coefficients))
        ky = sum(v*p[j][1] for j, v in zip(ids, coefficients))
        for j, v in zip(ids, coefficients):
            if fixed[j]:
                continue
            rx[j] -= lam*v*kx
            ry[j] -= lam*v*ky
            for q, w in zip(ids, coefficients):
                if fixed[q] or q > j:
                    continue
                term = lam*v*w
                if j == q:
                    a[j] += term
                elif j-q == 1:
                    b[j] += term
                else:
                    c[j] += term
    # Banded Cholesky; only two subdiagonals, no third-party dependency.
    for i in range(n):
        c[i] = c[i]/a[i-2] if i >= 2 else 0.
        b[i] = (b[i]-c[i]*b[i-1])/a[i-1] if i else 0.
        a[i] = math.sqrt(max(1e-15, a[i]-b[i]**2-c[i]**2))
        for rhs in (rx, ry):
            rhs[i] = (rhs[i] - (b[i]*rhs[i-1] if i else 0.)
                      - (c[i]*rhs[i-2] if i >= 2 else 0.))/a[i]
    for i in range(n-1, -1, -1):
        for rhs in (rx, ry):
            rhs[i] = (rhs[i] - (b[i+1]*rhs[i+1] if i+1 < n else 0.)
                      - (c[i+2]*rhs[i+2] if i+2 < n else 0.))/a[i]
    delta = [rx[i]*nx + ry[i]*ny for i, (nx, ny) in enumerate(normals)]
    weights = [abs(d) if abs(d) > 1e-10 else 0. for d in delta]
    if not any(weights):
        return p
    out = [(x+d*nx, y+d*ny) for (x, y), d, (nx, ny) in zip(p, delta, normals)]

    def signed_area(q):
        # Translation avoids loss of precision on large world coordinates.
        ox, oy = q[0]
        return .5*math.fsum((x-ox)*(v-oy)-(u-ox)*(y-oy)
                           for (x, y), (u, v) in zip(q, q[1:]+q[:1]))

    target = signed_area(p)
    for _ in range(5):
        error = target - signed_area(out)
        if abs(error) <= max(1e-9, abs(target)*1e-13):
            break
        direction = []
        slope = 0.
        for i, ((nx, ny), weight) in enumerate(zip(normals, weights)):
            if weight == 0:
                direction.append((0., 0.))
                continue
            gx = .5*(out[(i+1)%n][1]-out[i-1][1])
            gy = .5*(out[i-1][0]-out[(i+1)%n][0])
            g = gx*nx + gy*ny
            dx, dy = weight*g*nx, weight*g*ny
            direction.append((dx, dy))
            slope += weight*g*g
        if slope <= 1e-20:
            return p
        step = error/slope
        out = [(x+step*dx, y+step*dy) for (x, y), (dx, dy) in zip(out, direction)]
    return out


def damp_mesh_oscillations(points, *, strength=0.25):
    pts = [(float(x),float(y)) for x,y in points]
    if len(pts) < 5 or strength <= 0:
        return pts
    strength = min(0.25,float(strength))
    lap = [(0.,0.)]*len(pts)
    fixed = [True]*len(pts)
    for i in range(1,len(pts)-1):
        a,b,c = pts[i-1:i+2]
        ux,uy = b[0]-a[0],b[1]-a[1]
        vx,vy = c[0]-b[0],c[1]-b[1]
        length = math.hypot(ux,uy)*math.hypot(vx,vy)
        if length <= 1e-12 or (ux*vx+uy*vy)/length < math.cos(math.radians(45)):
            continue
        fixed[i] = False
        lap[i] = ((a[0]+c[0])*0.5-b[0],(a[1]+c[1])*0.5-b[1])
    out = list(pts)
    for i in range(2,len(pts)-2):
        if fixed[i-1] or fixed[i] or fixed[i+1]:
            continue
        # Tangential redistribution is left to equal_arc_resample. Damping only
        # normal motion avoids drift along the lip and preserves wall location.
        dx = -strength*((lap[i-1][0]+lap[i+1][0])*0.5-lap[i][0])
        dy = -strength*((lap[i-1][1]+lap[i+1][1])*0.5-lap[i][1])
        tx,ty = pts[i+1][0]-pts[i-1][0],pts[i+1][1]-pts[i-1][1]
        norm = math.hypot(tx,ty)
        if norm <= 1e-12:
            continue
        nx,ny = -ty/norm,tx/norm
        delta = dx*nx+dy*ny
        out[i] = (pts[i][0]+delta*nx,pts[i][1]+delta*ny)
    return out
