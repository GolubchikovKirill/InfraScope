# Rollout Policy (Compose-first)

## Progressive rollout

1. Update branch and run local checks (`pytest`, frontend tests, `docker compose config -q`).
2. Deploy to target server with `./scripts/deploy-compose-prod.sh`.
3. Validate readiness and smoke checks.
4. Monitor operational metrics and logs for the watch window.

## Required gates

- Service descriptor validation (`services/*/service.yaml`)
- Lint + tests for changed services
- Successful image build
- Readiness check: `curl -kfsS https://localhost/ready`
- Smoke checks: `./scripts/smoke-contract.sh`

## SLO watch window

- 15 minutes after rollout:
  - 5xx rate stable
  - p95 latency not regressing >20%
  - no sustained alert spikes
