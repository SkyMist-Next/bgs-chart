"""Read-only deployment evidence. No exec, Secret reads, or workload mutations."""
import json
import os
import subprocess


def kube(*args, raw=False):
    command=['kubectl']
    if os.environ.get('KUBE_CONTEXT'):command += ['--context',os.environ['KUBE_CONTEXT']]
    output=subprocess.check_output(command+list(args),timeout=25)
    return output if raw else json.loads(output)


def evidence(service, revision, image, jobs):
    app=kube('-n','argocd','get','application','skymist-'+service,'-o','json')
    status=app.get('status',{}); operation=status.get('operationState',{})
    result=operation.get('syncResult',{})
    current=result.get('revision')==revision
    if current and any(r.get('hookPhase') == 'Failed' for r in result.get('resources', [])):
        return False, 'Argo hook failed'
    if current and operation.get('phase') in ('Failed','Error'):
        return False, 'Argo operation '+operation['phase']
    if status.get('sync',{}).get('revision')!=revision or status.get('sync',{}).get('status')!='Synced' or status.get('health',{}).get('status')!='Healthy' or not current or operation.get('phase')!='Succeeded':
        return False,None
    owned=[r for r in status.get('resources',[]) if r['kind']=='Deployment']
    if not owned:raise ValueError('Application contains no Deployment')
    digest=image.split('@')[1]
    for resource in owned:
        deployment=kube('-n','skymist','get','deployment',resource['name'],'-o','json')
        spec=deployment['spec'];ds=deployment.get('status',{});replicas=spec.get('replicas',1)
        if replicas<1 or ds.get('observedGeneration',0)<deployment['metadata']['generation'] or any(ds.get(k,0)!=replicas for k in ('replicas','updatedReplicas','readyReplicas','availableReplicas')):return False,None
        containers=spec['template']['spec']['containers']
        if not any(c['image']==image for c in containers):return False,None
        selector=','.join(k+'='+v for k,v in spec['selector']['matchLabels'].items())
        pods=kube('-n','skymist','get','pods','-l',selector,'-o','json')['items']
        live=[p for p in pods if not p['metadata'].get('deletionTimestamp')]
        if len(live)!=replicas:return False,None
        for pod in live:
            statuses={c['name']:c for c in pod.get('status',{}).get('containerStatuses',[])}
            if not all(statuses.get(c['name'],{}).get('ready') for c in containers):return False,None
            for c in containers:
                if c['image']==image and not statuses[c['name']].get('imageID','').endswith(digest):return False,None
            # API proxy GET needs no execution or credentials from the workload.
            port='https:'+pod['metadata']['name']+':8443' if service=='admin' else pod['metadata']['name']+(':'+str(8080 if service=='operator' else 8081))
            kube('get','--raw',f'/api/v1/namespaces/skymist/pods/{port}/proxy/ready',raw=True)
    for name in jobs:
        job=kube('-n','skymist','get','job',name,'-o','json')
        conditions={c['type']:c['status'] for c in job.get('status',{}).get('conditions',[])}
        if conditions.get('Failed')=='True':return False,'Job failed: '+name
        if conditions.get('Complete')!='True':return False,None
    if service=='operator':
        realms=kube('-n','skymist','get','realms','-o','json')['items']
        for realm in realms:
            if realm['spec'].get('suspend',False):continue
            if realm.get('status',{}).get('phase')!='Ready':return False,None
        # Requires operator delivery endpoint: live SQL publication and current Pod identity.
        directory=kube('get','--raw','/api/v1/namespaces/skymist/services/skymist-operator:8080/proxy/v1/delivery')
        if not directory.get('ready'):return False,None
    return True,None


def diagnostics(service):
    try:
        status=kube('-n','argocd','get','application','skymist-'+service,'-o','json').get('status',{})
        operation=status.get('operationState',{})
        return {'sync':status.get('sync'), 'health':status.get('health'),
                'conditions':status.get('conditions',[]), 'phase':operation.get('phase'),
                'message':operation.get('message'), 'resources':operation.get('syncResult',{}).get('resources',[])}
    except Exception as error:
        return {'unavailable':type(error).__name__}
