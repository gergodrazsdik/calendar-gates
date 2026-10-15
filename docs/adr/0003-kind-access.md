# 3. Reach the app on kind through a port-forward, not an Ingress

- Status: accepted
- Date: 2026-10-15

## Context

The local cluster `kind-local` (one node, Kubernetes 1.37) is prepared for an ingress controller:
the node has the `ingress-ready` label and maps container ports 80/443 to host ports 8080/8443.
No controller is installed, though, and there are no Gateway API CRDs. The cluster belongs to the
machine setup (`~/bin/kind-local`), not to this project, so installing cluster-wide components
from here would change it for every other project. ingress-nginx, the usual kind example, was
retired in March 2026, so a new install would be a Gateway API implementation.

## Decision

- `just k8s-http` and the CI `k8s-smoke` job reach the Service with
  `kubectl port-forward svc/calendar-gates 18080:80` and run the `.http` tests with the `forward`
  environment (`http://localhost:18080`).
- The chart keeps an Ingress template, off by default (`ingress.enabled: false`), so a cluster with
  a controller can turn it on (`--set ingress.enabled=true --set ingress.className=<class>`,
  host `calendar.localhost`). `lint` validates the rendered Ingress either way.

## Consequences

- No new cluster-wide components; local and CI access work the same way.
- A port-forward goes to one pod, so it doesn't exercise load balancing across the two replicas.
- If kind-local gets a Gateway API controller later, add an `HTTPRoute` template and a `kind`
  environment (`http://calendar.localhost:8080`) and supersede this ADR.
