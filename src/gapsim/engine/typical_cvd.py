"""Bounded, empirical CVD shape controls, not a calibrated reactor solver.

This deposition-only field distinguishes broad upper-wall overhang from localized
corner cusping. It neither generates sputter sources nor transports redeposition.
The knobs describe growth tendencies, not guaranteed final geometric dimensions.
"""
from __future__ import annotations

import math
from gapsim.engine.deposition_pipeline import VertexNormalPropagator

DEFAULTS = dict(cvd_enabled=False, cvd_overhang_pct=30.0, cvd_cusping_pct=20.0,
                cvd_bottom_ratio_pct=50.0, cvd_upper_length_a=200.0,
                cvd_depth_power=1.2)


def config_values(config):
    return {name: getattr(config, name) for name in DEFAULTS}


def validate(config):
    for name, low, high in [('cvd_overhang_pct', 0, 200), ('cvd_cusping_pct', 0, 200),
                            ('cvd_bottom_ratio_pct', 0, 100), ('cvd_upper_length_a', .5, 10000),
                            ('cvd_depth_power', .2, 6)]:
        value = float(getattr(config, name))
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'{name} must be finite and in [{low}, {high}]')


def growth_bound(config):
    return 1 + (config.cvd_overhang_pct + config.cvd_cusping_pct) / 100


def reference_geometry(points):
    """Infer a single opening from first/last below-field vertices, without edits."""
    pts=sorted(points,key=lambda p:p[0])
    if len(pts)<3:
        raise ValueError('폭·깊이 추정에는 트랜치 형상 점이 필요합니다.')
    top=(pts[0][1]+pts[-1][1])/2
    below=[i for i,(_,y) in enumerate(pts) if y<top-1e-6]
    if not below or below[0]==0 or below[-1]==len(pts)-1:
        raise ValueError('열린 단일 트랜치의 평탄부와 내부를 찾을 수 없습니다. 기준 값을 직접 입력하세요.')
    width=pts[below[-1]+1][0]-pts[below[0]-1][0]
    depth=top-min(y for _,y in pts)
    if width<=0 or depth<=0:raise ValueError('유효한 폭·깊이가 아닙니다.')
    return width,depth


def growth_ratios(points, config):
    """Positive normal growth relative to nominal flat deposition.

    Bottom ratio is the base flux at the *reference feature depth*, before
    upper-localized enhancements or inhibition. Endpoints define the field plane.
    Single centered feature approximation; no chemistry or precursor mass balance.
    """
    validate(config)
    if len(points) < 2:
        return [1.] * len(points)
    normals = VertexNormalPropagator._vertex_air_normals(points)
    top = (points[0][1] + points[-1][1]) / 2
    center = (points[0][0] + points[-1][0]) / 2
    depth = max(.5, float(config.deposition_feature_depth_a))
    half_width = max(.5, float(config.deposition_feature_width_a) / 2)
    length = config.cvd_upper_length_a
    bottom = config.cvd_bottom_ratio_pct / 100
    result = []
    for (x, y), (nx, ny) in zip(points, normals):
        z = max(0., top - y)
        base = 1 - (1-bottom) * min(1., z/depth)**config.cvd_depth_power
        upper = math.exp(-(z/length)**2)
        shoulder = math.exp(-((abs(x-center)-half_width)/length)**2)
        overhang = config.cvd_overhang_pct/100 * upper * nx*nx
        cusp = config.cvd_cusping_pct/100 * upper * shoulder * 4*nx*nx*ny*ny
        result.append(base * (1 + overhang + cusp))
    return result
