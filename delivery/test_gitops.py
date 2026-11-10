import json
from pathlib import Path
import subprocess
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[1]
SERVICE=json.loads((ROOT/'delivery/manifest.json').read_text())['service']

class GitOpsChartTests(unittest.TestCase):
    def render(self,*extra):
        release={'operator':'operator','bgs':'skymist','admin':'admin'}[SERVICE]
        cmd=['helm','template',release,str(ROOT),'-n','skymist','-f',str(ROOT/'delivery/environments/skymist.yaml'),'--set','gitops.enabled=true',*extra]
        raw=subprocess.check_output(cmd)
        self.assertEqual(raw,subprocess.check_output(cmd))
        return [d for d in yaml.safe_load_all(raw) if d]
    def test_protection_and_order(self):
        docs=self.render();jobs=[d for d in docs if d['kind']=='Job']
        self.assertTrue(jobs)
        for d in jobs:
            a=d['metadata']['annotations']
            self.assertIn(a['argocd.argoproj.io/hook'],('PreSync','Sync'))
            self.assertEqual(a['argocd.argoproj.io/hook-delete-policy'],'BeforeHookCreation')
            self.assertIsInstance(a['argocd.argoproj.io/sync-wave'],str)
        migrations=[j for j in jobs if 'schema' in j['metadata']['name'] or 'migrate' in j['metadata']['name']]
        for d in docs:
            if d['kind']=='Deployment':
                self.assertTrue(all(int(d['metadata']['annotations']['argocd.argoproj.io/sync-wave'])>int(j['metadata']['annotations']['argocd.argoproj.io/sync-wave']) for j in migrations))
            if d['kind'] in ('Secret','StatefulSet','PersistentVolumeClaim','Database','MariaDB','User','Grant','Certificate','Issuer','RabbitmqCluster'):
                self.assertIn('Prune=false',d['metadata']['annotations']['argocd.argoproj.io/sync-options'])
                self.assertIn('Delete=false',d['metadata']['annotations']['argocd.argoproj.io/sync-options'])
    def test_digest_selection_and_retained_credentials(self):
        if SERVICE=='operator':
            docs=self.render()
            self.assertFalse(any(d['kind']=='Secret' for d in docs))
            deployment=next(d for d in docs if d['kind']=='Deployment')
            refs={v['secret']['secretName'] for v in deployment['spec']['template']['spec']['volumes'] if 'secret' in v}
            self.assertIn('skymist-operator-runtime',refs);self.assertIn('skymist-operator-broker',refs)
            cm=next(d for d in docs if d['kind']=='ConfigMap' and d['metadata']['name'].endswith('-crds'))
            self.assertNotIn('upstream-crds.yaml',cm['data'])
            self.assertEqual(len(cm['data']),5)
            for text in cm['data'].values():
                crd=yaml.safe_load(text)
                self.assertEqual(crd['spec']['group'],'skymist.io')
                self.assertIn('Delete=false',crd['metadata']['annotations']['argocd.argoproj.io/sync-options'])
        else:
            digest='sha256:'+'a'*64
            docs=self.render('--set','image.digest='+digest,'--set','image.tag=ignored')
            for d in docs:
                if d['kind']=='Deployment':self.assertTrue(d['spec']['template']['spec']['containers'][0]['image'].endswith('@'+digest))
