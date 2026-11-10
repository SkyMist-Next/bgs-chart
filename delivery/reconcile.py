"""Trusted-source promotion, resumable observation, and explicit immutable recovery."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
from github import GitHub, Lease
from model import SERVICES, compatible, enqueue, initial, observe, release, reserve, select
from snapshot import prepare
from verify import evidence, diagnostics, kube


def report(message):
    print(message)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as output:output.write(message+'\n\n')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--recover',default='');args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    chart=json.loads((root/'delivery/manifest.json').read_text());service=chart['service'];repo='SkyMist-Next/'+service+'-chart'
    gh=GitHub();branch='master' if service=='bgs' else 'main'
    sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
    if gh.ref(repo,branch)!=sha:raise ValueError('Stale chart workflow; reconcile current default branch')
    state_sha,state=gh.state(repo);state=state or initial()
    def save():
        nonlocal state_sha
        state_sha=gh.save(repo,state_sha,state)
    # Expiry processing does not need the global lock: it cannot promote anything.
    if state['pending'] and time.time()>=state['pending']['deadline']:
        state=observe(state,int(time.time()),False);save()
    head,value=gh.trusted_candidate(service)
    if value:
        updated=enqueue(state,value)
        if updated!=state:state=updated;save()
    if not state['enabled']:
        report('Delivery disabled pending reviewed baseline adoption');return
    lease=Lease(gh,os.environ.get('GITHUB_RUN_ID','local')+':'+os.environ.get('GITHUB_RUN_ATTEMPT','1'))
    if not lease.acquire():
        report('Waiting: another service is promoting; periodic reconciliation will retry');return
    try:
        if not state['pending']:
            selected=select(state,chart,head)
            if selected:
                proposed=release(selected,sha)
                if proposed['id'] not in state['releases']:
                    files,jobs=prepare(root,proposed,project=kube('-n','argocd','get','appproject','skymist-'+service,'-o','json')['spec'])
                    archive=gh.commit(repo,'delivery-releases',gh.ref(repo,'delivery-releases'),files,'Archive '+proposed['id'],replace=True)
                    state['releases'][proposed['id']]={**proposed,'archive':archive,'jobs':jobs}
                    save()
            if state['paused'] and not args.recover:
                report('Promotion paused: '+state['paused']['reason']+'. Select a recorded release ID through explicit recovery.');return
            if args.recover:
                if args.recover not in state['releases']:raise ValueError('Recovery requires a recorded immutable release ID')
                target=state['releases'][args.recover]
            else:
                selected=select(state,chart,head)
                if not selected:
                    report('Waiting for matching application/chart contract');return
                target=state['releases'][release(selected,sha)['id']]
            deployed={};healthy={}
            for other in SERVICES:
                _,s=gh.state('SkyMist-Next/'+other+'-chart')
                if not s or not s['lastSuccessful']:continue
                r=s['releases'][s['lastSuccessful']];deployed[other]=r
                healthy[other]=False
                if other in target['requires'] and not s['paused'] and not s['pending']:
                    try:healthy[other]=evidence(other,r['snapshot'],r['image'],r['jobs'])[0]
                    except (subprocess.SubprocessError,KeyError,ValueError):pass
            ok,reason=compatible(target,deployed,healthy)
            if not ok:
                report('Waiting: '+reason);return
            if not args.recover and target['id']==state['lastSuccessful']:
                report('Release already accepted: '+state['lastSuccessful']);return
            # A recovery uses the original exact snapshot contents, not today's chart.
            if args.recover:
                files={}
                tree=gh.api(f'repos/{repo}/git/trees/{target.get('archive', target.get('snapshot'))}?recursive=1')
                if tree.get('truncated'):raise ValueError('Recovery snapshot tree truncated')
                for item in tree['tree']:
                    if item['type']=='blob':files[item['path']]=gh.file(repo,item['path'],target.get('archive',target.get('snapshot')))
                jobs=target['jobs']
            else:files,jobs=prepare(root,target,project=kube('-n','argocd','get','appproject','skymist-'+service,'-o','json')['spec'])
            if not args.recover and (gh.ref(repo,branch)!=sha or gh.ref('SkyMist-Next/'+service,'master' if service=='bgs' else 'main')!=head):
                print('Sources advanced while preparing snapshot; wait for the current candidate')
                return
            state=reserve(state,target,int(time.time()),recovery=bool(args.recover))
            state['releases'][target['id']]['jobs']=jobs
            save() # Durable reservation BEFORE deploy mutation.
            parent=gh.ref(repo,'deploy')
            revision=gh.commit(repo,'deploy',parent,files,'Deploy '+service+' '+target['id'],replace=True)
            state['pending']['revision']=revision
            state['releases'][target['id']]['snapshot']=revision
            save()
        pending=state['pending'];target=state['releases'][pending['release']]
        if not pending['revision']:
            # A killed workflow may have advanced deploy without persisting its revision.
            revision=gh.ref(repo,'deploy')
            actual=json.loads(gh.file(repo,'release.json',revision)) if revision else {}
            if actual.get('id')!=pending['release']:
                state=observe(state,int(time.time()),False,'Interrupted before deploy revision was recorded; select explicit recovery')
                save();return
            pending['revision']=revision;target['snapshot']=revision;save()
        while state['pending']:
            healthy=False;failure=None
            try:
                healthy,failure=evidence(service,pending['revision'],target['image'],target['jobs'])
                for dependency in target['requires']:
                    _,ds=gh.state('SkyMist-Next/'+dependency+'-chart')
                    if not ds or ds['paused'] or ds['pending'] or not ds['lastSuccessful']:
                        healthy=False
                        continue
                    dr=ds['releases'][ds['lastSuccessful']]
                    healthy=healthy and evidence(dependency,dr['snapshot'],dr['image'],dr['jobs'])[0]
            except (subprocess.SubprocessError,KeyError,ValueError) as error:
                print('Evidence unavailable:',type(error).__name__)
            state=observe(state,int(time.time()),healthy,failure)
            if state['paused']:state['paused']['diagnostics']=diagnostics(service)
            save()
            if state['pending']:time.sleep(10)
        if state['paused']:raise RuntimeError('Promotion paused: '+state['paused']['reason'])
        report('Accepted release: '+state['lastSuccessful'])
        # Wake dependants; scheduled reconciliation remains the reliable fallback.
        for other in SERVICES:
            if other!=service:
                try:gh.api(f'repos/SkyMist-Next/{other}-chart/dispatches',{'event_type':'prerequisite-deployed'})
                except urllib.error.HTTPError:print('Wakeup unavailable for',other)
    except Exception:
        if state['pending']:
            state=observe(state,int(time.time()),False,'Promotion controller failed; inspect workflow diagnostics')
            save()
        raise
    finally:lease.release()

if __name__=='__main__':main()
