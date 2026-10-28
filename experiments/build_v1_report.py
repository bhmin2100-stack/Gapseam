"""Standalone responsive report, computed profiles only, no fitted contours."""
import gzip, json
from pathlib import Path
import argparse

p=argparse.ArgumentParser();p.add_argument('directory',type=Path);a=p.parse_args();root=a.directory
cases=json.loads((root/'cases.json').read_text(encoding='utf8'))
rows=json.loads((root/'comparison.json').read_text(encoding='utf8'))
data=[]
for row in rows:
    key=row['case']; case=cases[key]
    pair=[]
    for side in ('baseline','candidate'):
        with gzip.open(root/side/(key+'.json.gz'),'rt',encoding='utf8') as f:r=json.load(f)['result']
        ix=sorted(set([0,*range(50,len(r['frame_profiles']),50),len(r['frame_profiles'])-1]))
        pair.append([{'cycle':r['frame_steps'][i],'profile':r['frame_profiles'][i],'voids':r['frame_voids'][i]} for i in ix])
    # Exact duplicate profiles need only one embedded copy; hashes above still
    # come from independent full-frame comparisons of both original records.
    data.append({**row,'config':case['config'],'old':None if pair[0]==pair[1] else pair[0],'new':pair[1]})
template=Path(__file__).with_name('v1-report-template.html').read_text(encoding='utf8')
(root/'gfe-1.0-report.html').write_text(template.replace('__DATA__',json.dumps(data,ensure_ascii=False,separators=(',',':'))),encoding='utf8')
print(root/'gfe-1.0-report.html')
