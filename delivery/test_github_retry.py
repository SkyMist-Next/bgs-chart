import io
import unittest
import urllib.error
from unittest.mock import patch, MagicMock
from github import GitHub

class TransientGitHubTests(unittest.TestCase):
    def test_transient_ref_update_retries_same_request(self):
        response=MagicMock();response.__enter__.return_value.read.return_value=b'{}'
        opener=MagicMock();opener.open.side_effect=[urllib.error.HTTPError('url',500,'transient',{},io.BytesIO()),response]
        with patch('github.urllib.request.build_opener',return_value=opener),patch('github.time.sleep'):
            GitHub('test').api('repos/test/git/refs/heads/deploy',{'sha':'a','force':False},'PATCH')
        self.assertEqual(opener.open.call_count,2)
        self.assertIs(opener.open.call_args_list[0].args[0],opener.open.call_args_list[1].args[0])
    def test_conflict_is_not_retried(self):
        opener=MagicMock();opener.open.side_effect=urllib.error.HTTPError('url',422,'conflict',{},io.BytesIO())
        with patch('github.urllib.request.build_opener',return_value=opener),self.assertRaises(urllib.error.HTTPError):
            GitHub('test').api('repos/test/git/refs/heads/deploy',{'sha':'a','force':False},'PATCH')
        self.assertEqual(opener.open.call_count,1)
