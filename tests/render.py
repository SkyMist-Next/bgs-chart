#!/usr/bin/env python3
"""Offline chart contract checks; run with Python + PyYAML and Helm."""
import pathlib
import subprocess
import yaml
ROOT = pathlib.Path(__file__).resolve().parents[1]
for profile, replicas in [('local', 1), ('production', 2)]:
    cmd = ['helm', 'template', 'contract', str(ROOT), '-n', 'contract', '-f', str(ROOT / f'values-{profile}.yaml'), '--set', 'image.repository=bgs,image.tag=test,gateway.hostname=bgs.example,gateway.frontendSecret=tls,gateway.restSecret=tls']
    rendered = subprocess.check_output(cmd)
    assert rendered == subprocess.check_output(cmd), 'Nondeterministic rendering'
    docs = [d for d in yaml.safe_load_all(rendered) if d]
    deployments = [d for d in docs if d['kind'] == 'Deployment']
    assert len(deployments) == 5
    assert all(d['spec']['replicas'] == replicas for d in deployments)
    users = [d for d in docs if d['kind'] == 'User']
    runtime = [d for d in users if d['metadata']['labels']['skymist.io/database-role'] == 'bgs-runtime']
    assert len(runtime) == 1 and runtime[0]['spec']['name'] and runtime[0]['spec']['host'] == '%'
    config = next(d for d in docs if d['kind'] == 'ConfigMap' and d['metadata'].get('labels', {}).get('skymist.io/connection-type') == 'bgs-redis')
    assert 'PASSWORD' not in config['data']
    assert config['data']['REDIS_PASSWORD_SECRET_NAME'] == 'contract-redis-auth'
    assert len([d for d in docs if d['kind'] == 'MariaDB']) == (profile == 'local')
    for d in deployments:
        pod = d['spec']['template']['spec']
        frontend = d['metadata']['name'].endswith('-frontend')
        cert_volumes = [v for v in pod['volumes'] if v['name'] == 'certs']
        assert len(cert_volumes) == int(frontend)
        if frontend:
            secret = cert_volumes[0]['secret']
            assert secret['secretName'] == 'tls'
            assert secret['defaultMode'] == 0o440
            assert {i['key'] for i in secret['items']} == {'tls.crt', 'tls.key'}
            assert pod['securityContext']['fsGroup'] == 1000
            mount = next(m for m in pod['containers'][0]['volumeMounts'] if m['name'] == 'certs')
            assert mount['readOnly'] and 'subPath' not in mount
        env = {e['name']: e.get('value') for e in pod['containers'][0]['env']}
        assert env['BGS_TLS_SERVER_NAME'] == 'bgs.example'
        assert env['BGS_TLS'] == ('true' if frontend else 'false')
        assert pod['automountServiceAccountToken'] is False
        assert pod['initContainers'][0]['args'][-1] == 'wait'
        assert next(e['value'] for e in pod['containers'][0]['env'] if e['name'] == 'WEB_AUTH_URL') == 'https://bgs.example/bnetserver/login/'
    print(f'{profile}: deterministic render, five deployments, database users, schema gate and Redis discovery passed')

override = 'https://bgs.local:8443/bnetserver/login/'
docs = list(yaml.safe_load_all(subprocess.check_output(cmd + ['--set', f'webAuthUrl={override}'])))
for d in docs:
    if d and d['kind'] == 'Deployment':
        assert next(e['value'] for e in d['spec']['template']['spec']['containers'][0]['env'] if e['name'] == 'WEB_AUTH_URL') == override
print('Explicit web-auth URL, including forwarded port, reaches every BGS deployment')
