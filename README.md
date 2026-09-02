# LoL ROFL Analysis Backend

Personal LoL coaching API with a Riot API-first history pipeline and optional
read-only ROFL extraction.
The current release safely parses ROFL v2 metadata plus chunk/network transport
and creates generic player reports. Champion, role and player information are
fields inside `players.json`; files are not named after champions. Reports now
also include canonical `champion_key` and `champion_id` fields when the local
catalog recognizes the champion.

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

## Riot API collector

The MVP can collect official profile, rank and match-history data into a
chart-ready dataset. It uses `account-v1`, `summoner-v4`, `league-v4` and
`match-v5`; the default routing for Vietnamese accounts is `vn2` + `sea`.
Keep both credentials server-side:

```bash
export RIOT_API_KEY='your-server-side-riot-key'
export RIOT_COLLECT_TOKEN='a-separate-internal-token'
riot-collect "Riot ID game name" TAG --output riot-dataset.json
```

The HTTP collector is `POST /api/v1/riot/collect` and requires the
`X-Collector-Token` header. It is intentionally disabled until
`RIOT_COLLECT_TOKEN` is configured, so a public frontend cannot spend the Riot
API quota. `chart_data` in the response is match-history data, not an
in-game movement timeline.

For `VN2-1568084329.rofl` (patch `16.17.810.4348`), transport parsing verifies
630 chunks, 1,790,597 blocks and 264 opcodes. The report records `0x022c` as a
candidate movement signal, but does not turn it into coordinates without a
matching client decoder. The report keeps RoflLens' 16.14 profile as a
`candidate`/warning-only fallback; it is never presented as verified for this
16.17 client.

## API

- `GET /health/live`
- `GET /health/ready`
- `GET /api/v1/reports`
- `GET /api/v1/reports/{match_id}`
- `GET /api/v1/reports/{match_id}/players/{player_id}`
- `GET /api/v1/reports/{match_id}/timeline`
- `GET /api/v1/reports/{match_id}/analysis`
- `POST /api/v1/reports` with a multipart `file` field
- `POST /api/v1/riot/collect` with a Riot ID request body and
  `X-Collector-Token`
- `GET /api/v1/players/{player_id}`
- `GET /api/v1/players/{player_id}/analysis`
- `GET /api/v1/players/{player_id}/charts`
- `GET /api/v1/players/{player_id}/matches`

The collector persists data below `RIOT_DATA_ROOT` (default
`/var/lib/rofl-analysis/riot`) and returns a stable opaque `player_id` derived
from PUUID. Its deterministic analysis compares the player's own wins and
losses; it does not pretend that match-v5 contains movement or event timing.

## Safety boundary

This MVP does not claim exact ganks, invades, coordinates, death timestamps or
objective timestamps unless a verified patch-specific adapter is added. It
reports the stale profile as a warning-only candidate and keeps the actual
semantic artifacts empty until exact client assets are available.
