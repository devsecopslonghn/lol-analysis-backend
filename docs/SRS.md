# LoL ROFL Analysis Platform — Software Requirements Specification

## 1. Objective

Build a personal League of Legends coaching service. The primary MVP input is
official Riot API match history for one player identified by PUUID. The service
normalizes matches, builds a personal win/loss baseline, detects recurring
patterns and explains how a loss diverged from the player's own winning games.
ROFL remains an optional evidence source for future exact timeline analysis.

The replay binary is never sent to the model. The model must not invent
coordinates, events or patch-specific semantics.

## 2. Scope

### MVP — Riot API first

- Resolve Riot ID/tagline to PUUID through `account-v1`; use PUUID as the
  canonical user key.
- Collect summoner profile, ranked entries and bounded match history through
  `summoner-v4`, `league-v4` and `match-v5`.
- Persist a normalized, chart-ready player dataset and never expose the Riot
  API key to the browser.
- Compare the player's wins and losses, preferably by champion/role when the
  sample supports it, across participation, resources, damage, objectives,
  farm, vision and availability.
- Emit recurring mistakes and a match-level `loss_path` with evidence paths;
  label small samples as `candidate` rather than presenting them as facts.
- Render history and win/loss comparison charts before asking an AI coach to
  write prose. AI consumes the normalized analysis context, not raw API calls.

### Optional ROFL input

- Validate ROFL v2 containers and parse metadata.
- Extract match, team and player reports using generic filenames.
- Preserve champion, role and player identity inside JSON fields.
- Derive KDA, gold, CS, damage, vision, objective and disconnect metrics.
- Generate `summary.json`, `players.json`, `timeline.json`,
  `objectives.json`, `movement.json`, `analysis_context.json` and `run.json`.
- Expose read-only report APIs and a bounded ROFL upload/analyze endpoint.
- Mark unsupported event/movement semantics explicitly.
- Emit generic per-player impact dimensions and an event-chain contract for
  `precondition → action → outcome → conversion → impact`.
- Parse and retain transport-layer chunk/block timestamps and opcode evidence
  without mislabeling patch-bound packet semantics.
- Emit timestamped transport candidate JSONL artifacts for future decoders,
  with opcode provenance and `transport_only` confidence.
- Cache generated reports by replay SHA256 and parser schema version.
- Accept `.rofl` reports as a separate transport/metadata evidence stream.
- Join ROFL and Riot data only when identity and match ID are verified.

### Subsequent releases

- Patch-verified death/objective/spell/ward event adapters.
- Player entity mapping and movement segments.
- Jungle camp, invade and gank detection.
- Objective setup windows and causal impact chains.
- Patch-verified death/objective/spell/ward event adapters and exact replay
  movement semantics.
- Champion/role-specific baselines with larger longitudinal samples.
- Database/search and multi-user authentication/consent controls.

## 3. Evidence contract

Every claim must be classified as one of:

- `verified`: directly present in replay or deterministic parser output;
- `derived`: deterministic calculation from verified fields;
- `inferred`: coaching interpretation supported by evidence references;
- `unknown`: unavailable or unsafe to infer;
- `candidate`: an older profile/reference may be used for comparison, but its
  output is warning-only and is never a verified game event.

Movement, camp ownership, exact gank location and exact death/objective
timestamps are `unknown` unless a matching semantic profile is verified. When
an older profile exists, the report may expose it as `candidate` with an
explicit warning. This is comparison-only evidence: it must not be used to
emit coordinates, player routes or gank events for another client version.
Transport candidate records contain framing evidence only.
Aggregate impact dimensions are `derived`; they are signals for the AI or
dashboard, not an automatic quality score.

## 4. Functional requirements

| ID | Requirement |
| --- | --- |
| FR-01 | Parse ROFL v2 header and tail metadata without mutating the replay. |
| FR-02 | Produce one generic player collection; champion is a field, never the report filename. |
| FR-03 | Include source SHA256, parser version, client version and capability status. |
| FR-04 | Generate compact AI context instead of exposing raw replay bytes. |
| FR-05 | Reject oversized, malformed and non-ROFL uploads with stable errors. |
| FR-06 | Cache/report storage must be keyed by replay SHA256 and parser/profile version. |
| FR-07 | The API must return liveness/readiness endpoints suitable for Kubernetes. |
| FR-08 | A future verified movement adapter must never run when patch/profile/client hashes do not match; an older profile may remain visible as warning-only candidate evidence. |
| FR-09 | Event chains must represent `precondition → action → outcome → conversion → impact`. |
| FR-10 | The frontend must consume backend JSON and must not recreate analysis rules. |
| FR-11 | Timestamped movement/opcode candidate artifacts must remain explicitly transport-only until an exact decoder is verified. |
| FR-12 | Riot API credentials must remain server-side; collected profile/history data must identify its API source, routing and collection time. |
| FR-13 | The canonical player key is a stable opaque hash of PUUID; Riot ID/tagline is a display/bootstrap field. |
| FR-14 | `POST /api/v1/riot/collect` must persist a normalized dataset and return analysis plus chart data. |
| FR-15 | Analysis must compare personal wins/losses and attach evidence paths to recurring patterns and loss paths. |
| FR-16 | The API must expose profile, analysis, charts and match data by opaque `player_id`. |
| FR-17 | A small sample must produce a limited-confidence/candidate signal, never a definitive coaching claim. |

## 5. Non-functional requirements

- Read-only parsing and least-privilege runtime container.
- No secrets, Riot API keys or raw PII in source, logs or reports committed to Git.
- Upload limit 128 MiB and bounded request body processing.
- JSON schema versioning for dashboard compatibility and additive feature evolution.
- Existing PVC storage is acceptable for the single-replica MVP; writes must be
  atomic and the storage boundary must be replaceable by a database later.
- Reproducible Docker and Helm deployment.
- Tests must prove metadata parsing, team aggregation, unsupported movement safety,
  API health behavior and mocked Riot API normalization.

## 6. Riot API and coaching contract

| Endpoint | Purpose | Auth/data boundary |
| --- | --- | --- |
| `POST /api/v1/riot/collect` | Resolve Riot ID, collect profile/rank/matches, persist dataset, return analysis | `X-Collector-Token`; Riot key remains backend-only |
| `GET /api/v1/players/{player_id}` | Read safe profile, routing/source and rank metadata | opaque PUUID hash |
| `GET /api/v1/players/{player_id}/analysis` | Read baseline, recurring patterns, loss paths and evidence | opaque PUUID hash |
| `GET /api/v1/players/{player_id}/charts` | Read chart-ready history and win/loss comparison series | opaque PUUID hash |
| `GET /api/v1/players/{player_id}/matches` | Read normalized post-game matches | opaque PUUID hash |

The collector request is:

```json
{
  "game_name": "Player name",
  "tag_line": "VN2",
  "platform": "vn2",
  "regional": "sea",
  "start": 0,
  "count": 20
}
```

The collector uses Riot `account-v1` → `summoner-v4` → `league-v4` →
`match-v5`. The normalized dataset stores match ID, patch/version, queue,
teams, participant identity/champion/role, KDA, gold, CS, damage, objective
damage, vision, items and available challenges. The feature layer derives
kill participation, gold/damage/objective shares, CS/vision per minute,
deaths/time dead, personal win/loss baseline and a loss path with these
phases: `resource → combat → conversion → availability`.

The response is chart-first. A prose/AI layer may consume `analysis` only after
the deterministic feature layer has produced it. It must quote evidence paths,
state sample quality, and preserve the limitation that match-v5 is not a
play-by-play timeline.

## 7. Acceptance criteria

```bash
rofl-analyze /path/to/replay.rofl --output analysis
```

creates a match directory containing the required JSON artifacts and reports
the actual client capability status. A dashboard can list reports and inspect
all players without knowing champion-specific filenames.

For the personal coaching flow, configure `RIOT_API_KEY` and a separate
`RIOT_COLLECT_TOKEN`, then send a Riot ID request to `POST /api/v1/riot/collect`.
The response must contain `player_id`, `dataset`, `analysis.baseline`,
`analysis.recurring_mistakes`, `analysis.loss_paths` and `analysis.charts`.
The analysis is useful without ROFL, but it is match-level: no API response is
allowed to claim an exact gank, route, coordinate or event timestamp.
