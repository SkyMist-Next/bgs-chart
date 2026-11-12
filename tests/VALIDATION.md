# Validation recorded 2026-11-02

- Helm local/production lint and deterministic render contract checks passed.
- BGS lint and all 88 Node tests passed, including worker queue and health listener coverage.
- Production Docker image built with migrations and deployment runner.
- Minikube bgs-test release revision 4 reached deployed with --wait --wait-for-jobs.
- Standalone MariaDB, RabbitMQ, and Redis/Sentinel ready; all five BGS Deployments ready.
- All six migrations applied; Account and GameAccount model SELECTs succeeded using runtime credentials.
- A same-namespace simulated realm Pod consumed the discovery ConfigMap and Secret references, discovered the Redis primary through authenticated Sentinel, and received PONG.
- Gateway HTTPS login form returned 200; frontend TLS certificate verification passed through the TCPRoute.

Local prerequisites added: namespace-scoped MariaDB operator, RabbitMQ operator
2.23.2, cert-manager, Gateway API v1 TCPRoute CRD, Envoy Gateway 1.9.3 and
bgs-test-envoy GatewayClass. Minikube's existing Cilium 1.18 cannot handle the
chart's TCPRoute, so the test selected gateway.className=bgs-test-envoy.
The Gateway LoadBalancer has no external address in this Minikube setup;
traffic acceptance used port-forwarding to its Envoy Service.

Production multi-node failover, negative NetworkPolicy cases, migration crash/
concurrency recovery, full authentication with persisted account fixtures, and
native WoW client acceptance remain separate integration checks. No production
release was installed. Local test resources remain for inspection.

## Social worker static validation, 2026-11-12

Chart 2.3.0 adds a seventh Deployment for `node social.js`. Validation used
Helm 4.3.0, the installed Python/PyYAML environment, and the chart's Kubernetes
1.31.0 version floor. Renders used the synthetic `contract` namespace. No cluster,
CNI, admission policy, broker or database was contacted; production policy
compatibility and worker readiness remain unverified.

- Local and production Helm lint passed.
- `tests/render.py` passed serially: deterministic rendering, seven Deployments,
  social entrypoint, health-only port, `/ready` and `/alive` probes, schema gate,
  inherited resources and broker/Redis credentials, restricted pod settings,
  replica/resource overrides, matching PDB selectors, and invalid-value rejection.
- Existing public routing and TLS/authenticator Secret isolation checks passed;
  no Service selects the social worker and only frontend/REST routes are created.
- Strict kubeconform validation against Kubernetes 1.31.0 passed for the
  production render: 49 resources, 38 valid, 0 invalid, 0 errors, 11 custom
  resources skipped for unavailable schemas. The schema validator used one
  worker. This is not API-server or CRD validation.
- The sibling `bgs/package.json` contains `social: "node social.js"`; no dependency
  or lockfile changes were needed. Git whitespace checks passed.

Reproduction commands, with no build or deployment:

```sh
../admin/.venv/bin/python tests/render.py
helm lint . -f values-local.yaml --set image.repository=bgs,image.tag=social-validation
helm lint . -f values-production.yaml --set image.repository=bgs,image.tag=social-validation,gateway.hostname=bgs.example
helm template contract . -n contract --kube-version 1.31.0 -f values-production.yaml --set image.repository=bgs,image.tag=social-validation,gateway.hostname=bgs.example > /tmp/bgs-social-production.yaml
kubeconform -n 1 -strict -summary -ignore-missing-schemas -kubernetes-version 1.31.0 /tmp/bgs-social-production.yaml
```

The sibling operator's `provision_realm_rpc` ACL now includes
`skymist.realm.social.v1.requests` in the BGS worker's configure/write/read rules
on `skymist-realms`. Four focused broker contract tests pass, including rejection
of realm access to this queue and of unrelated queue names. Operator provisioning
rewrites these permissions, so the operator change must accompany runtime
rollout. Existing exchange and default-exchange reply grants remain suitable.
Server-side dry-run,
actual admission, second AMQP connection readiness, broker recovery and native
client acceptance remain separate checks after the operator/runtime integration.

## Social integration on Minikube, 2026-11-12

The chart rendered against the retained local release values and passed API-server
dry-run on Minikube Kubernetes 1.35.1. The existing release was not upgraded.
A separate `bgs-social-validation` namespace ran a disposable Job with MariaDB
11.4.10, Redis 8.2 and RabbitMQ 4.3.6 as native sidecars. It completed successfully
with seven social migrations and the real three-client protocol harness.

The harness verified direct 15595/authenticated world 26972 subscriptions,
bilateral friendships, active-character presence, whispers in both directions,
worker restart with persisted subscriptions/outbox, and stale generation rejection.
It removed its unique SQL schema, Redis keys and broker identities/vhosts.
The image ID was `sha256:3e7a0e2278e6459103c2360ac4b59a4058d47ae7f42fd6b1c465ffd60a2a15e1`.
Logs and manifests are retained in the workspace `.validation/social/minikube`.
This validates the protocol harness in a Pod; it does not establish a chart
rollout, production performance/failover or native game-client acceptance.
