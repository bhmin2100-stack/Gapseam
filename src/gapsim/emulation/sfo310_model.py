"""SFO3.10 empirical calibration, isolated per run and geometry independent.

The coefficients reproduce the separately validated research candidate. This
is an effective shape model, not a validated physical post-closure mechanism.
"""
from contextvars import ContextVar
from dataclasses import replace
import math
import pyclipper

MODEL = "sfo310_calibrated_v1"
nominal_gpc = ContextVar("sfo310_nominal_gpc", default=None)


def growth_response(state, cfg, values, *, cycle_index):
    if not values:
        return values
    pts = state.surface.points
    if len(values) != len(pts):
        raise RuntimeError("SFO3.10 flux and surface lengths differ")
    gpc = nominal_gpc.get()
    if gpc is None:
        gpc = float(cfg.angstrom_per_cycle)
    dose = state.meta.get("_sfo310_dose_override_a", float(cycle_index) * gpc)
    state.meta["_neck_research_nominal_dose_a"] = dose
    surface = max(y for _, y in pts)
    width = float(cfg.deposition_feature_width_a)
    aspect = float(cfg.deposition_feature_depth_a) / width
    def sigmoid(x):
        return 1 / (1 + math.exp(max(-60., min(60., x))))
    aspect_weight = sigmoid((aspect - 4.) / .1)
    state.meta["_neck_research_aspect_weight"] = aspect_weight
    early = sigmoid((dose - 310.) / 5.)
    end = sigmoid((dose - 600.) / 5.)
    late = (1 - early) * end
    out = []
    for ratio, (_, y) in zip(values, pts):
        depth = max(0., surface - y) / width
        u = (depth - 2.2) / .5
        mask = (1 - u*u)**2 if abs(u) < 1 else 0.
        adjustment = aspect_weight * mask * (-.25 * early + .35 * late)
        q = (depth - .26) / .2
        upper = (1 - q*q)**2 if abs(q) < 1 else 0.
        adjustment += (1 - aspect_weight) * .4 * upper
        q = (depth - .55) / .24
        relief = (1 - q*q)**2 if abs(q) < 1 else 0.
        adjustment -= (1 - aspect_weight) * .3 * relief
        out.append(float(ratio) * max(0., 1 + adjustment))
    return out


def fill_fraction(depth_nm):
    def sigmoid(x):
        return 1 / (1 + math.exp(max(-60., min(60., x))))
    value = .2 + (.75-.2)*sigmoid((depth_nm-400.)/30.) + (.98-.2)*sigmoid((670.-depth_nm)/30.)
    u = (depth_nm-545.)/60.
    value += .08 * math.exp(-.5*u*u)
    u = (depth_nm-442.)/30.
    value += .65 * math.exp(-.5*u*u)
    return min(1., value)


def apply_post_closure(state, cfg, *, nominal_depo_a, cycle_index, base_fill):
    from . import trench_depo as engine
    voids = engine.OffsetBoolean.collect_void_air(state)
    previous = state.meta.get("_research_previous_voids", [])
    if state.meta.get("depth_closure_detected", False) and voids:
        pc = pyclipper.Pyclipper()
        pc.AddPaths([v if pyclipper.Orientation(v) else v[::-1] for v in voids], pyclipper.PT_SUBJECT, True)
        if previous:
            pc.AddPaths([v if pyclipper.Orientation(v) else v[::-1] for v in previous], pyclipper.PT_CLIP, True)
        fresh = pc.Execute(pyclipper.CT_DIFFERENCE, pyclipper.PFT_NONZERO, pyclipper.PFT_NONZERO)
        if any(not pyclipper.Orientation(region) for region in fresh):
            tree = pc.Execute2(pyclipper.CT_DIFFERENCE, pyclipper.PFT_NONZERO, pyclipper.PFT_NONZERO)
            def components(node):
                found = []
                if node.Contour and not node.IsHole:
                    area = abs(pyclipper.Area(node.Contour))-sum(abs(pyclipper.Area(c.Contour)) for c in node.Childs if c.IsHole)
                    found.append((node.Contour, area))
                for child in node.Childs:
                    found.extend(components(child))
                return found
            areas = components(tree)
        else:
            areas = [(region, abs(pyclipper.Area(region))) for region in fresh]
        surface_y = max(y for _, y in state.surface.points)
        for region, area_i2 in areas:
            area_a2 = max(0., area_i2) / (state.scale**2)
            if area_a2 <= 1.:
                continue
            depth_nm = max(0., (surface_y - max(y/state.scale for _, y in region))/10.)
            state.meta["depth_post_closure_allowed_fill_area_a2"] += area_a2 * fill_fraction(depth_nm)
    use = cfg
    if not state.meta.get("depth_closure_detected", False) and voids:
        surface_y = max(y for _, y in state.surface.points)
        top_y = max(y/state.scale for v in voids for _, y in v)
        depth_nm = max(0., (surface_y - top_y)/10.)
        use = replace(cfg, deposition_post_closure_fill_pct_line=fill_fraction(depth_nm))
    def deep_first(state, voids_i, *, target_fill_area_a2):
        remaining = max(0., float(target_fill_area_a2))
        filled = 0.
        for void in sorted(voids_i, key=lambda p: max(y for _, y in p)):
            if remaining <= 1e-9:
                break
            amount = engine._fill_voids_by_area_budget(state, [void], target_fill_area_a2=remaining)
            if amount > remaining + 1e-6:
                raise RuntimeError("SFO3.10 fill exceeded its area budget")
            filled += amount
            remaining = max(0., remaining-amount)
        return filled
    result = base_fill(state, use, nominal_depo_a=nominal_depo_a, cycle_index=cycle_index, area_fill=deep_first)
    state.meta["_research_previous_voids"] = engine.OffsetBoolean.collect_void_air(state)
    return result
