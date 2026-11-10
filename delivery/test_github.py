import json
import unittest
from urllib.request import Request
from github import GitHub, SafeRedirect

class FakeGitHub(GitHub):
    def __init__(self):self.head='base';self.parents={};self.count=0
    def api(self,path,data=None,method=None,raw=False):
        if path.endswith('/git/blobs'):return {'sha':'blob'}
        if '/git/commits/' in path:return {'tree':{'sha':'tree'}}
        if path.endswith('/git/trees'):return {'sha':'tree'}
        if path.endswith('/git/commits'):
            self.count+=1;sha=str(self.count);self.parents[sha]=data['parents'];return {'sha':sha}
        if '/git/refs/heads/' in path:
            assert data['force'] is False
            if self.parents[data['sha']] != [self.head]:raise ValueError('Non-fast-forward update')
            self.head=data['sha'];return {}
        raise AssertionError(path)

class GitStateTests(unittest.TestCase):
    def test_competing_state_writers_cannot_overwrite(self):
        g=FakeGitHub();g.save('org/repo','base',{'pending':'one'})
        with self.assertRaisesRegex(ValueError,'Non-fast-forward'):g.save('org/repo','base',{'pending':'two'})
        self.assertEqual(g.head,'1')
    def test_artifact_redirect_does_not_leak_github_token(self):
        request=Request('https://api.github.com/artifact',headers={'Authorization':'Bearer private'})
        result=SafeRedirect().redirect_request(request,None,302,'',{},'https://storage.example/artifact')
        self.assertIsNone(result.get_header('Authorization'))
