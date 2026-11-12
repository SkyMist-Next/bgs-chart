import unittest
from unittest.mock import patch
from verify import evidence

class VerificationTests(unittest.TestCase):
    def test_failed_hook_pauses_before_argo_retries_finish(self):
        app={'status':{'operationState':{'phase':'Running','syncResult':{'revision':'r','resources':[{'hookPhase':'Failed'}]}}}}
        with patch('verify.kube',return_value=app):
            self.assertEqual(evidence('bgs','r','repo@sha256:abc',[]),(False,'Argo hook failed','Argo hook failed'))
    def test_old_failure_does_not_fail_new_revision(self):
        app={'status':{'operationState':{'phase':'Failed','syncResult':{'revision':'old'}}}}
        with patch('verify.kube',return_value=app):
            self.assertEqual(evidence('bgs','new','repo@sha256:abc',[])[:2],(False,None))
    def test_empty_application_cannot_pass(self):
        app={'status':{'sync':{'revision':'r','status':'Synced'},'health':{'status':'Healthy'},'operationState':{'phase':'Succeeded','syncResult':{'revision':'r'}},'resources':[]}}
        with patch('verify.kube',return_value=app),self.assertRaisesRegex(ValueError,'no Deployment'):
            evidence('bgs','r','repo@sha256:abc',[])

class ProjectTests(unittest.TestCase):
    def test_missing_kind_fails_before_deployment(self):
        from snapshot import validate_project
        docs=[{'apiVersion':'policy/v1','kind':'PodDisruptionBudget'}]
        with self.assertRaisesRegex(ValueError,'not permitted'):
            validate_project(docs,{'namespaceResourceWhitelist':[]})
        validate_project(docs,{'namespaceResourceWhitelist':[{'group':'policy','kind':'PodDisruptionBudget'}]})

class HealthResponseTests(unittest.TestCase):
    def test_successful_empty_health_body_is_supported(self):
        from verify import kube
        with patch('verify.subprocess.check_output',return_value=b''):
            self.assertEqual(kube('get','--raw','/ready',raw=True),b'')


def application(revision='r', hooks=()):
    return {'status':{'sync':{'revision':revision,'status':'Synced'},'health':{'status':'Healthy'},
        'operationState':{'phase':'Succeeded','syncResult':{'revision':revision,'resources':[
            {'kind':'Deployment','name':'skymist-bgs-social'},*({'kind':'Job','name':n,'hookType':'Sync'} for n in hooks)]}},
        'resources':[{'kind':'Deployment','name':'skymist-bgs-social'}]}}


IMAGE='repo/bgs@sha256:abc'


def cluster(app, jobs, ready=2):
    deployment={'metadata':{'generation':1},'spec':{'replicas':2,'selector':{'matchLabels':{'app':'social'}},
        'template':{'spec':{'containers':[{'name':'bgs','image':IMAGE}]}}},
        'status':{'observedGeneration':1,'replicas':2,'updatedReplicas':2,'readyReplicas':ready,'availableReplicas':ready}}
    pods={'items':[{'metadata':{'name':'p'+str(i)},'status':{'containerStatuses':[{'name':'bgs','ready':True,'imageID':'x@sha256:abc'}]}} for i in range(2)]}
    def kube(*args, raw=False):
        if args[:4]==('-n','argocd','get','application'):return app
        if 'deployment' in args:return deployment
        if 'pods' in args:return pods
        if args[0]=='get' and args[1]=='--raw':return b''
        if 'job' in args:
            name=args[args.index('job')+1]
            if name not in jobs:
                import subprocess
                raise subprocess.CalledProcessError(1,'kubectl')
            return jobs[name]
        raise AssertionError(args)
    return kube


def job(created='2026-11-12T13:48:00Z', complete=True, failed=False, hook=True):
    conditions=[{'type':'Complete','status':'True'}] if complete else []
    if failed:conditions=[{'type':'Failed','status':'True'}]
    return {'metadata':{'creationTimestamp':created,'annotations':{'argocd.argoproj.io/hook':'Sync'} if hook else {}},
            'spec':{'template':{'spec':{'containers':[{'image':IMAGE}]}}},'status':{'conditions':conditions}}


STARTED=1794491212 # 2026-11-12T13:46:52Z


class PartialSyncTests(unittest.TestCase):
    def check(self, app, jobs, ready=2):
        with patch('verify.kube',side_effect=cluster(app,jobs,ready)):
            return evidence('bgs','r',IMAGE,['skymist-bgs-migrate'],since=STARTED)
    def test_operation_hooks_are_verified(self):
        self.assertEqual(self.check(application(hooks=['skymist-bgs-migrate']),{'skymist-bgs-migrate':job()}),(True,None,'healthy'))
    def test_self_heal_partial_sync_falls_back_to_live_hook_jobs(self):
        self.assertEqual(self.check(application(),{'skymist-bgs-migrate':job()}),(True,None,'healthy'))
    def test_hook_job_from_previous_attempt_is_rejected(self):
        self.assertEqual(self.check(application(),{'skymist-bgs-migrate':job(created='2026-11-12T12:00:00Z')}),
            (False,None,'hook job skymist-bgs-migrate predates this attempt'))
    def test_missing_hook_job_is_rejected(self):
        self.assertEqual(self.check(application(),{}),(False,None,'hook job skymist-bgs-migrate missing'))
    def test_non_hook_job_is_rejected(self):
        self.assertFalse(self.check(application(),{'skymist-bgs-migrate':job(hook=False)})[0])
    def test_failed_hook_job_pauses(self):
        self.assertEqual(self.check(application(),{'skymist-bgs-migrate':job(failed=True)})[1],'Job failed: skymist-bgs-migrate')
    def test_incomplete_hook_job_waits(self):
        self.assertEqual(self.check(application(),{'skymist-bgs-migrate':job(complete=False)}),
            (False,None,'hook job skymist-bgs-migrate incomplete'))
    def test_unready_deployment_explains_wait(self):
        self.assertEqual(self.check(application(),{'skymist-bgs-migrate':job()},ready=0),
            (False,None,'deployment skymist-bgs-social 0/2 ready, 2 updated'))
    def test_degraded_application_explains_wait(self):
        app=application();app['status']['health']['status']='Degraded'
        self.assertEqual(self.check(app,{}),(False,None,'Argo health Degraded'))
