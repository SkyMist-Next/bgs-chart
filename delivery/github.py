"""GitHub API operations with optimistic Git ref updates; never force-push."""
import base64
import io
import json
import os
import time
import urllib.error
import urllib.request
import zipfile
from model import candidate


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        result=super().redirect_request(req,fp,code,msg,headers,newurl)
        from urllib.parse import urlsplit
        if result is not None and urlsplit(req.full_url).netloc!=urlsplit(newurl).netloc:
            result.remove_header('Authorization')
        return result


class GitHub:
    def __init__(self, token=None):
        self.token = token or os.environ['GH_TOKEN']

    def api(self, path, data=None, method=None, raw=False):
        req = urllib.request.Request('https://api.github.com/' + path, data=None if data is None else json.dumps(data).encode(), method=method,
            headers={'Authorization':'Bearer '+self.token, 'Accept':'application/vnd.github+json', 'X-GitHub-Api-Version':'2022-11-28', 'Content-Type':'application/json'})
        # GET and a repeated non-force ref PATCH are idempotent, including when
        # the first update succeeded but its response was lost. Never retry a
        # conflict or an authorization failure, and never force the ref.
        for attempt in range(3):
            try:
                with urllib.request.build_opener(SafeRedirect).open(req, timeout=30) as response:
                    value=response.read()
                    return value if raw else json.loads(value) if value else None
            except urllib.error.HTTPError as error:
                if req.get_method() not in ('GET','PATCH') or error.code not in (500,502,503,504) or attempt == 2:
                    raise
                time.sleep(2 ** attempt)

    def ref(self, repo, branch):
        try: return self.api(f'repos/{repo}/git/ref/heads/{branch}')['object']['sha']
        except urllib.error.HTTPError as e:
            if e.code==404:return None
            raise

    def file(self, repo, path, ref):
        value=self.api(f'repos/{repo}/contents/{path}?ref={ref}')
        if value.get('encoding') != 'base64':
            value=self.api(f'repos/{repo}/git/blobs/{value["sha"]}')
        return base64.b64decode(value['content'])

    def state(self, repo, branch='delivery-state'):
        sha=self.ref(repo,branch)
        return sha, json.loads(self.file(repo,'state.json',sha)) if sha else None

    def commit(self, repo, branch, parent, files, message, replace=False):
        tree=[]
        for name, content in sorted(files.items()):
            blob=self.api(f'repos/{repo}/git/blobs',{'content':base64.b64encode(content).decode(),'encoding':'base64'})
            tree.append({'path':name,'mode':'100644','type':'blob','sha':blob['sha']})
        args={'tree':tree}
        if parent and not replace:args['base_tree']=self.api(f'repos/{repo}/git/commits/{parent}')['tree']['sha']
        tree_sha=self.api(f'repos/{repo}/git/trees',args)['sha']
        sha=self.api(f'repos/{repo}/git/commits',{'message':message,'tree':tree_sha,'parents':[parent] if parent else []})['sha']
        # A competing commit is not an ancestor of this commit: GitHub rejects the update.
        if parent:self.api(f'repos/{repo}/git/refs/heads/{branch}',{'sha':sha,'force':False},'PATCH')
        else:self.api(f'repos/{repo}/git/refs',{'ref':'refs/heads/'+branch,'sha':sha})
        return sha

    def save(self, repo, parent, state, branch='delivery-state'):
        return self.commit(repo,branch,parent,{'state.json':(json.dumps(state,indent=2,sort_keys=True)+'\n').encode()},'Record delivery state',replace=True)

    def trusted_candidate(self, service):
        repo='SkyMist-Next/'+service
        branch='master' if service=='bgs' else 'main'
        head=self.ref(repo,branch)
        # Query by HEAD so a newer failed or still-running source cannot be bypassed.
        runs=self.api(f'repos/{repo}/actions/workflows/delivery.yml/runs?event=push&branch={branch}&head_sha={head}&status=success&per_page=100')['workflow_runs']
        for run in sorted(runs,key=lambda r:(r['run_number'],r['run_attempt']),reverse=True):
            if run['head_repository']['full_name']!=repo or run['path']!='.github/workflows/delivery.yml' or run['conclusion']!='success' or run['head_sha']!=head:continue
            artifacts=self.api(f'repos/{repo}/actions/runs/{run["id"]}/artifacts')['artifacts']
            matches=[a for a in artifacts if a['name']=='delivery-candidate' and not a['expired']]
            if len(matches)!=1:continue
            raw=self.api(f'repos/{repo}/actions/artifacts/{matches[0]["id"]}/zip',raw=True)
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                info=archive.getinfo('candidate.json')
                if info.file_size>65536:raise ValueError('Candidate exceeds limit')
                value=json.loads(archive.read(info))
            candidate(value)
            source=json.loads(self.file(repo,'delivery/manifest.json',head))
            if any(value[k]!=v for k,v in source.items()) or value['sourceSha']!=head or value['service']!=service or value['runId']!=run['id'] or value['runAttempt']!=run['run_attempt']:
                raise ValueError('Candidate does not match trusted source workflow')
            return head,value
        return head,None


class Lease:
    """Cross-repository promotion lock prevents consumer/provider check races.

    The lease outlives the workflow deadline. Expiry is recovered only after all
    pending deployments have been observed/paused, never by blind lock stealing.
    """
    def __init__(self, gh, owner):self.gh,self.owner,self.sha=gh,owner,None
    def acquire(self):
        repo='SkyMist-Next/operator-chart'; sha,state=self.gh.state(repo,'delivery-lock');now=int(time.time())
        if state and state.get('owner') and state['owner']!=self.owner:
            if state['expires']>now:return False
            for service in ('operator','bgs','admin'):
                _,s=self.gh.state('SkyMist-Next/'+service+'-chart')
                if s and s.get('pending'):return False
        self.sha=self.gh.save(repo,sha,{'owner':self.owner,'expires':now+2400},'delivery-lock')
        return True
    def release(self):
        if self.sha:self.gh.save('SkyMist-Next/operator-chart',self.sha,{'owner':None,'expires':0},'delivery-lock')
    def release_if_owner(self):
        """Release after cancellation; the write is a fast-forward of the read state."""
        sha,state=self.gh.state('SkyMist-Next/operator-chart','delivery-lock')
        if not state or state.get('owner')!=self.owner:return False
        self.gh.save('SkyMist-Next/operator-chart',sha,{'owner':None,'expires':0},'delivery-lock')
        return True
