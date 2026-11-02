# BGS chart

Helm 3+ / Kubernetes 1.31+, Gateway API v1 including TCPRoute, a compatible
Gateway controller, MariaDB operator 26.10.1+, and RabbitMQ Cluster Operator
must be installed first. Operators are shared infrastructure, not dependencies
of this release. Newer RabbitMQ operators also require cert-manager.

Build the current sibling `bgs/` image, which includes `scripts/deploy.js` and
migrations. Old netcho/bnetserver images cannot run this chart. Supply immutable
image tags. Redis HA 4.39.0 is locked and vendored.

## Local development

For the existing Minikube `bgs-test` environment, use the sibling project's
Skaffold configuration from `../bgs`:

```sh
nvm use
skaffold run --kube-context minikube
npm run test:local
skaffold dev --kube-context minikube --cleanup=false
```

This selects `values-local.yaml`, the existing `bgs-test-envoy` GatewayClass,
and `webAuthUrl=https://bgs.local:8443/bnetserver/login/`. The BGS helpers discover
and forward Envoy on localhost ports 1119/8443 and retain an opt-in test account.
See [BGS local development](../bgs/README.md#local-kubernetes-with-skaffold) for
credentials, certificate trust, prerequisites, and cleanup behavior.

Use an explicit Minikube context. Install operators watching the test namespace.
Import externally issued dev credentials (SAN `bgs.local`) and the public dev CA:

```sh
cd ../bgs
npm run local:tls -- --cert /secure/dev-fullchain.pem --key /secure/dev-key.pem --ca /secure/dev-ca.pem
```

The namespace must already exist. See the BGS TLS provisioning documentation for
file requirements, direct Node configuration, and certificate renewal.

The local profile runs one MariaDB, RabbitMQ, and Redis/Sentinel node. It still
uses Sentinel discovery and migrations, with automatic schema sync disabled.
GatewayClass `cilium` must exist and support v1 TCPRoute (Cilium 1.20+).
For older Minikube Cilium, install a separate compatible controller such as
Envoy Gateway and override gateway.className; see tests/VALIDATION.md. Route bgs.local to the
Gateway address. Certificates are not generated or committed by this chart.

## Production

Use `values-production.yaml` and supply `image.repository`, `image.tag`,
`gateway.hostname`, `gateway.frontendSecret`, and `gateway.restSecret`.
The example references skymist-db in skymist-cata; that operator only watches
skymist-cata, so install the BGS release there. Verify the primary Service name
before installation. Each release must use a distinct database.name when sharing
a MariaDB. The chart does not alter or own the existing MariaDB instance.

Production uses two replicas of each BGS service, three RabbitMQ nodes and three
Redis/Sentinel nodes. Redis requires distinct nodes by default. Adjust resources,
storage classes and capacity before installation. Frontend TCPRoute passes TLS
on 1119 to Pods; REST HTTPS terminates at the Gateway, with only the login path
routed to HTTP port 8080. Internal health listens on 8081.

Optional `webAuthUrl` overrides the advertised HTTPS login base URL, including a
forwarded port; it must end in `/bnetserver/login/`. When empty, the chart uses
`https://<gateway.hostname>/bnetserver/login/` as before.

## Discovery contracts

The runtime MariaDB User has `skymist.io/database-role=bgs-runtime`; the migration
User has `bgs-migrator`. Narrow discovery with namespace and
`app.kubernetes.io/instance=<release>`. Read spec.name, spec.host and spec.mariaDbRef
from the selected User for future Grants; never guess from the object name.
Neither these labels nor creation of the chart's Grant transfers User ownership
to skymist-operator.

Discover the ConfigMap with `skymist.io/connection-type=bgs-redis` and the release
label. Its REDIS_SENTINELS, REDIS_MASTER_NAME and REDIS_DB describe the shared
store. REDIS_PASSWORD_SECRET_NAME/KEY and
REDIS_SENTINEL_PASSWORD_SECRET_NAME/KEY reference credentials in the same
namespace. Passwords are never stored in the ConfigMap.

Future worldserver Pods must carry `skymist.io/redis-client=<release>` and consume
this configuration and Secrets. NetworkPolicy permits those same-namespace Pods
to reach every Redis/Sentinel node on 6379/26379, including promoted primaries.
These are shared credentials, not per-realm ACL identities. This chart does not
modify skymist-operator or add Redis support to worldserver binaries.

## Bootstrap, migrations and recovery

Ordinary Jobs work with Helm --wait and GitOps without post-install hooks.
Bootstrap creates credentials once; it never replaces existing Secrets. Secrets
have no owner reference and survive release deletion. The bootstrap account can
create Secrets in its namespace (Kubernetes cannot restrict create by name) but
can read only this release's credential names. Application Pods have no API token.

Migrations use the runtime image's JavaScript migrations and Sequelize; no CLI
installation or model synchronization is needed. A database-specific Lease
serializes jobs in the namespace. Renewal failure terminates execution. A journal
marks a migration before DDL; interrupted DDL blocks retries until inspected.
SequelizeMeta is the completion gate for new application Pods. Migration jobs
have no automatic retries, a 15-minute deadline, and retained logs. Use immutable
image tags so a new image creates a new migration Job.

For failed migrations, inspect Job logs and BgsMigrationJournal using migration
credentials. MariaDB DDL is not transactional. Repair/reconcile the failed
migration before clearing its journal entry and explicitly recreating the failed
Job. Never clear history blindly or run down migrations during Helm rollback.
Bootstrap/migration Job names include the Helm release revision as well as the
values hash. Each Helm upgrade runs fresh idempotent Jobs, including upgrades
where Skaffold substitutes image references after Helm rendering.
Only backward-compatible schema changes are safe during rolling application
upgrades. Existing SQL Database/User/Grant resources use cleanupPolicy Skip;
Redis/RabbitMQ PVCs and generated Secrets require explicit cleanup after uninstall.
Changing database identity requires deliberate credential/data migration; the
bootstrap refuses mismatched existing credentials.

Argo CD must apply all ordinary resources without adding waves that wait for BGS
Deployments before their bootstrap/migration Jobs. Do not auto-prune retained
credentials or PVCs. Rollback only to images compatible with the current schema.

## Validation

```sh
python3 tests/render.py
helm lint . -f values-local.yaml --set image.repository=bgs,image.tag=local
```

Integration acceptance includes fresh/repeated migrations, account data retention,
concurrent migration exclusion, competing worker consumers, Redis failover,
worldserver-shaped consumer access, Gateway TLS and graceful shutdown. Native
client acceptance is a separate check. Worker quorum queues prevent broadcast to
every replica, but do not promise exactly-once delivery across broker failures.

TLS Secrets are externally owned and are never generated by this chart. Use separate
dev/production CAs. A Secret may be shared by `gateway.frontendSecret` and
`gateway.restSecret`; it must contain a matching `tls.crt` full chain and unencrypted
PEM `tls.key`. Local tooling additionally requires public `ca.crt`. Frontend mounts
use a full Secret volume with mode 0440 and fsGroup 1000, allowing Node to reload
updates without a restart. Keep Secret updates mutable and verify Gateway renewal
behavior. No CA signing keys belong in these Secrets.
