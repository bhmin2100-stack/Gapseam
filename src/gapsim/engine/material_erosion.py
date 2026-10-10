"""Normal-ray film/substrate etch allocation for opt-in research.

Thickness and dose use the caller's length unit. Selectivity is substrate
removal / film removal at the same ion dose; 1 is the single-material limit.
This does not infer ion energy or material composition from a contour.
"""
import math
import numpy as np
import pyclipper


def allocate_erosion(dose, film_thickness, substrate_ratio):
    d,t=np.asarray(dose,float),np.asarray(film_thickness,float)
    if not math.isfinite(substrate_ratio) or substrate_ratio<0:
        raise ValueError('Nonnegative finite substrate selectivity required')
    if d.shape!=t.shape or np.any(~np.isfinite(d)) or np.any(d<0) or np.any(np.isnan(t)) or np.any(t<0):
        raise ValueError('Aligned nonnegative dose and film thickness required')
    film=np.minimum(d,t)
    substrate=np.maximum(d-film,0)*substrate_ratio
    return film+substrate,film,substrate


def normal_film_thickness(points,normals,substrate_paths,scale):
    """Distance from air-facing surface into the *remaining original* substrate.

    Supports closed polygons and holes using parity. Geometry is material-mask
    limited, not depth/target limited. An absent substrate means infinite film.
    """
    p,n=np.asarray(points,float),np.asarray(normals,float)
    if p.shape!=n.shape or p.ndim!=2 or p.shape[1]!=2 or not np.isfinite(p).all() or not np.isfinite(n).all() or scale<=0:
        raise ValueError('Aligned finite 2D coordinates and positive scale required')
    length=np.linalg.norm(n,axis=1)
    if np.any(length<1e-12):raise ValueError('Nonzero normals required')
    d=-n/length[:,None];out=np.full(len(p),np.inf)
    for i,point in enumerate(p):
        ip=tuple(int(round(v*scale)) for v in point)
        tests=[pyclipper.PointInPolygon(ip,path) for path in substrate_paths if len(path)>=3]
        if -1 in tests or sum(v==1 for v in tests)%2:out[i]=0.
    starts=[];vectors=[]
    for path in substrate_paths:
        if len(path)<3:continue
        a=np.asarray(path,float)/scale
        starts.extend(a);vectors.extend(np.roll(a,-1,axis=0)-a)
    if not starts:return out
    a,s=np.asarray(starts),np.asarray(vectors)
    # Chunked intersections avoid quadratic temporary growth for large masks.
    for start in range(0,len(p),128):
        pp,dd=p[start:start+128],d[start:start+128]
        q=a[None,:,:]-pp[:,None,:]
        den=dd[:,0,None]*s[None,:,1]-dd[:,1,None]*s[None,:,0]
        with np.errstate(divide='ignore',invalid='ignore'):
            t=(q[:,:,0]*s[None,:,1]-q[:,:,1]*s[None,:,0])/den
            u=(q[:,:,0]*dd[:,1,None]-q[:,:,1]*dd[:,0,None])/den
        hit=(abs(den)>1e-12)&(t>=-1e-9)&(u>=-1e-9)&(u<=1+1e-9)
        nearest=np.min(np.where(hit,np.maximum(t,0),np.inf),axis=1)
        out[start:start+len(pp)]=np.minimum(out[start:start+len(pp)],nearest)
    return out


def shadow_growth_ratio(activation, unexposed_ratio=1., saturation_dose=1.):
    """Measured unexposed-GPC / exposed-NPW-GPC, with saturating ion effect.

    Dimensionless dose relative to a characteristic growth-response dose. No
    invented conversion to eV, LF power or process time. R=1 disables response.
    """
    a=np.asarray(activation,float)
    if not np.isfinite(a).all() or np.any(a<0) or np.any(a>1):raise ValueError('Activation in [0,1] required')
    if not math.isfinite(unexposed_ratio) or unexposed_ratio<=0 or not math.isfinite(saturation_dose) or saturation_dose<=0:
        raise ValueError('Positive finite growth ratio and dose required')
    exposure=-np.expm1(-saturation_dose*a)/(-math.expm1(-saturation_dose))
    return unexposed_ratio+(1-unexposed_ratio)*exposure
