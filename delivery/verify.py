"""Read-only deployment evidence. No exec, Secret reads, or workload mutations."""
import datetime
import json
import os
import subprocess


def kube(*args, raw=False):
    command=['kubectl']
    if os.environ.get('KUBE_CONTEXT'):command += ['--context',os.environ['KUBE_CONTEXT']]
    output=subprocess.check_output(command+list(args),timeout=25)
    return output if raw else json.loads(output)


def timestamp(value):
    return int(datetime.datetime.strptime(value,'%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc).timestamp())


def evidence(service, revision, image, jobs, since=None):
    """Return (healthy, failure, detail). A failure pauses; detail explains waiting.

    since is the delivery attempt start. With it, hook Jobs must have been
    created by this attempt (BeforeHookCreation recreates them per sync).
    """
    app=kube('-n','argocd','get','application','skymist-'+service,'-o','json')
    status=app.get('status',{}); operation=status.get('operationState',{})
    result=operation.get('syncResult',{})
    current=result.get('revision')==revision
    if current and any(r.get('hookPhase') == 'Failed' for r in result.get('resources', [])):
        return False, 'Argo hook failed', 'Argo hook failed'
    if current and operation.get('phase') in ('Failed','Error'):
        return False, 'Argo operation '+operation['phase'], 'Argo operation '+operation['phase']
    sync=status.get('sync',{}); health=status.get('health',{}).get('status')
    if sync.get('revision')!=revision:return False,None,'Argo revision '+str(sync.get('revision'))[:12]+' is not '+revision[:12]
    if sync.get('status')!='Synced':return False,None,'Argo sync '+str(sync.get('status'))
    if health!='Healthy':return False,None,'Argo health '+str(health)
    if not current or operation.get('phase')!='Succeeded':return False,None,'Argo operation '+str(operation.get('phase'))+' for '+str(result.get('revision'))[:12]
    owned=[r for r in status.get('resources',[]) if r['kind']=='Deployment']
    if not owned:raise ValueError('Application contains no Deployment')
    digest=image.split('@')[1]
    for resource in owned:
        name=resource['name']
        deployment=kube('-n','skymist','get','deployment',name,'-o','json')
        spec=deployment['spec'];ds=deployment.get('status',{});replicas=spec.get('replicas',1)
        if replicas<1:return False,None,'deployment '+name+' has no replicas'
        if ds.get('observedGeneration',0)<deployment['metadata']['generation'] or any(ds.get(k,0)!=replicas for k in ('replicas','updatedReplicas','readyReplicas','availableReplicas')):
            return False,None,f"deployment {name} {ds.get('readyReplicas',0)}/{replicas} ready, {ds.get('updatedReplicas',0)} updated"
        containers=spec['template']['spec']['containers']
        if not any(c['image']==image for c in containers):return False,None,'deployment '+name+' does not run the release image'
        selector=','.join(k+'='+v for k,v in spec['selector']['matchLabels'].items())
        pods=kube('-n','skymist','get','pods','-l',selector,'-o','json')['items']
        live=[p for p in pods if not p['metadata'].get('deletionTimestamp')]
        if len(live)!=replicas:return False,None,f'deployment {name} has {len(live)}/{replicas} live pods'
        for pod in live:
            pod_name=pod['metadata']['name']
            statuses={c['name']:c for c in pod.get('status',{}).get('containerStatuses',[])}
            if not all(statuses.get(c['name'],{}).get('ready') for c in containers):return False,None,'pod '+pod_name+' not ready'
            for c in containers:
                if c['image']==image and not statuses[c['name']].get('imageID','').endswith(digest):return False,None,'pod '+pod_name+' runs another image digest'
            # API proxy GET needs no execution or credentials from the workload.
            port='https:'+pod_name+':8443' if service=='admin' else pod_name+(':'+str(8080 if service=='operator' else 8081))
            kube('get','--raw',f'/api/v1/namespaces/skymist/pods/{port}/proxy/ready',raw=True)
    # Argo's exact-revision operation is authoritative for hook names. Helm
    # versions can coalesce subchart defaults differently in legacy hashed names.
    # An automated partial sync (self-heal) of the same revision replaces the
    # operation without hooks; then the recorded hook Jobs are verified live.
    actual_jobs=[r['name'] for r in result.get('resources',[]) if r['kind']=='Job' and r.get('hookType') in ('Sync','PreSync')]
    partial=not actual_jobs
    if partial:actual_jobs=list(jobs)
    if len(actual_jobs)!=len(jobs) or not actual_jobs:return False,None,f'{len(actual_jobs)} hook jobs, expected {len(jobs)}'
    for name in actual_jobs:
        try:job=kube('-n','skymist','get','job',name,'-o','json')
        except subprocess.CalledProcessError:
            if partial:return False,None,'hook job '+name+' missing'
            raise
        if partial:
            metadata=job['metadata']
            if not metadata.get('annotations',{}).get('argocd.argoproj.io/hook'):return False,None,'job '+name+' is not an Argo hook'
            if since is not None and timestamp(metadata['creationTimestamp'])<since:return False,None,'hook job '+name+' predates this attempt'
        if not name.endswith('-crds') and not any(c['image']==image for c in job['spec']['template']['spec']['containers']):return False,None,'hook job '+name+' does not run the release image'
        conditions={c['type']:c['status'] for c in job.get('status',{}).get('conditions',[])}
        if conditions.get('Failed')=='True':return False,'Job failed: '+name,'Job failed: '+name
        if conditions.get('Complete')!='True':return False,None,'hook job '+name+' incomplete'
    if service=='operator':
        realms=kube('-n','skymist','get','realms','-o','json')['items']
        for realm in realms:
            if realm['spec'].get('suspend',False):continue
            if realm.get('status',{}).get('phase')!='Ready':return False,None,'realm '+realm['metadata']['name']+' not Ready'
        # Requires operator delivery endpoint: live SQL publication and current Pod identity.
        directory=kube('get','--raw','/api/v1/namespaces/skymist/services/skymist-operator:8080/proxy/v1/delivery')
        if not directory.get('ready'):return False,None,'operator delivery endpoint not ready'
    return True,None,'healthy'


def diagnostics(service):
    try:
        status=kube('-n','argocd','get','application','skymist-'+service,'-o','json').get('status',{})
        operation=status.get('operationState',{})
        return {'sync':status.get('sync'), 'health':status.get('health'),
                'conditions':status.get('conditions',[]), 'phase':operation.get('phase'),
                'message':operation.get('message'), 'resources':operation.get('syncResult',{}).get('resources',[])}
    except Exception as error:
        return {'unavailable':type(error).__name__}
