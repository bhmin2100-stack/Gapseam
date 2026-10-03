"""Package only built binaries, never local recipes/results, for the personal channel."""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from gapsim import __version__

def package(built,output,commit):
    built=Path(built).resolve()
    output=Path(output).resolve()
    assert (built/'GFE.exe').is_file()
    assert (built/'_internal/gapsim/emulation/assets/gfe.ico').is_file()
    output.mkdir(parents=True,exist_ok=True)
    archive=output/'Gapseam.zip'
    files=[built/'GFE.exe']+sorted(p for p in (built/'_internal').rglob('*') if p.is_file())
    with ZipFile(archive,'w',ZIP_DEFLATED,compresslevel=6) as zipfile:
        for path in files:zipfile.write(path,Path('GFE')/path.relative_to(built))
    with ZipFile(archive) as zipfile:
        assert zipfile.testzip() is None
        assert 'GFE/GFE.exe' in zipfile.namelist()
        assert all(n.startswith('GFE/GFE.exe') or n.startswith('GFE/_internal/') for n in zipfile.namelist())
    digest=hashlib.file_digest(archive.open('rb'),'sha256').hexdigest()
    metadata=dict(version=__version__,asset='Gapseam.zip',sha256=digest,size=archive.stat().st_size,
        buildCommit=commit,buildId=commit[:12],updateChannel='personal',
        downloadUrl=f'https://github.com/bhmin2100-stack/Gapseam/releases/download/v{__version__}/Gapseam.zip')
    (output/'version.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    print(json.dumps(metadata,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--built',required=True)
    p.add_argument('--output',required=True)
    p.add_argument('--commit',required=True)
    a=p.parse_args()
    package(a.built,a.output,a.commit)
