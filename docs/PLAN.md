# Implementation plan

## Phase 1 — report foundation (implemented)

1. ROFL v2 header/tail metadata reader.
2. Generic player/team JSON contract.
3. Derived metrics and capability warnings.
4. CLI and FastAPI report endpoints.
5. Tests with synthetic metadata and the supplied replay as a smoke check.
6. SHA256 cache, generic player impact artifact and event-chain extension point.
7. Transport chunk/block parser with per-opcode counts and observed time windows.

## Phase 2 — verified event adapters (requires a verified patch profile)

1. Add exact patch/profile adapters for death, objective, ward and spell events.
2. Emit compact `events.jsonl` and objective windows.
3. Add golden fixtures where totals reconcile with metadata.
4. Keep unsupported patch behavior as a clean fallback.

## Phase 3 — movement and causal coaching

1. Decode player entities only with a verified profile.
2. Reconstruct movement segments and semantic zones.
3. Detect candidate clears, invades, ganks and counter-ganks.
4. Build event chains with evidence references and confidence.
5. Add player impact reports and dashboard timeline/map views.

## Phase 4 — platform hardening

1. Persistent database/cache and report retention policy.
2. Authentication and per-user access control.
3. Optional Riot Match-V5 enrichment behind an explicit configuration flag.
4. CI image scans, deployment promotion and operational dashboards.

## Rollback

The MVP has no database migration and no destructive action. Roll back by
reverting the GitOps Application/chart revision and retaining the report PVC.
Deleting the report PVC would delete user analysis data and requires an explicit
backup/retention decision.
