"""Versioned, normalized empirical depth laws; no expression evaluation or clipping."""
from dataclasses import asdict, dataclass, fields
import math
from typing import Mapping

import numpy as np

MODEL = 'depth_formula_v1'
LAW_NAMES = {'exponential': '지수식', 'linear_exp': '선형·지수식', 'cubic': '3차식'}
PRESET_LAWS = {
    '깊이 지수식 (시험)': 'exponential',
    '깊이 선형·지수식 (시험)': 'linear_exp',
    '깊이 3차식 (시험)': 'cubic',
}
MAX_RATIO = 1000.  # Refuse extreme extrapolation; never cap the calculated rate.


@dataclass(frozen=True)
class Parameters:
    version: int = 1
    law: str = 'exponential'
    depth_unit: str = 'nm'
    reference: str = 'initial_top'
    decay_per_nm: float = .000829
    linear_slope: float = .0001
    linear_constant: float = .2134
    linear_exp_gain: float = .0282
    linear_length: float = 100.
    cubic_a: float = -6e-10
    cubic_b: float = -6e-7
    cubic_c: float = -.0002
    cubic_d: float = .423


def load_parameters(value=None):
    if isinstance(value, Parameters):
        p = value
    else:
        if value is not None and not isinstance(value, Mapping):
            raise ValueError('깊이식 파라미터는 이름과 값의 목록이어야 합니다.')
        unknown = set(value or {}) - {f.name for f in fields(Parameters)}
        if unknown:
            raise ValueError(f'알 수 없는 깊이식 파라미터: {sorted(unknown)}')
        p = Parameters(**(value or {}))
    if p.version != 1 or isinstance(p.version, bool):
        raise ValueError('지원하지 않는 깊이식 버전입니다.')
    if p.law not in LAW_NAMES or p.depth_unit not in ('nm', 'A') or p.reference not in ('initial_top', 'current_field'):
        raise ValueError('깊이식 종류·단위·기준을 확인하세요.')
    for f in fields(Parameters):
        if f.name not in ('version', 'law', 'depth_unit', 'reference'):
            v = getattr(p, f.name)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ValueError(f'깊이식 계수 {f.name}는 유한한 숫자여야 합니다.')
    if p.decay_per_nm < 0 or p.linear_length <= 0:
        raise ValueError('감쇠계수는 0 이상, 지수 길이는 0보다 커야 합니다.')
    if float(raw_value(0., p)) <= 0:
        raise ValueError('깊이식의 평탄부 값 f(0)은 0보다 커야 합니다.')
    return p


def raw_value(depth_a, p):
    d = np.asarray(depth_a, dtype=float)
    if not np.all(np.isfinite(d)) or np.any(d < 0):
        raise ValueError('깊이는 0 이상의 유한한 값이어야 합니다.')
    if p.law == 'exponential':
        # Original signed AR and k cancel CD: exp(-0.0000829 * depth_A).
        return np.exp(-p.decay_per_nm*d/10.)
    z = -d/(10. if p.depth_unit == 'nm' else 1.)
    if p.law == 'linear_exp':
        return p.linear_slope*z + p.linear_constant + p.linear_exp_gain*(1-z/p.linear_length)*np.exp(z/p.linear_length)
    return p.cubic_a*z**3 + p.cubic_b*z**2 + p.cubic_c*z + p.cubic_d


def growth_ratios(depth_a, p):
    with np.errstate(over='ignore', invalid='ignore'):
        result = raw_value(depth_a, p)/float(raw_value(0., p))
    if not np.all(np.isfinite(result)):
        raise ValueError('깊이식이 유한한 성장률을 만들지 못합니다. 계수와 깊이 단위를 확인하세요.')
    if np.any(result < 0):
        raise ValueError('깊이식이 현재 구조에서 음수 성장률을 만듭니다. 깊이 단위·계수·적용 깊이를 확인하세요. 음수를 0이나 식각량으로 바꾸지 않습니다.')
    if np.any(result > MAX_RATIO):
        raise ValueError(f'깊이식이 평탄부의 {MAX_RATIO:g}배를 넘습니다. 미검증 외삽을 중단했습니다. 계수와 깊이 단위를 확인하세요.')
    return result


def _critical_depths(max_depth_a, p):
    """Include interior extrema, not just vertices or a coarse depth grid."""
    scale = 10. if p.depth_unit == 'nm' else 1.
    end = max_depth_a/scale
    candidates = [0., end]
    if p.law == 'cubic':
        # z=-u => derivative in u: -3*a*u^2 + 2*b*u - c.
        coefficients = np.trim_zeros(np.array([-3*p.cubic_a, 2*p.cubic_b, -p.cubic_c]), 'f')
        if len(coefficients) > 1:
            for root in np.roots(coefficients):
                if abs(root.imag) < 1e-8 and 0 < root.real < end:
                    candidates.append(float(root.real))
    elif p.law == 'linear_exp':
        def derivative(u):
            return -p.linear_slope-p.linear_exp_gain*u/p.linear_length**2*math.exp(-u/p.linear_length)
        # u*exp(-u/L) is monotone on either side of L: at most two roots.
        cuts = sorted(set((0., min(end, p.linear_length), end)))
        for lo, hi in zip(cuts, cuts[1:]):
            if derivative(lo)*derivative(hi) < 0:
                for _ in range(60):
                    mid = (lo+hi)/2
                    if derivative(lo)*derivative(mid) <= 0: hi = mid
                    else: lo = mid
                candidates.append((lo+hi)/2)
        candidates.extend(cuts)
    return np.array(candidates)*scale


def validate_config(config):
    if config.recipe_model != MODEL:
        return None
    p = load_parameters(config.depth_formula)
    ys = [float(y) for x, y in config.points]
    if not ys or not all(math.isfinite(y) for y in ys):
        raise ValueError('깊이식에는 유한한 입력 구조가 필요합니다.')
    growth_ratios(_critical_depths(max(ys)-min(ys), p), p)
    return p


def ratios_at_points(points, p, initial_top_a):
    ys = np.asarray(points, dtype=float)[:, 1]
    origin = initial_top_a if p.reference == 'initial_top' else float(ys.max())
    return growth_ratios(np.maximum(0., origin-ys), p)


def description(p):
    if p.law == 'exponential':
        return f'r(d) = exp(−{p.decay_per_nm:g} × d_nm)'
    if p.law == 'linear_exp':
        formula = f'{p.linear_slope:g}z + {p.linear_constant:g} + {p.linear_exp_gain:g}(1−z/{p.linear_length:g})exp(z/{p.linear_length:g})'
    else:
        formula = f'{p.cubic_a:g}z³ + {p.cubic_b:g}z² + {p.cubic_c:g}z + {p.cubic_d:g}'
    return f'f(z) = {formula}; r = f(z)/f(0)'
