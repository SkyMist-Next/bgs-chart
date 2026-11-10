import unittest
import yaml
from snapshot import stamp_attempt

class SyncAttemptTests(unittest.TestCase):
    def test_retry_changes_only_stateless_attempt_marker(self):
        files={'release.json':b'recorded identity','chart/values.yaml':b'accepted image'}
        first=stamp_attempt(files,'operator','r','first')
        second=stamp_attempt(first,'operator','r','second')
        marker='chart/templates/delivery-attempt.yaml'
        self.assertEqual({k:v for k,v in first.items() if k!=marker},files)
        self.assertEqual({k:v for k,v in second.items() if k!=marker},files)
        self.assertNotEqual(first[marker],second[marker])
        self.assertEqual(stamp_attempt(files,'operator','r','first'),first)
        doc=yaml.safe_load(second[marker])
        self.assertEqual(doc['kind'],'ConfigMap')
        self.assertEqual(doc['data'],{'release':'r','attempt':'second'})
