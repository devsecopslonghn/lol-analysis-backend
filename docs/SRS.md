# LoL ROFL Analysis Platform — Software Requirements Specification

## 1. Objective

Build a read-only analysis service that extracts compact, evidence-backed data
from League of Legends `.rofl` files. The dashboard visualizes the data; the AI
coach reads the generated JSON context and explains player impact, movement,
ganks, invades, objective setup and macro decisions.

The replay binary is never sent to the model. The model must not invent
coordinates, events or patch-specific semantics.

## 2. Scope

### MVP

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

### Subsequent releases

- Patch-verified death/objective/spell/ward event adapters.
- Player entity mapping and movement segments.
- Jungle camp, invade and gank detection.
- Objective setup windows and causal impact chains.
- Persistent database/search and multi-user authentication.

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

## 5. Non-functional requirements

- Read-only parsing and least-privilege runtime container.
- No secrets, Riot API keys or raw PII in source, logs or reports committed to Git.
- Upload limit 128 MiB and bounded request body processing.
- JSON schema versioning for dashboard compatibility.
- Reproducible Docker and Helm deployment.
- Tests must prove metadata parsing, team aggregation, unsupported movement safety
  and API health behavior.

## 6. Acceptance criteria

```bash
rofl-analyze /path/to/replay.rofl --output analysis
```

creates a match directory containing the required JSON artifacts and reports
the actual client capability status. A dashboard can list reports and inspect
all players without knowing champion-specific filenames.
