# Service delivery

Default-branch workflows test applications before publishing Linux/amd64 images.
Charts own `deploy` (self-contained Helm snapshot), `delivery-state` (durable
candidate, pause, schema floor and accepted-release journal), and
`delivery-releases` (immutable snapshot history). The operator chart also owns
`delivery-lock`, a compare-and-swap lease serializing cross-service graph checks.

`manifest.json` declares an integer `deploymentContract`. Increment it in both
repositories for coordinated breaking chart/application changes. `provides` and
`requires` use exact capability versions; add a new capability alongside the old
one to stage changes used by deployed consumers. `schemaMigrations` records the
forward-only migration inventory. A recovery must support every migration that
may have run, including migrations in failed deployments. No down-migrations run.

Source workflows are pinned to default-branch HEAD, the expected workflow path,
repository, event, run ID and attempt. Dispatch payloads never supply a trusted
image or source revision. Periodic reconciliation recovers missed events. A
chart-only change retains the accepted application image unless a current
compatible application candidate is waiting. Duplicate releases are no-ops.

All promotion workflows share a per-repository concurrency group. The global
lease prevents concurrent provider/consumer promotions across repositories;
non-fast-forward state writes fail instead of overwriting another run. The
lease exceeds the deployment deadline and cannot be stolen while any service
has an unresolved deployment. Expired pending deployments are durably paused by
scheduled reconciliation before a new lease is acquired.
Cancelling a run releases the lease only if that run attempt still owns it
(`reconcile.py --release-lease`); its pending deployment stays recorded and the
next reconciliation resumes observing it.

A new state journal starts disabled. Adopt and verify operator, BGS, then admin
before setting `enabled: true`. Existing Helm records remain recovery evidence.
The bootstrap Applications have no deletion finalizers. Their Projects exclude
Realm and platform-controller ownership; upstream CRDs are not installed.
`PruneLast=true` delays stateless pruning until successful sync; protected
resources carry `Prune=false,Delete=false`. Removed protected resources remain
OutOfSync and require explicit cleanup review. Never remove those annotations
merely to make a deployment green.

Verification uses only a projected, rotating ServiceAccount token. It can read
workloads, Jobs, Realms, three Applications and HTTP health proxies in the target
namespace; it cannot read Secrets, execute commands, or modify workloads.
Image builders have no Kubernetes token. Argo uses read-only repository deploy
keys. The GitHub App token is restricted to the enumerated repositories and
requested Contents/Actions permissions. Publication credentials are environment
secrets and are removed at job completion. Applications opt out of inherited Slack notifications.

The verifier requires the expected Argo revision to be Synced/Healthy with a
successful operation, exact workload image digests, complete hooks, readiness,
HTTP smoke checks, and current realm-directory publication after operator
changes. Health must remain continuously sampled for two minutes within the
30-minute deadline; an observation gap resets the stability timer.
Hook names come from the exact-revision Argo operation. When automated
self-heal replaces it with a partial sync of the same revision, the recorded
hook Jobs are checked live instead and must have been created after the
delivery attempt started. Each observation prints what it is waiting for.

## Recovery

Inspect `delivery-state/state.json`, the failed Actions run, and the Argo
operation. Builds continue while paused. Reconciliation archives new compatible
candidates, so a forward fix has an explicit release ID even while paused.
Run **Compatible service delivery** on the chart's default branch with `release`
set to a full recorded release ID. Retry, forward fix and reviewed rollback all
use the exact archived chart and application image and repeat compatibility and
health gates. A failed recovery remains paused. Do not edit `deploy` by hand or
clear `paused` to bypass recovery checks.

The three chart working copies must carry identical delivery controller modules; copy
changes from operator-chart and run each chart's `delivery/check.py`. Application
and chart branches have independent tests. Operator fixture pins are recorded in
`operator/delivery/siblings.json`; these are test dependencies, not deployment
sources. Native client acceptance remains a separate check.
