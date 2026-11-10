"""Use the verifier Pod's rotating projected token; no stored cluster credential."""
import json,os
from pathlib import Path
sa='/var/run/secrets/kubernetes.io/serviceaccount/'
config={'apiVersion':'v1','kind':'Config','clusters':[{'name':'cluster','cluster':{'server':'https://kubernetes.default.svc','certificate-authority':sa+'ca.crt'}}],'users':[{'name':'verifier','user':{'tokenFile':sa+'token'}}],'contexts':[{'name':'delivery','context':{'cluster':'cluster','user':'verifier','namespace':'skymist'}}],'current-context':'delivery'}
os.umask(0o077)
Path('/tmp/delivery-kubeconfig').write_text(json.dumps(config))
with open(os.environ['GITHUB_ENV'],'a') as out:out.write('KUBECONFIG=/tmp/delivery-kubeconfig\n')
