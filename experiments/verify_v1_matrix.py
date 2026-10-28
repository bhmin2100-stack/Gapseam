"""Independent old/new engine replay of the configurations loaded by the UI.

prepare: writes nine cases through real preset controls. run: isolated process
per case with a supplied source path. compare: hashes ALL saved geometry.
"""
import argparse, gzip, hashlib, json, os, sys, time
from dataclasses import asdict, replace
from pathlib import Path


def main():
    p=argparse.ArgumentParser()
    p.add_argument('mode', choices=('prepare','run','compare'))
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--source',type=Path)
    p.add_argument('--case')
    p.add_argument('--side',choices=('baseline','candidate'))
    a=p.parse_args(); out=a.output; out.mkdir(parents=True,exist_ok=True)
    if a.source: sys.path.insert(0,str(a.source))
    if a.mode=='prepare':
        import tempfile
        from unittest.mock import patch
        os.environ['QT_QPA_PLATFORM']='offscreen'
        root=Path(tempfile.mkdtemp(prefix='gfe-v1-matrix-'))
        for key,rel in [('GAPSIM_DATA_ROOT','data'),('GAPSIM_STRUCTURE_LIBRARY','structures.xlsx'),('GAPSIM_PARAMETER_LIBRARY','presets.json'),('GAPSIM_ADDON_ROOT','addons'),('GAPSIM_ADDON_STATE','addons.json')]:
            os.environ[key]=str(root/rel)
        from PySide6.QtWidgets import QApplication
        from gapsim.emulation.trench_depo_ui import TrenchDepoWindow
        from gapsim.emulation.builtin_presets import RECIPE_NAMES, STRUCTURE_NAMES
        app=QApplication([])
        with patch('gapsim.emulation.trench_depo_ui.QTimer.singleShot'): w=TrenchDepoWindow()
        w._set_workflow_step('progress')
        w.process_presets_fold.setChecked(True)
        cases={}
        for si,structure in enumerate(STRUCTURE_NAMES):
            w.cmb_structure_library.setCurrentIndex(w.cmb_structure_library.findData(structure))
            w.load_selected_structure_from_library()
            for ri,recipe in enumerate(RECIPE_NAMES):
                w.chk_preset_run_defaults.setChecked(True)
                w.cmb_parameter_preset.setCurrentIndex(w.cmb_parameter_preset.findData(recipe))
                w.btn_apply_parameter_preset.click()
                # Nominal GPC stays 0.56; full 1045 cycles, 2/5 nm evaluation grid.
                cfg=replace(w.current_config(),reparam_ds_a=50. if si==2 else 20.)
                assert cfg.cycles==1045 and cfg.angstrom_per_cycle==.56 and cfg.recipe_model=='calibrated_response_v1'
                assert cfg.sputter_enabled and cfg.redepo_enabled and cfg.inhibition_enabled
                cases[f's{si+1}-r{ri+1}']={'structure':structure,'recipe':recipe,'config':asdict(cfg)}
        (out/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf-8')
        w.close();print('Prepared',len(cases),'UI-loaded cases',flush=True)
    elif a.mode=='run':
        case=json.loads((out/'cases.json').read_text(encoding='utf-8'))[a.case]
        values=case['config']
        if a.side=='baseline':
            values.pop('empirical_response',None)
            values['recipe_model']={'SFO3.1':'legacy_calibrated_v1','SFO3.10':'sfo310_calibrated_v1','SFO3.10-HAR (시험)':'sfo310_har_experimental_v1'}[case['recipe']]
        from gapsim.emulation.trench_depo import TrenchDepoConfig,run_trench_depo
        values['points']=tuple(tuple(v) for v in values['points'])
        cfg=TrenchDepoConfig(**values); start=time.perf_counter()
        def progress(i,n):
            if i and i%250==0: print(a.case,a.side,i,n,round(time.perf_counter()-start,1),flush=True)
        result=run_trench_depo(cfg,progress_cb=progress)
        record={'config':asdict(cfg),'result':asdict(result),'seconds':time.perf_counter()-start}
        folder=out/a.side;folder.mkdir(exist_ok=True)
        with gzip.open(folder/(a.case+'.json.gz'),'wt',encoding='utf-8') as f: json.dump(record,f,ensure_ascii=False,allow_nan=False)
        print('DONE',a.case,a.side,round(record['seconds'],1),flush=True)
    else:
        cases=json.loads((out/'cases.json').read_text(encoding='utf-8')); records=[]
        def read(path):
            with gzip.open(path,'rt',encoding='utf-8') as f:return json.load(f)
        def norm(value):
            if isinstance(value,dict):return {k:('common' if k=='recipe_model' else norm(v)) for k,v in value.items() if k!='empirical_response'}
            if isinstance(value,list):return [norm(v) for v in value]
            return value
        def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        for key,case in cases.items():
            b,c=[read(out/side/(key+'.json.gz')) for side in ('baseline','candidate')]
            expected=case['config']
            inputs_exact = norm(b['config'])==norm(c['config'])==norm(expected)
            fields=('frame_profiles','frame_voids','frame_steps','final_profile')
            exact={f:b['result'][f]==c['result'][f] for f in fields}
            records.append(dict(case=key,structure=case['structure'],recipe=case['recipe'],
                exact=exact,passed=all(exact.values()) and inputs_exact and norm(b['result']['meta'])==norm(c['result']['meta']),
                inputs_exact=inputs_exact,frames=len(c['result']['frame_profiles']),
                metadata_exact=norm(b['result']['meta'])==norm(c['result']['meta']),
                baseline_hash=digest({f:b['result'][f] for f in fields}),candidate_hash=digest({f:c['result'][f] for f in fields}),
                seconds=c['seconds'],spacing_a=case['config']['reparam_ds_a'],
                final_void_count=len(c['result']['frame_voids'][-1])))
        (out/'comparison.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps([{'case':r['case'],'passed':r['passed'],'metadata_exact':r['metadata_exact']} for r in records]))


if __name__=='__main__':main()
