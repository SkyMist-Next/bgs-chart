import unittest
from unittest.mock import patch
from verify import evidence

class VerificationTests(unittest.TestCase):
    def test_failed_hook_pauses_before_argo_retries_finish(self):
        app={'status':{'operationState':{'phase':'Running','syncResult':{'revision':'r','resources':[{'hookPhase':'Failed'}]}}}}
        with patch('verify.kube',return_value=app):
            self.assertEqual(evidence('bgs','r','repo@sha256:abc',[]),(False,'Argo hook failed'))
    def test_old_failure_does_not_fail_new_revision(self):
        app={'status':{'operationState':{'phase':'Failed','syncResult':{'revision':'old'}}}}
        with patch('verify.kube',return_value=app):
            self.assertEqual(evidence('bgs','new','repo@sha256:abc',[]),(False,None))
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
