"""Create a self-contained deterministic Helm snapshot and audit protected output."""
import json
from pathlib import Path
import subprocess
import yaml

PROTECTED={'StatefulSet','PersistentVolumeClaim','Secret','MariaDB','Database','User','Grant','RabbitmqCluster','Certificate','Issuer','ClusterIssuer','CustomResourceDefinition'}
RELEASE={'operator':'operator','bgs':'skymist','admin':'admin'}


def validate_project(docs, policy):
    allowed={(r['group'],r['kind']) for r in policy.get('namespaceResourceWhitelist',[])+policy.get('clusterResourceWhitelist',[])}
    for resource in docs:
        version=resource['apiVersion'];group=version.split('/')[0] if '/' in version else ''
        if (group,resource['kind']) not in allowed:
            raise ValueError('Resource kind is not permitted in AppProject: '+group+'/'+resource['kind'])


def prepare(root, release, project=None):
    root=Path(root); service=release['service']
    values=yaml.safe_load((root/'delivery/environments/skymist.yaml').read_text())
    values['gitops']={'enabled':True}
    if service=='operator':values['image']=release['image']
    else:
        repo,digest=release['image'].split('@');values['image']={**values.get('image',{}),'repository':repo,'digest':digest,'tag':''}
    if service=='bgs':
        redis=values.setdefault('redis-ha',{})
        redis.setdefault('redis',{}).setdefault('annotations',{}).update({'argocd.argoproj.io/sync-options':'Prune=false,Delete=false','argocd.argoproj.io/sync-wave':'-5'})
    value_file=root/'delivery-values.generated.yaml'; value_file.write_text(yaml.safe_dump(values,sort_keys=True))
    command=['helm','template',RELEASE[service],str(root),'-n','skymist','--skip-tests','--kube-version','1.36.4','-f',str(value_file)]
    raw=subprocess.check_output(command)
    if raw!=subprocess.check_output(command):raise ValueError('Nondeterministic chart rendering')
    docs=[d for d in yaml.safe_load_all(raw) if d]
    if not docs:raise ValueError('Empty chart output')
    validate_project(docs,json.loads((root/'delivery/project.json').read_text()))
    if project is not None:validate_project(docs,project)
    jobs=[]
    for d in docs:
        metadata=d['metadata'];ann=metadata.get('annotations') or {}
        if d['kind'] in PROTECTED and not all(v in ann.get('argocd.argoproj.io/sync-options','').split(',') for v in ('Prune=false','Delete=false')):raise ValueError('Unprotected resource: '+metadata['name'])
        if d['kind']=='Job':
            if ann.get('argocd.argoproj.io/hook') not in ('Sync','PreSync'):raise ValueError('Job is not repeatable')
            jobs.append(metadata['name'])
    # Validate Kubernetes built-ins; CRs are checked against checked-in schemas by chart tests.
    subprocess.run(['kubeconform','-strict','-summary','-kubernetes-version','1.36.0','-ignore-missing-schemas'],input=raw,check=True)
    files={}
    for name in ('Chart.yaml','Chart.lock','values.yaml','values.schema.json'):
        if (root/name).exists():files['chart/'+name]=(root/name).read_bytes()
    for folder in ('templates','files','crds','charts'):
        for p in sorted((root/folder).rglob('*')):
            if p.is_file():files['chart/'+str(p.relative_to(root))]=p.read_bytes()
    files['environments/skymist/values.yaml']=value_file.read_bytes()
    files['release.json']=(json.dumps({k:v for k,v in release.items() if k not in ('jobs','snapshot','archive')},sort_keys=True,indent=2)+'\n').encode()
    value_file.unlink()
    return files,jobs
