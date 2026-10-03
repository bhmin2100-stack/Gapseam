"""Reviewed 2026-10-03 synthetic trench study; not calibrated process recipes."""
from .trench_depo import TrenchDepoConfig

INCIDENT_PRESET_DOSES = (300, 500, 750, 1000, 1250, 1500, 1750, 2000)
SFO31_PRESET_NAME = 'SFO3.1'
INCIDENT_STUDY_POINTS = ((5000., 0.), (250., 0.), (250., -2200.),
                         (-250., -2200.), (-250., 0.), (-5000., 0.))


def incident_study_preset(dose_a=300):
    """Gross deposition dose, not net film thickness. Preserve dose/etch ratio."""
    if dose_a not in INCIDENT_PRESET_DOSES:
        raise ValueError("Unsupported incident-ion study thickness")
    return TrenchDepoConfig(
        points=INCIDENT_STUDY_POINTS, emulator_number=0, cycles=int(dose_a // 2),
        angstrom_per_cycle=2., reparam_ds_a=5., sputter_enabled=True,
        sputter_strength_a_per_cycle=8./3., sputter_peak_pct=100.,
        sputter_peak_angle_deg=55., sputter_width_deg=40., sputter_smoothing_a=20.,
        ion_transmission_enabled=False, redepo_enabled=True,
        redepo_incident_los_enabled=True, redepo_incident_sigma_deg=10.,
        redepo_incident_ray_count=25, redepo_efficiency_pct=90.,
        redepo_emit_power=5., redepo_distance_power=50.,
        redepo_max_distance_a=1800., deposition_feature_width_a=500.,
        deposition_feature_depth_a=2200.,
    )


def sfo31_preset():
    """One editable process preset; dose sweeps belong to research, not this preset."""
    return incident_study_preset(300)


def ensure_sfo31_preset(path):
    """Seed the normal user library once; preserve user-edited and other presets."""
    from .parameter_library import list_parameter_presets, save_parameter_preset
    if SFO31_PRESET_NAME not in list_parameter_presets(path):
        save_parameter_preset(path, SFO31_PRESET_NAME, sfo31_preset(), emulator_number=0)
