"""Compatibility names for saved SFO3.10 recipes.

Existing recipes without explicit response parameters use the unchanged
3.10 coefficient set. The formula is shared with the generic model.
"""
from .calibrated_response import (
    nominal_gpc, growth_response, fill_fraction, apply_post_closure,
)

MODEL = "sfo310_calibrated_v1"
