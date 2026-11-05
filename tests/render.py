#!/usr/bin/env python3
"""Offline chart contract checks; run with Python + PyYAML and Helm."""
import pathlib
import subprocess
import yaml
ROOT = pathlib.Path(__file__).resolve().parents[1]
for profile, replicas in [('local', 1), ('production', 2)]:
    cmd = ['helm', 'template', 'contract', str(ROOT), '-n', 'contract', '-f', str(ROOT / f'values-{profile}.yaml'), '--set', 'image.repository=bgs,image.tag=test,gateway.hostname=bgs.example']
    expected_secret = 'bgs-local-tls' if profile == 'local' else 'contract-bgs-tls'
    rendered = subprocess.check_output(cmd)
    assert rendered == subprocess.check_output(cmd), 'Nondeterministic rendering'
    docs = [d for d in yaml.safe_load_all(rendered) if d]
    certificates = [d for d in docs if d['kind'] == 'Certificate']
    assert len(certificates) == int(profile == 'production')
    if certificates:
        spec = certificates[0]['spec']
        assert spec['secretName'] == expected_secret
        assert spec['commonName'] == 'bgs.example'
        assert spec['dnsNames'] == ['bgs.example']
        assert spec['issuerRef'] == {'name': 'bgs-ca', 'kind': 'Issuer', 'group': 'cert-manager.io'}
        assert spec['privateKey']['rotationPolicy'] == 'Always' and not spec['isCA']
        assert 'server auth' in spec['usages']
    gateway = next(d for d in docs if d['kind'] == 'Gateway')
    assert gateway['spec']['listeners'][1]['tls'] == {'mode': 'Passthrough'}
    assert gateway['spec']['listeners'][1]['protocol'] == 'TLS'
    assert not any(d['kind'] == 'HTTPRoute' for d in docs)
    assert next(d for d in docs if d['kind'] == 'TLSRoute')['spec']['rules'][0]['backendRefs'][0]['port'] == 8080
    deployments = [d for d in docs if d['kind'] == 'Deployment']
    assert len(deployments) == 6
    realm_worker = next(d for d in deployments if d['metadata']['name'].endswith('-realm'))
    assert realm_worker['spec']['template']['spec']['containers'][0]['args'] == ['node', 'realm.js']
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
        frontend = d['metadata']['name'].endswith(('-frontend', '-rest'))
        cert_volumes = [v for v in pod['volumes'] if v['name'] == 'certs']
        assert len(cert_volumes) == int(frontend)
        if frontend:
            secret = cert_volumes[0]['secret']
            assert secret['secretName'] == expected_secret
            assert secret['defaultMode'] == 0o440
            assert {i['key'] for i in secret['items']} == {'tls.crt', 'tls.key'}
            assert pod['securityContext']['fsGroup'] == 1000
            mount = next(m for m in pod['containers'][0]['volumeMounts'] if m['name'] == 'certs')
            assert mount['readOnly'] and 'subPath' not in mount
        env = {e['name']: e.get('value') for e in pod['containers'][0]['env']}
        assert env['BGS_IP_BANS_ENABLED'] == 'true'
        assert env['BGS_PROXY_PROTOCOL'] == 'off'
        assert env['BGS_TLS_SERVER_NAME'] == 'bgs.example'
        assert env['BGS_TLS'] == ('true' if frontend else 'false')
        assert pod['automountServiceAccountToken'] is False
        assert pod['initContainers'][0]['args'][-1] == 'wait'
        assert next(e['value'] for e in pod['containers'][0]['env'] if e['name'] == 'WEB_AUTH_URL') == 'https://bgs.example/bnetserver/login/'
    print(f'{profile}: deterministic render, six deployments, database users, schema gate and Redis discovery passed')

override = 'https://bgs.local:8443/bnetserver/login/'
docs = list(yaml.safe_load_all(subprocess.check_output(cmd + ['--set', f'webAuthUrl={override}'])))
for d in docs:
    if d and d['kind'] == 'Deployment':
        assert next(e['value'] for e in d['spec']['template']['spec']['containers'][0]['env'] if e['name'] == 'WEB_AUTH_URL') == override
print('Explicit web-auth URL, including forwarded port, reaches every BGS deployment')

# Managed Secret overrides must reach both TLS consumers.
custom = cmd + ['--set', 'certificate.secretName=custom-tls,certificate.issuerRef.name=custom-ca']
docs = [d for d in yaml.safe_load_all(subprocess.check_output(custom)) if d]
assert next(d for d in docs if d['kind'] == 'Certificate')['spec']['issuerRef']['name'] == 'custom-ca'
assert next(d for d in docs if d['kind'] == 'Certificate')['spec']['secretName'] == 'custom-tls'
assert next(v for v in next(d for d in docs if d['kind'] == 'Deployment' and d['metadata']['name'].endswith('-rest'))['spec']['template']['spec']['volumes'] if v['name'] == 'certs')['secret']['secretName'] == 'custom-tls'
frontend = next(d for d in docs if d['kind'] == 'Deployment' and d['metadata']['name'].endswith('-frontend'))
assert next(v for v in frontend['spec']['template']['spec']['volumes'] if v['name'] == 'certs')['secret']['secretName'] == 'custom-tls'
for endpoint in ['frontendSecret', 'restSecret']:
    result = subprocess.run(cmd + ['--set', f'gateway.{endpoint}=conflicting'], capture_output=True)
    assert result.returncode != 0 and b'overrides must match' in result.stderr
external = cmd + ['--set', 'certificate.enabled=false,gateway.frontendSecret=external-front,gateway.restSecret=external-rest']
docs = [d for d in yaml.safe_load_all(subprocess.check_output(external)) if d]
assert not any(d['kind'] == 'Certificate' for d in docs)
assert next(v for v in next(d for d in docs if d['kind'] == 'Deployment' and d['metadata']['name'].endswith('-rest'))['spec']['template']['spec']['volumes'] if v['name'] == 'certs')['secret']['secretName'] == 'external-rest'
frontend = next(d for d in docs if d['kind'] == 'Deployment' and d['metadata']['name'].endswith('-frontend'))
assert next(v for v in frontend['spec']['template']['spec']['volumes'] if v['name'] == 'certs')['secret']['secretName'] == 'external-front'
print('Managed certificate overrides, conflicting Secret rejection, and external Secret compatibility passed')


for enabled in ['true', 'false']:
    docs = [d for d in yaml.safe_load_all(subprocess.check_output(cmd + ['--set', f'security.ipBansEnabled={enabled}'])) if d]
    assert not any(d['kind'] == 'BackendTrafficPolicy' for d in docs)
    for d in docs:
        if d['kind'] == 'Deployment':
            env = {e['name']: e.get('value') for e in d['spec']['template']['spec']['containers'][0]['env']}
            assert env['BGS_IP_BANS_ENABLED'] == enabled
v2 = cmd + ['--set', 'gateway.proxyProtocol=v2', '--set-json', 'gateway.trustedProxyCIDRs=["192.0.2.0/24"]']
docs = [d for d in yaml.safe_load_all(subprocess.check_output(v2)) if d]
assert len([d for d in docs if d['kind'] == 'BackendTrafficPolicy']) == 1
result = subprocess.run(v2 + ['--set-json', 'gateway.trustedProxyCIDRs=[]'], capture_output=True)
assert result.returncode != 0 and b'gateway.trustedProxyCIDRs' in result.stderr
print('Default and disabled IP bans plus optional frontend PROXY v2 validation passed')

# Opt-in Realm ACLs must be loaded by both processes on every replica restart.
docs = [d for d in yaml.safe_load_all(subprocess.check_output(cmd + ['-f', str(ROOT / 'realm-access.values.yaml')])) if d]
redis_state = next(d for d in docs if d['kind'] == 'StatefulSet' and d['metadata']['name'].endswith('-redis-ha-server'))
pod = redis_state['spec']['template']['spec']
assert next(v for v in pod['volumes'] if v['name'] == 'realm-acl')['configMap']['name'] == 'skymist-realm-redis-acl'
for name, file in [('redis', 'redis.acl'), ('sentinel', 'sentinel.acl')]:
    container = next(c for c in pod['containers'] if c['name'] == name)
    assert container['args'][-2:] == ['--aclfile', '/realm-acl/' + file]
    mount = next(m for m in container['volumeMounts'] if m['name'] == 'realm-acl')
    assert mount['readOnly'] and mount['mountPath'] == '/realm-acl' and 'subPath' not in mount
print('Opt-in Redis and Sentinel persistent Realm ACL includes and projections passed')
