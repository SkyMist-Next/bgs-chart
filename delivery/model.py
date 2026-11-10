"""Pure compatibility and durable promotion transitions; no network or cluster writes."""
import copy
import hashlib
import json
import re

SERVICES = ('operator', 'bgs', 'admin')
SHA = re.compile(r'^[a-f0-9]{40}$')
DIGEST = re.compile(r'^registry\.neomatik\.eu/skymist/(admin|bgs|operator)@sha256:[a-f0-9]{64}$')


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def manifest(value, application=True):
    if value.get('service') not in SERVICES or type(value.get('deploymentContract')) is not int or value['deploymentContract'] < 1:
        raise ValueError('Invalid service or deploymentContract')
    if not application:
        return
    for capabilities in [value['provides'], *value['requires'].values()]:
        if not isinstance(capabilities, dict) or any(not isinstance(k, str) or not k or type(v) is not int or v < 1 for k, v in capabilities.items()):
            raise ValueError('Capabilities must map names to positive integer versions')
    if any(s not in SERVICES or s == value['service'] for s in value['requires']):
        raise ValueError('Invalid prerequisite service')


def candidate(value):
    manifest(value)
    if not SHA.fullmatch(value['sourceSha']) or not DIGEST.fullmatch(value['image']) or value['image'].split('@')[0].rsplit('/', 1)[1] != value['service']:
        raise ValueError('Candidate must identify exact source and service image digest')
    if type(value['runId']) is not int or value['runId'] < 1 or type(value['runAttempt']) is not int or value['runAttempt'] < 1:
        raise ValueError('Missing workflow provenance')


def compatible(release, deployed, healthy):
    """Validate the proposed graph, including consumers of removed capabilities."""
    graph = dict(deployed, **{release['service']: release})
    for service, item in graph.items():
        for provider, capabilities in item['requires'].items():
            if provider not in graph:
                return False, f'{service} waiting for {provider}'
            if service == release['service'] and provider != release['service'] and not healthy.get(provider, False):
                return False, f'{provider} is not healthy'
            for capability, version in capabilities.items():
                if graph[provider]['provides'].get(capability) != version:
                    return False, f'{service} requires {provider}/{capability}@{version}'
    visiting, visited = set(), set()
    def visit(service):
        if service in visiting:
            raise ValueError('Dependency cycle')
        if service in visited:
            return
        visiting.add(service)
        for dependency in graph[service]['requires']:
            visit(dependency)
        visiting.remove(service)
        visited.add(service)
    for service in graph:
        visit(service)
    return True, 'compatible'


def initial():
    return {'version': 1, 'enabled': False, 'paused': None, 'pending': None,
            'lastSuccessful': None, 'candidates': {}, 'releases': {}, 'schemaFloor': {}, 'appliedMigrations': []}


def enqueue(state, value):
    candidate(value)
    state = copy.deepcopy(state)
    state['candidates'][identity(value)] = value
    return state


def select(state, chart, source_head):
    """Newest compatible application at HEAD, otherwise retain accepted image."""
    manifest(chart, application=False)
    matching = [v for v in state['candidates'].values() if v['sourceSha'] == source_head and v['deploymentContract'] == chart['deploymentContract']]
    if matching:
        return max(matching, key=lambda v: (v['runId'], v['runAttempt']))
    previous = state['releases'].get(state['lastSuccessful'])
    if previous and previous['deploymentContract'] == chart['deploymentContract']:
        return {k: v for k, v in previous.items() if k not in ('chartSha', 'id', 'snapshot', 'jobs', 'archive')}
    return None


def release(value, chart_sha):
    if value.get('provenance') == 'helm-adoption':
        manifest(value)
        if not DIGEST.fullmatch(value['image']):
            raise ValueError('Adoption requires an immutable image digest')
    else:
        candidate(value)
    if not SHA.fullmatch(chart_sha):
        raise ValueError('Invalid chart SHA')
    result = dict(value, chartSha=chart_sha)
    result['id'] = identity(result)
    return result


def reserve(state, release, now, recovery=False):
    state = copy.deepcopy(state)
    if state['pending']:
        raise ValueError('Promotion already in progress')
    if not state['enabled'] or (state['paused'] and not recovery):
        raise ValueError('Promotion disabled or paused')
    if not recovery and state['lastSuccessful'] == release['id']:
        return state
    # Schemas are forward-only. Explicit rollback must advertise every already applied version.
    for capability, version in state['schemaFloor'].items():
        if release['provides'].get(capability, 0) < version:
            raise ValueError('Release cannot operate with applied schema: ' + capability)
    if not set(state.get('appliedMigrations', [])) <= set(release.get('schemaMigrations', [])):
        raise ValueError('Release does not support already applied migrations')
    state['appliedMigrations'] = sorted(set(state.get('appliedMigrations', [])) | set(release.get('schemaMigrations', [])))
    state['releases'][release['id']] = release
    state['pending'] = {'release': release['id'], 'started': now, 'deadline': now + 1800,
                        'healthySince': None, 'lastObserved': None, 'revision': None}
    # DDL may commit before a later gate fails; reserve the floor before attempting sync.
    for capability, version in release['provides'].items():
        if 'schema' in capability:
            state['schemaFloor'][capability] = max(version, state['schemaFloor'].get(capability, 0))
    return state


def observe(state, now, healthy, failure=None):
    state = copy.deepcopy(state)
    pending = state['pending']
    if not pending:
        return state
    if pending.get('lastObserved') is not None and now - pending['lastObserved'] > 30:
        pending['healthySince'] = None
    pending['lastObserved'] = now
    if failure or now >= pending['deadline']:
        state['paused'] = {'release': pending['release'], 'reason': failure or 'Deployment deadline exceeded', 'at': now}
        state['pending'] = None
    elif not healthy:
        pending['healthySince'] = None
    elif pending['healthySince'] is None:
        pending['healthySince'] = now
    elif now - pending['healthySince'] >= 120:
        state['lastSuccessful'] = pending['release']
        state['paused'] = None
        state['pending'] = None
    return state
