# Rollout Policy (Kubernetes-first)

## Progressive rollout

1. Deploy to `dev` overlay and run smoke checks.
2. Deploy to `staging` overlay and run contract + integration checks.
3. Manual approval.
4. Deploy to `prod` with rolling/canary strategy.

## Required gates

- Service descriptor validation (`services/*/service.yaml`)
- Lint + tests for changed services
- Image build
- Security scan (SBOM + vulnerability scan)
- Smoke checks against health endpoints

## SLO watch window

- 15 minutes after rollout:
  - 5xx rate stable
  - p95 latency not regressing >20%
  - no sustained alert spikes
