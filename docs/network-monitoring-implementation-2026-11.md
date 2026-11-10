# Network monitoring implementation

## Baseline, 10 November 2026

Local repository: `D:/Main Files/InfraScope`, branch `dev`, source SHA `01e885c`.
The production checkout reports the same SHA. This does not establish the
revision baked into the running images, which were created on 29 October.
SSH alias `infrascope-server` works. Credentials remain in the existing SSH setup.
Implementation uses a separate worktree and branch, preserving the main worktree changes.

Read-only production report (`scripts/network_freshness_report.py`):

| Class | Total | Online | Offline | Unknown | No attempt in 30 minutes |
|---|---:|---:|---:|---:|---:|
| Computer | 131 | 96 | 35 | 0 | 32 |
| Media player | 28 | 18 | 10 | 0 | 0 |
| Switch | 34 | 34 | 0 | 0 | 0 |
| Printer | 53 | 33 | 8 | 12 | 12 |
| Cash register | 86 | 82 | 4 | 0 | 0 |

These are database observations, not independently verified device availability.
Computer circuits skip probes without updating last_polled_at, which is one
possible cause of aged observations and needs investigation by reason and site.
Scheduled checks currently run every 15 minutes; toner collection is hourly.
Worker RSS was 1.67 GiB in one sample. This is insufficient to diagnose a leak.

## Implemented package

- Add per-color observation timestamps with additive Alembic migration.
- Preserve old levels and their timestamps on missing or unknown SNMP data.
- Keep zero as a valid empty measurement. A missing MIB level is unknown.
- Keep the aggregate timestamp conservative for compatibility.
- Timestamp page count independently of toner collection.
- Record quantitative toner history at measurement time and suppress repeated
  writes of the same cached observation within normal serialized polling.
- Expire toner displays after ten minutes, naming affected colors.
- Hide stale low-toner details and predictions on printer cards.
- Re-evaluate UI expiry every thirty seconds even without server responses.
- Mark aged availability in printer, label-printer, switch, media-player,
  computer and cash-register cards. The temporary threshold is thirty minutes,
  matching two current polling intervals.
- Add a read-only aggregate freshness diagnostic.

Historical per-color timestamps deliberately start empty because aggregate
timestamps cannot prove which slots were actually read. The next valid poll
establishes each slot's measurement time.

## Outstanding implementation

1. Verify running-image source hashes and database migration revision, measure
   queue lag and full-cycle p95, and inspect stale computers by failure reason.
2. Decouple availability cadence (target 60 seconds) and full telemetry cadence
   (target five minutes). First measure cycle duration and queue capacity.
   The ten-minute toner expiry currently exposes the hourly collection gap.
3. Add shared API freshness/service-health representation and apply it to list
   filters, dashboard totals, alerts and forecasts, including per-color history
   consumers. Current changes cover card presentation and history producers.
4. Enforce per-device ownership across single/bulk polling, owner-safe lease
   release, reject out-of-order results and prove concurrency on PostgreSQL.
   History deduplication currently assumes existing polling serialization.
5. Unify path/device/service health evidence across all classes, add explicit
   site dependencies and distinguish direct AP/camera evidence from PoE state.
6. Collect freshness/queue metrics and alerts. Add recorded protocol fixtures
   and failure scenarios for interrupted routes, worker loss, DHCP identity
   changes, partial MIB data and unsupported equipment.
7. Run the migration and release to one pilot site after verification. Observe
   48 hours and evaluate the agreed freshness targets before wider rollout.
8. Benchmark a Go read-only collector only if measured collection CPU/RSS or
   throughput remains the limiting factor after the polling changes.

## Verification

The targeted backend suite covering polling, cartridge journal, schemas,
resilience and reachability passed (61 tests). Additional toner/parser/forecast
tests passed (22 tests, overlapping the new regression file). Ruff and TypeScript
passed. The affected frontend suites passed (17 tests), and production frontend
build passed. Alembic generated the expected PostgreSQL ALTER TABLE offline.
Production migration and deployment have not been performed.

Vite cannot reliably resolve paths containing `#`. Frontend validation uses a
temporary source copy without that character and the existing installed node
dependencies. Running an entire frontend suite in the asynchronous terminal
did not return a completion result; only the targeted suites are confirmed.
