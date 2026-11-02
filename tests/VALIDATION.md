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
