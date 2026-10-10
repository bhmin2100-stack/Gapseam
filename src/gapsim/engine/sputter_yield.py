"""Optional semi-empirical angular yield; not an energy-resolved SFO fit.

Y(theta) ~ cos(theta)^(-f) exp[f*cos(theta_opt)*(1-1/cos(theta))].
Normalized at theta_opt, not normal incidence. See Ertl et al., SISPAD2010,
https://www.iue.tuwien.ac.at/pdf/ib_2010/CP2010_Ertl_1.pdf, equation 2.
No surface coordinates or desired contour occur in this material response.
"""
import math
import numpy as np
from .incident_ions import validate_incident_parameters,visible_from_direction


def yamamura_yield(cosine,peak=72.,exponent=2.36):
    c=np.asarray(cosine,float)
    if not np.isfinite(c).all() or np.any(c<0) or np.any(c>1):
        raise ValueError('Cosine must be finite in [0,1]')
    if not math.isfinite(peak) or not 0<=peak<90 or not math.isfinite(exponent) or exponent<=0:
        raise ValueError('Peak in [0,90) and positive exponent required')
    cp=math.cos(math.radians(peak));safe=np.maximum(c,1e-15)
    # Subtract the analytic log maximum. Avoid overflow at grazing incidence.
    logy=exponent*(np.log(cp/safe)+1-cp/safe)
    return np.where(c>0,np.exp(np.minimum(logy,0)),0.)


def yamamura_integral(points,normals,*,sigma=10.,rays=25,peak=72.,width=14.,amplitude=1.,exponent=2.36):
    sigma,rays=validate_incident_parameters(sigma,rays)
    if len(points)!=len(normals):raise ValueError('Aligned geometry required')
    if not math.isfinite(amplitude) or amplitude<0:raise ValueError('Nonnegative finite amplitude required')
    yamamura_yield([],peak,exponent)
    angles=np.radians(np.linspace(-4*sigma,4*sigma,rays))
    weights=np.exp(-.5*(np.degrees(angles)/sigma)**2);weights[[0,-1]]*=.5;weights/=weights.sum()
    n=np.asarray(normals,float);raw,exposed,flux=(np.zeros(len(points)) for _ in range(3))
    if not len(points):return raw,exposed,flux
    for a,w in zip(angles,weights):
        c=np.clip(n@np.array([math.sin(a),math.cos(a)]),0,1)
        clear=visible_from_direction(points,a);incident=w*c
        y=amplitude*yamamura_yield(c,peak,exponent)
        raw+=incident*y;exposed+=incident*y*clear;flux+=incident*clear
    return raw,exposed,flux
