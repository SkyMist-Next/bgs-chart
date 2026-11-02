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
        assert pod['automountServiceAccountToken'] is False
        assert pod['initContainers'][0]['args'][-1] == 'wait'
    print(f'{profile}: deterministic render, five deployments, database users, schema gate and Redis discovery passed')
