"""Validate both Helm paths plus protected GitOps output before any promotion."""
import json,os,subprocess,sys
from pathlib import Path
from github import GitHub
from model import manifest,release
from snapshot import prepare
root=Path(__file__).resolve().parents[1]
m=json.loads((root/'delivery/manifest.json').read_text());manifest(m,False)
if m['service']!='operator':
    sibling=root.parent/'operator-chart'
    if not sibling.exists():
        gh=GitHub();pin='914415c8defe8b8bc2fd40a62b7c9c4d390fff5b'
        (sibling/'crds').mkdir(parents=True)
        (sibling/'crds/upstream-crds.yaml').write_bytes(gh.file('SkyMist-Next/operator-chart','crds/upstream-crds.yaml',pin))
    subprocess.run([sys.executable,str(root/'tests/render.py')],check=True)
subprocess.run([sys.executable,'-m','unittest','discover','-s',str(root/'delivery'),'-p','test_*.py'],check=True)
fixture=dict(m,provides={},requires={},sourceSha='a'*40,image='registry.neomatik.eu/skymist/'+m['service']+'@sha256:'+'b'*64,runId=1,runAttempt=1)
prepare(root,release(fixture,'c'*40))
subprocess.run(['helm','lint',str(root),'-f',str(root/'delivery/environments/skymist.yaml')],check=True)
