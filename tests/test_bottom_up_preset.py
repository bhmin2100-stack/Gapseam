from dataclasses import asdict, replace
import math

import numpy as np

from test_incident_preset_ui import window
from gapsim.emulation.builtin_presets import BOTTOM_UP_PRESET, recipe_config
from gapsim.emulation.process_recipe import _growth_ratios
from gapsim.emulation.trench_depo import run_trench_depo
from gapsim.emulation.trench_depo_export import result_to_payload, payload_to_trench_run
from gapsim.engine.deposition_pipeline import equal_arc_resample


def test_bottom_up_apply_preserves_geometry_and_cycles_and_enables_inhibition(window):
    geometry=window.current_config().points
    window.spin_cycles.setValue(37)
    window.cmb_parameter_preset.setCurrentIndex(window.cmb_parameter_preset.findData(BOTTOM_UP_PRESET))
    window.btn_apply_parameter_preset.click()
    c=window.current_config()
    assert c.points==geometry and c.cycles==37
    assert c.recipe_model=='physical_transport_v1' and c.depth_formula is None
    assert c.inhibition_enabled and not c.sputter_enabled and not c.redepo_enabled
    assert c.inhibitor_exposure==2. and c.inhibitor_sticking==.7
    assert c.ald_exposure==10. and c.precursor_sticking==.01
    assert c.deposition_post_closure_fill_pct_hole==c.deposition_post_closure_fill_pct_line==0.


def test_bottom_up_rate_is_positive_bounded_and_reference_calibrated():
    c=recipe_config(BOTTOM_UP_PRESET)
    flat,_=_growth_ratios([(-100.,0.),(100.,0.)],c)
    np.testing.assert_allclose(flat,1.,atol=1e-10)
    p=equal_arc_resample([(-2000.,0.),(-500.,0.),(-500.,-4000.),
                         (500.,-4000.),(500.,0.),(2000.,0.)],100.)
    ratios,_=_growth_ratios(p,c)
    assert np.all(ratios>0) and max(ratios)<=math.exp(2.)/(1-math.exp(-10.))+1e-8
    a=np.array(p)
    upper=ratios[(a[:,0]>0)&(a[:,1]<-100)&(a[:,1]>-400)].mean()
    lower=ratios[(a[:,0]>0)&(a[:,1]<-2500)&(a[:,1]>-3500)].mean()
    assert lower>2*upper


def test_bottom_up_open_front_advances_without_filling_a_sealed_void():
    # Scale-invariant straight trench: 10 nm CD, 40 nm depth, 2 nm field.
    c=replace(recipe_config(BOTTOM_UP_PRESET),
        points=[(-200.,0.),(-50.,0.),(-50.,-400.),(50.,-400.),(50.,0.),(200.,0.)],
        angstrom_per_cycle=.5,cycles=40,reparam_ds_a=5.,numerical_step_a=.5,transport_ray_count=16)
    r=run_trench_depo(c)
    assert -min(y for x,y in r.final_profile)<60.  # <6 nm left open out of 40 nm.
    assert all(not loops for loops in r.frame_voids)
    depths=[-min(y for x,y in p) for p in r.frame_profiles]
    assert all(a>=b-.05 for a,b in zip(depths,depths[1:]))
    restored,replay,_=payload_to_trench_run(result_to_payload(c,r,request_note='bottom-up trial'))
    assert asdict(restored)==asdict(c) and replay.final_profile==r.final_profile
