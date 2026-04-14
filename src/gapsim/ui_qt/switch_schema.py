from __future__ import annotations

from typing import Any, Dict, List

SwitchDef = Dict[str, Any]
ParamDef = Dict[str, Any]


PHASE1_SWITCH_SCHEMA: List[SwitchDef] = [
    {
        "id": "conformal",
        "title_key": "switch.conformal",
        "default_enabled": True,
        "params": [
            {
                "id": "base_rate",
                "label_key": "switch.param.base_rate",
                "type": "float",
                "default": 1.0,
                "min": 0.0,
                "max": 1e12,
                "decimals": 6,
                "step": 0.1,
                "tooltip_key": "switch.tip.base_rate",
            },
            {
                "id": "n_steps",
                "label_key": "switch.param.n_steps",
                "type": "int",
                "default": 200,
                "min": 1,
                "max": 10_000_000,
                "tooltip_key": "switch.tip.n_steps",
            },
            {
                "id": "reparam_preset",
                "label_key": "switch.param.reparam_preset",
                "type": "enum",
                "default": "manual",
                "options": ["manual", "fast", "normal", "detail"],
                "tooltip_key": "switch.tip.reparam_preset",
            },
            {
                "id": "reparam_ds_a",
                "label_key": "switch.param.reparam_ds_a",
                "type": "float",
                "default": 2.5,
                "min": 0.5,
                "max": 200.0,
                "decimals": 3,
                "step": 0.5,
                "tooltip_key": "switch.tip.reparam_ds_a",
            },
        ],
    },
    {
        "id": "attenuation",
        "title_key": "switch.attenuation",
        "default_enabled": False,
        "params": [
            {
                "id": "source_onset_width_a",
                "label_key": "switch.param.source_onset_width_a",
                "type": "float",
                "default": 0.0,
                "min": 0.0,
                "max": 1e12,
                "decimals": 6,
                "step": 1.0,
                "tooltip_key": "switch.tip.source_onset_width_a",
            },
            {
                "id": "source_decay_pct",
                "label_key": "switch.param.source_decay_pct",
                "type": "float",
                "default": 98.0,
                "min": 0.0,
                "max": 100.0,
                "decimals": 3,
                "step": 1.0,
                "tooltip_key": "switch.tip.source_decay_pct",
            },
            {
                "id": "source_distance_decay_pct",
                "label_key": "switch.param.source_distance_decay_pct",
                "type": "float",
                "default": 0.0,
                "min": 0.0,
                "max": 100.0,
                "decimals": 3,
                "step": 1.0,
                "tooltip_key": "switch.tip.source_distance_decay_pct",
            },
        ],
    },
    {
        "id": "sputter",
        "title_key": "switch.sputter",
        "default_enabled": False,
        "params": [
            {
                "id": "sputter_only",
                "label_key": "switch.param.sputter_only",
                "type": "bool",
                "default": False,
                "tooltip_key": "switch.tip.sputter_only",
            },
            {
                "id": "strength_pct",
                "label_key": "switch.param.sputter_strength_pct",
                "type": "float",
                "default": 0.0,
                "min": 0.0,
                "max": 10000.0,
                "decimals": 3,
                "step": 1.0,
                "tooltip_key": "switch.tip.sputter_strength_pct",
            },
            {
                "id": "peak_angle_deg",
                "label_key": "switch.param.sputter_peak_angle_deg",
                "type": "float",
                "default": 55.0,
                "min": 30.0,
                "max": 80.0,
                "decimals": 3,
                "step": 1.0,
                "tooltip_key": "switch.tip.sputter_peak_angle_deg",
            },
            {
                "id": "angle_sigma_deg",
                "label_key": "switch.param.sputter_angle_sigma_deg",
                "type": "float",
                "default": 15.0,
                "min": 1.0,
                "max": 40.0,
                "decimals": 3,
                "step": 1.0,
                "tooltip_key": "switch.tip.sputter_angle_sigma_deg",
            },
            {
                "id": "depth_decay_length_a",
                "label_key": "switch.param.sputter_depth_decay_length_a",
                "type": "float",
                "default": 1000.0,
                "min": 0.0,
                "max": 1000000.0,
                "decimals": 3,
                "step": 10.0,
                "tooltip_key": "switch.tip.sputter_depth_decay_length_a",
            },
            {
                "id": "vis_exponent",
                "label_key": "switch.param.sputter_vis_exponent",
                "type": "float",
                "default": 1.0,
                "min": 0.0,
                "max": 8.0,
                "decimals": 3,
                "step": 0.1,
                "tooltip_key": "switch.tip.sputter_vis_exponent",
            },
        ],
    },
    {
        "id": "redepo",
        "title_key": "switch.redepo",
        "default_enabled": False,
        "params": [
            {
                "id": "efficiency_pct",
                "label_key": "switch.param.redepo_efficiency_pct",
                "type": "float",
                "default": 50.0,
                "min": 0.0,
                "max": 100.0,
                "decimals": 3,
                "step": 1.0,
                "tooltip_key": "switch.tip.redepo_efficiency_pct",
            },
            {
                "id": "lobe_sigma_deg",
                "label_key": "switch.param.redepo_lobe_sigma_deg",
                "type": "float",
                "default": 20.0,
                "min": 1.0,
                "max": 60.0,
                "decimals": 3,
                "step": 1.0,
                "tooltip_key": "switch.tip.redepo_lobe_sigma_deg",
            },
        ],
    },
    {
        "id": "inhibition",
        "title_key": "switch.inhibition",
        "default_enabled": False,
        "params": [
            {
                "id": "i_max",
                "label_key": "switch.param.inhib_i_max",
                "type": "float",
                "default": 0.5,
                "min": 0.0,
                "max": 1.0,
                "decimals": 3,
                "step": 0.1,
                "tooltip_key": "switch.tip.inhib_i_max",
            },
            {
                "id": "lambda_a",
                "label_key": "switch.param.inhib_lambda_a",
                "type": "float",
                "default": 500.0,
                "min": 0.0,
                "max": 1000000.0,
                "decimals": 3,
                "step": 10.0,
                "tooltip_key": "switch.tip.inhib_lambda_a",
            },
        ],
    },
]


def default_switch_state() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for sw in PHASE1_SWITCH_SCHEMA:
        params: Dict[str, Any] = {}
        for p in sw.get("params", []):
            params[str(p["id"])] = p.get("default")
        out[str(sw["id"])] = {
            "enabled": bool(sw.get("default_enabled", False)),
            "params": params,
        }
    return out
