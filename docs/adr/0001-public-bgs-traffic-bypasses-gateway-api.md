# Public BGS traffic bypasses Gateway API

Frontend (1119) and REST (443) are exposed through one plain `LoadBalancer` Service with `externalTrafficPolicy: Cluster` and Cilium DSR, not a Gateway. On Cilium a Gateway mixing a TLS-passthrough listener (served by Envoy on every node) with a TCPRoute (programmed straight to frontend Pods) makes every node announce the BGP address, while only nodes running a frontend Pod serve 1119; the rest refuse connections. BGP announces per address, not per port, and the frontend must see the client's real source IP for login ticket checks and IP bans, so the Service forwards from any node without SNAT.

## Considered Options

- **`externalTrafficPolicy: Local` with frontend and REST Pods pinned to the same nodes**: correct only while the scheduler keeps them together; any reschedule refuses connections again.
- **Separate addresses for 1119 and 443**: the client reaches both through one hostname.
- **`Cluster` with SNAT, or a PROXY v2 gateway**: SNAT hides the client IP; PROXY v2 needs Envoy Gateway in front of the frontend, which the cluster does not run.
