# LoL ROFL Analysis Backend

Read-only ROFL extraction and report API for a future LoL coaching dashboard.
The current release safely parses ROFL v2 metadata plus chunk/network transport
and creates generic player reports. Champion, role and player information are
fields inside `players.json`; files are not named after champions.

## Local usage

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e '.[dev]'
rofl-analyze /path/to/match.rofl --output analysis
uvicorn rofl_analyzer.api:app --host 0.0.0.0 --port 8080
```

The output directory contains generic `players.json`, `player_impacts.json`,
`analysis_context.json`, `event_chains.json`, JSONL extension points and
`transport.json` with chunk/block/opcode evidence, plus capability-aware
placeholder files for future event and movement adapters.
`movement_transport.jsonl` contains timestamped transport records for the
`0x022c` candidate; it has no coordinates, entity IDs or decoded gank meaning.
`opcode_0226_transport.jsonl` is retained as a second profile-bound candidate
for later reconciliation.
The API cache is keyed by replay SHA256, so re-uploading the same replay does
not require a second semantic parse.
The contract is documented in `docs/report.schema.json`.

For `VN2-1568084329.rofl` (patch `16.17.810.4348`), transport parsing verifies
630 chunks, 1,790,597 blocks and 264 opcodes. The report records `0x022c` as a
candidate movement signal, but does not turn it into coordinates without a
matching client decoder. The report records RoflLens' 16.14 profile as a legacy
reference only; it is explicitly marked as not applicable to this 16.17 client.

## API

- `GET /health/live`
- `GET /health/ready`
- `GET /api/v1/reports`
- `GET /api/v1/reports/{match_id}`
- `GET /api/v1/reports/{match_id}/players/{player_id}`
- `POST /api/v1/reports` with a multipart `file` field

## Safety boundary

This MVP does not claim exact ganks, invades, coordinates, death timestamps or
objective timestamps unless a verified patch-specific adapter is added. It
reports these capabilities as unavailable instead of applying a stale profile.
