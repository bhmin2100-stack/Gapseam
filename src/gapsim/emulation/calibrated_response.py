"""Explicit, versioned empirical response parameters shared by named recipes.

This parameterizes the existing calibration algebra without claiming a new
physical mechanism. In particular closed-void filling remains empirical.
Evaluation candidate: the desktop parameter editor does not yet expose this.
"""
from contextvars import ContextVar
from dataclasses import asdict, dataclass, fields, replace
import math

MODEL = 'calibrated_response_v1'
nominal_gpc = ContextVar('calibrated_nominal_gpc', default=None)


@dataclass(frozen=True)
class ResponseParameters:
    version: int = 1
    growth_enabled: bool = False
    closure_enabled: bool = False
    dose_response_enabled: bool = True
    aspect_response_enabled: bool = True
    depth_reference: str = 'current_top'
    aspect_center: float = 4.
    aspect_width: float = .1
    static_aspect_weight: float = 1.
    dose_start_a: float = 310.
    dose_end_a: float = 600.
    dose_width_a: float = 5.
    deep_center_cd: float = 2.2
    deep_halfwidth_cd: float = .5
    deep_early_gain: float = -.25
    deep_middle_gain: float = .35
    upper_center_cd: float = .26
    upper_halfwidth_cd: float = .2
    upper_gain: float = .4
    relief_center_cd: float = .55
    relief_halfwidth_cd: float = .24
    relief_gain: float = .3
    fill_base: float = .2
    fill_shallow: float = .75
    fill_deep: float = .98
    fill_shallow_depth_nm: float = 400.
    fill_deep_depth_nm: float = 670.
    fill_transition_width_nm: float = 30.
    fill_peak1_depth_nm: float = 545.
    fill_peak1_width_nm: float = 60.
    fill_peak1_gain: float = .08
    fill_peak2_depth_nm: float = 442.
    fill_peak2_width_nm: float = 30.
    fill_peak2_gain: float = .65
    include_new_void_budget: bool = True
    fill_order: str = 'deep_first'


def load_parameters(value):
    if isinstance(value, ResponseParameters):
        return value
    if value is None:
        return ResponseParameters()
    if not isinstance(value, dict):
        raise ValueError('Empirical response parameters must be an object')
    unknown = value.keys() - ResponseParameters.__dataclass_fields__.keys()
    if unknown:
        raise ValueError(f'Unknown empirical response parameters: {sorted(unknown)}')
    p = ResponseParameters(**value)
    defaults = ResponseParameters()
    for f in fields(p):
        v = getattr(p, f.name)
        if isinstance(getattr(defaults, f.name), bool):
            if type(v) is not bool:
                raise ValueError(f'{f.name} must be boolean')
        elif isinstance(getattr(defaults, f.name), (int, float)):
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ValueError(f'{f.name} must be a finite number')
    if p.version != 1 or type(p.version) is not int:
        raise ValueError('Unsupported empirical response version')
    if p.depth_reference not in ('current_top', 'initial_top'):
        raise ValueError('Unsupported depth reference')
    if p.fill_order not in ('deep_first', 'uniform'):
        raise ValueError('Unsupported fill order')
    for name in ('aspect_width','dose_width_a','deep_halfwidth_cd','upper_halfwidth_cd',
                 'relief_halfwidth_cd','fill_transition_width_nm','fill_peak1_width_nm','fill_peak2_width_nm'):
        if getattr(p,name) <= 0:
            raise ValueError(f'{name} must be positive')
    for name in ('static_aspect_weight','fill_base','fill_shallow','fill_deep'):
        if not 0 <= getattr(p,name) <= 1:
            raise ValueError(f'{name} must be in [0, 1]')
    if not 0 <= p.dose_start_a <= p.dose_end_a:
        raise ValueError('Dose transition order must be nonnegative and increasing')
    return p


def sfo310_parameters():
    return ResponseParameters(growth_enabled=True, closure_enabled=True)


def parameters(cfg):
    value = cfg.empirical_response
    if value is None and cfg.recipe_model == 'sfo310_calibrated_v1':
        return sfo310_parameters()
    return load_parameters(value)


def _surface_y(state, cfg, p):
    return max(y for _,y in (cfg.points if p.depth_reference=='initial_top' else state.surface.points))


def growth_response(state, cfg, values, *, cycle_index):
    p=parameters(cfg)
    if not p.growth_enabled or not values:
        return values
    pts=state.surface.points
    if len(values)!=len(pts):
        raise RuntimeError('Empirical response flux and surface lengths differ')
    gpc=nominal_gpc.get()
    if gpc is None:gpc=float(cfg.angstrom_per_cycle)
    dose=state.meta.get('_sfo310_dose_override_a',float(cycle_index)*gpc)
    state.meta['_neck_research_nominal_dose_a']=dose
    surface=_surface_y(state,cfg,p)
    width=float(cfg.deposition_feature_width_a)
    if not math.isfinite(width) or width<=0:raise ValueError('Response reference width must be positive')
    aspect=float(cfg.deposition_feature_depth_a)/width
    def sigmoid(x):return 1/(1+math.exp(max(-60.,min(60.,x))))
    weight=sigmoid((aspect-p.aspect_center)/p.aspect_width) if p.aspect_response_enabled else p.static_aspect_weight
    state.meta['_neck_research_aspect_weight']=weight
    early=sigmoid((dose-p.dose_start_a)/p.dose_width_a) if p.dose_response_enabled else 1.
    end=sigmoid((dose-p.dose_end_a)/p.dose_width_a) if p.dose_response_enabled else 1.
    late=(1-early)*end
    out=[]
    for ratio,(_,y) in zip(values,pts):
        depth=max(0.,surface-y)/width
        u=(depth-p.deep_center_cd)/p.deep_halfwidth_cd
        mask=(1-u*u)**2 if abs(u)<1 else 0.
        # Preserve the original arithmetic order, including subtractive relief.
        adjustment=weight*mask*(p.deep_early_gain*early+p.deep_middle_gain*late)
        q=(depth-p.upper_center_cd)/p.upper_halfwidth_cd
        upper=(1-q*q)**2 if abs(q)<1 else 0.
        adjustment+=(1-weight)*p.upper_gain*upper
        q=(depth-p.relief_center_cd)/p.relief_halfwidth_cd
        relief=(1-q*q)**2 if abs(q)<1 else 0.
        adjustment-=(1-weight)*p.relief_gain*relief
        out.append(float(ratio)*max(0.,1+adjustment))
    return out


def fill_fraction(depth_nm, p=None):
    p=p or sfo310_parameters()
    def sigmoid(x):return 1/(1+math.exp(max(-60.,min(60.,x))))
    value=p.fill_base+(p.fill_shallow-p.fill_base)*sigmoid((depth_nm-p.fill_shallow_depth_nm)/p.fill_transition_width_nm)+(p.fill_deep-p.fill_base)*sigmoid((p.fill_deep_depth_nm-depth_nm)/p.fill_transition_width_nm)
    u=(depth_nm-p.fill_peak1_depth_nm)/p.fill_peak1_width_nm
    value+=p.fill_peak1_gain*math.exp(-.5*u*u)
    u=(depth_nm-p.fill_peak2_depth_nm)/p.fill_peak2_width_nm
    value+=p.fill_peak2_gain*math.exp(-.5*u*u)
    return min(1.,max(0.,value))


def apply_post_closure(state,cfg,*,nominal_depo_a,cycle_index,base_fill):
    import pyclipper
    from . import trench_depo as engine
    p=parameters(cfg)
    if not p.closure_enabled:
        return base_fill(state,cfg,nominal_depo_a=nominal_depo_a,cycle_index=cycle_index)
    voids=engine.OffsetBoolean.collect_void_air(state)
    previous=state.meta.get('_research_previous_voids',[])
    if p.include_new_void_budget and state.meta.get('depth_closure_detected',False) and voids:
        pc=pyclipper.Pyclipper()
        pc.AddPaths([v if pyclipper.Orientation(v) else v[::-1] for v in voids],pyclipper.PT_SUBJECT,True)
        if previous:pc.AddPaths([v if pyclipper.Orientation(v) else v[::-1] for v in previous],pyclipper.PT_CLIP,True)
        fresh=pc.Execute(pyclipper.CT_DIFFERENCE,pyclipper.PFT_NONZERO,pyclipper.PFT_NONZERO)
        if any(not pyclipper.Orientation(region) for region in fresh):
            tree=pc.Execute2(pyclipper.CT_DIFFERENCE,pyclipper.PFT_NONZERO,pyclipper.PFT_NONZERO)
            def components(node):
                found=[]
                if node.Contour and not node.IsHole:
                    area=abs(pyclipper.Area(node.Contour))-sum(abs(pyclipper.Area(c.Contour)) for c in node.Childs if c.IsHole)
                    found.append((node.Contour,area))
                for child in node.Childs:found.extend(components(child))
                return found
            areas=components(tree)
        else:areas=[(region,abs(pyclipper.Area(region))) for region in fresh]
        surface_y=_surface_y(state,cfg,p)
        for region,area_i2 in areas:
            area_a2=max(0.,area_i2)/(state.scale**2)
            if area_a2<=1.:continue
            depth_nm=max(0.,(surface_y-max(y/state.scale for _,y in region))/10.)
            state.meta['depth_post_closure_allowed_fill_area_a2']+=area_a2*fill_fraction(depth_nm,p)
    use=cfg
    if not state.meta.get('depth_closure_detected',False) and voids:
        surface_y=_surface_y(state,cfg,p)
        top_y=max(y/state.scale for v in voids for _,y in v)
        depth_nm=max(0.,(surface_y-top_y)/10.)
        use=replace(cfg,deposition_post_closure_fill_pct_line=fill_fraction(depth_nm,p))
    def deep_first(state,voids_i,*,target_fill_area_a2):
        remaining=max(0.,float(target_fill_area_a2));filled=0.
        for void in sorted(voids_i,key=lambda path:max(y for _,y in path)):
            if remaining<=1e-9:break
            amount=engine._fill_voids_by_area_budget(state,[void],target_fill_area_a2=remaining)
            if amount>remaining+1e-6:raise RuntimeError('Empirical fill exceeded its area budget')
            filled+=amount;remaining=max(0.,remaining-amount)
        return filled
    result=base_fill(state,use,nominal_depo_a=nominal_depo_a,cycle_index=cycle_index,
                     area_fill=deep_first if p.fill_order=='deep_first' else None)
    state.meta['_research_previous_voids']=engine.OffsetBoolean.collect_void_air(state)
    return result
