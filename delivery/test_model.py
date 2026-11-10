import unittest
from model import *


def app(service='operator', run=1, contract=1, requires=None, provides=None):
    return dict(service=service, deploymentContract=contract, sourceSha='a'*40,
                image=f'registry.neomatik.eu/skymist/{service}@sha256:'+'b'*64,
                runId=run, runAttempt=1, provides=provides or {'directory-schema':1}, requires=requires or {})


class PromotionTests(unittest.TestCase):
    def test_contract_pair_and_chart_only(self):
        s=enqueue(initial(),app()); c={'service':'operator','deploymentContract':2}
        self.assertIsNone(select(s,c,'a'*40))
        s=enqueue(s,app(run=2,contract=2))
        self.assertEqual(select(s,c,'a'*40)['runId'],2)
        r=release(app(),'c'*40);s['lastSuccessful']=r['id'];s['releases'][r['id']]=r
        self.assertEqual(select(s,dict(c,deploymentContract=1),'d'*40)['sourceSha'],'a'*40)

    def test_duplicates_and_stale(self):
        a=app();s=enqueue(enqueue(initial(),a),a)
        self.assertEqual(len(s['candidates']),1)
        self.assertIsNone(select(s,{'service':'operator','deploymentContract':1},'c'*40))

    def test_dependencies_health_removal_and_cycle(self):
        a=app(); b=app('bgs',requires={'operator':{'directory-schema':1}})
        self.assertFalse(compatible(b,{},{} )[0])
        self.assertFalse(compatible(b,{'operator':a},{'operator':False})[0])
        self.assertTrue(compatible(b,{'operator':a},{'operator':True})[0])
        self.assertFalse(compatible(app(provides={'directory-schema':2}),{'bgs':b},{'bgs':True})[0])
        a['requires']={'bgs':{'directory-schema':1}}
        with self.assertRaisesRegex(ValueError,'cycle'):compatible(a,{'bgs':b},{'bgs':True})

    def test_pause_recovery_deadline_and_continuous_health(self):
        s=initial();s['enabled']=True;r=release(app(),'c'*40)
        s=reserve(s,r,0)
        with self.assertRaises(ValueError):reserve(s,r,0)
        s=observe(s,1,True);s=observe(s,119,False);s=observe(s,120,True)
        for now in range(130,240,10): s=observe(s,now,True)
        self.assertIsNotNone(observe(s,239,True)['pending'])
        s=observe(s,240,True);self.assertEqual(s['lastSuccessful'],r['id'])
        self.assertEqual(reserve(s,r,241),s)
        s=reserve(s,r,242,recovery=True);s=observe(s,243,False,'migration failed')
        self.assertIsNotNone(s['paused'])
        s=enqueue(s,app(run=3));self.assertEqual(len(s['candidates']),1)
        with self.assertRaises(ValueError):reserve(s,r,244)
        s=reserve(s,r,244,recovery=True);self.assertIsNotNone(s['paused'])
        s=observe(s,2044,True);self.assertIsNotNone(s['paused'])

    def test_unobserved_gap_resets_continuous_health(self):
        s=initial();s['enabled']=True;s=reserve(s,release(app(),'c'*40),0)
        s=observe(s,1,True);s=observe(s,121,True)
        self.assertIsNotNone(s['pending'])
        self.assertEqual(s['pending']['healthySince'],121)

    def test_forward_only_schema_even_after_failed_migration(self):
        s=initial();s['enabled']=True
        s=reserve(s,release(app(provides={'directory-schema':2}),'c'*40),0)
        s=observe(s,1,False,'partial DDL')
        with self.assertRaisesRegex(ValueError,'schema'):
            reserve(s,release(app(),'c'*40),2,recovery=True)

if __name__ == '__main__': unittest.main()
