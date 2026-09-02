from __future__ import annotations

import os
import re
import tempfile
import hashlib
import secrets
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .rofl import MAX_REPLAY_BYTES, PARSER_VERSION, SCHEMA_VERSION, ReplayParseError, _upgrade_report, parse_replay, write_report_data
from .player_store import PlayerDatasetStore
from .riot_api import RiotApiClient, RiotApiError


REPORT_ROOT = Path(os.getenv("ROFL_REPORT_ROOT", "/var/lib/rofl-analysis/reports"))
UPLOAD_ROOT = Path(os.getenv("ROFL_UPLOAD_ROOT", "/var/lib/rofl-analysis/uploads"))
CACHE_ROOT = Path(os.getenv("ROFL_CACHE_ROOT", "/var/lib/rofl-analysis/cache"))
RIOT_DATA_ROOT = Path(os.getenv("RIOT_DATA_ROOT", "/var/lib/rofl-analysis/riot"))
PLAYER_STORE = PlayerDatasetStore(RIOT_DATA_ROOT)
app = FastAPI(title="LoL ROFL Analysis API", version="0.4.0")
allowed_origins = [item.strip() for item in os.getenv("ROFL_ALLOWED_ORIGINS", "http://localhost:5173").split(",") if item.strip()]
app.add_middleware(CORSMiddleware, allow_origins=allowed_origins, allow_methods=["GET", "POST"], allow_headers=["*"])


class RiotCollectRequest(BaseModel):
    game_name: str = Field(min_length=1, max_length=64)
    tag_line: str = Field(min_length=1, max_length=16)
    platform: str = Field(default="vn2", min_length=2, max_length=5)
    regional: str = Field(default="sea", min_length=3, max_length=9)
    start: int = Field(default=0, ge=0)
    count: int = Field(default=20, ge=1, le=100)


@app.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
def ready() -> dict[str, str]:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    RIOT_DATA_ROOT.mkdir(parents=True, exist_ok=True)
    return {"status": "ok"}


@app.get("/api/v1/reports")
def list_reports() -> dict[str, object]:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    reports = []
    paths = sorted(REPORT_ROOT.glob("*/summary.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in paths:
        try:
            data = _upgrade_report(_read_json(path))
            reports.append({
                "match_id": data.get("match_id", path.parent.name),
                "game": data.get("game"),
                "teams": data.get("teams"),
                "created_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            })
        except ValueError:
            continue
    return {"reports": reports}


@app.get("/api/v1/reports/{match_id}")
def get_report(match_id: str) -> dict[str, object]:
    return _load_report(match_id)


@app.get("/api/v1/reports/{match_id}/players/{player_id}")
def get_player(match_id: str, player_id: str) -> dict[str, object]:
    report = _load_report(match_id)
    for player in report.get("players", []):
        if player.get("player_id") == player_id:
            return {"match_id": match_id, "player": player, "capabilities": report.get("capabilities")}
    raise HTTPException(status_code=404, detail="player not found")


@app.get("/api/v1/reports/{match_id}/timeline")
def get_timeline(match_id: str) -> dict[str, object]:
    report = _load_report(match_id)
    return {"match_id": match_id, "timeline": report.get("timeline"), "capabilities": report.get("capabilities")}


@app.get("/api/v1/reports/{match_id}/analysis")
def get_analysis(match_id: str) -> dict[str, object]:
    report = _load_report(match_id)
    return {
        "match_id": match_id,
        "analysis": report.get("analysis"),
        "event_chains": report.get("event_chains"),
        "capabilities": report.get("capabilities"),
    }


@app.post("/api/v1/riot/collect")
def collect_riot(
    request: RiotCollectRequest,
    x_collector_token: str | None = Header(default=None),
) -> dict[str, object]:
    """Collect Riot profile/history data without exposing the Riot API key."""
    configured_token = os.getenv("RIOT_COLLECT_TOKEN", "")
    if not configured_token:
        raise HTTPException(status_code=503, detail="Riot collector is not configured")
    if not x_collector_token or not secrets.compare_digest(x_collector_token, configured_token):
        raise HTTPException(status_code=401, detail="collector authentication required")
    try:
        client = RiotApiClient.from_env(platform=request.platform, regional=request.regional)
        dataset = client.collect_player_history(
            request.game_name,
            request.tag_line,
            start=request.start,
            count=request.count,
        )
        return PLAYER_STORE.save(dataset)
    except RiotApiError as exc:
        status = exc.status_code if exc.status_code in {404, 429} else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@app.get("/api/v1/players/{player_id}")
def get_player_profile(player_id: str) -> dict[str, object]:
    stored = _load_player(player_id)
    return {"player_id": stored["player_id"], "player": stored["dataset"].get("player"), "source": stored["dataset"].get("source"), "ranked": stored["dataset"].get("ranked")}


@app.get("/api/v1/players/{player_id}/analysis")
def get_player_analysis(player_id: str) -> dict[str, object]:
    stored = _load_player(player_id)
    return {"player_id": stored["player_id"], "analysis": stored["analysis"]}


@app.get("/api/v1/players/{player_id}/charts")
def get_player_charts(player_id: str) -> dict[str, object]:
    stored = _load_player(player_id)
    return {"player_id": stored["player_id"], "charts": stored["analysis"].get("charts", {})}


@app.get("/api/v1/players/{player_id}/matches")
def get_player_matches(player_id: str) -> dict[str, object]:
    stored = _load_player(player_id)
    return {"player_id": stored["player_id"], "matches": stored["dataset"].get("matches", [])}


@app.post("/api/v1/reports", status_code=201)
async def analyze_upload(file: UploadFile = File(...)) -> JSONResponse:
    if not file.filename or not file.filename.lower().endswith(".rofl"):
        raise HTTPException(status_code=400, detail="only .rofl files are accepted")
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=UPLOAD_ROOT, suffix=".rofl", delete=False) as handle:
            temp_path = Path(handle.name)
            total = 0
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_REPLAY_BYTES:
                    raise HTTPException(status_code=413, detail="replay file exceeds the 128 MiB safety limit")
                handle.write(chunk)
        match_id = Path(file.filename).stem
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", match_id):
            raise HTTPException(status_code=400, detail="filename must contain only safe match-id characters")
        source_sha = _sha256(temp_path)
        cached = _load_cached_report(source_sha)
        report = cached or parse_replay(temp_path)
        output = write_report_data(report, REPORT_ROOT, match_id=match_id, transport_source=temp_path)
        if cached is None:
            write_report_data(report, CACHE_ROOT, match_id=_cache_key(source_sha), transport_source=temp_path)
        return JSONResponse(status_code=201, content={"match_id": match_id, "report_path": str(output), "cache_hit": cached is not None})
    except ReplayParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)
        await file.close()


def _load_report(match_id: str) -> dict[str, object]:
    if Path(match_id).name != match_id:
        raise HTTPException(status_code=400, detail="invalid match id")
    path = REPORT_ROOT / match_id / "summary.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="report not found")
    try:
        return _upgrade_report(_read_json(path))
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="report is invalid") from exc


def _load_player(player_id: str) -> dict[str, object]:
    try:
        stored = PLAYER_STORE.load(player_id)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="player dataset is invalid") from exc
    if stored is None:
        raise HTTPException(status_code=404, detail="player dataset not found")
    return stored


def _read_json(path: Path) -> dict[str, object]:
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("report root is not an object")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_cached_report(source_sha: str) -> dict[str, object] | None:
    path = CACHE_ROOT / _cache_key(source_sha) / "summary.json"
    if not path.is_file():
        return None
    try:
        cached = _read_json(path)
    except (OSError, ValueError):
        return None
    if cached.get("source", {}).get("sha256") != source_sha:
        return None
    return cached


def _cache_key(source_sha: str) -> str:
    return f"schema-{SCHEMA_VERSION}-parser-{PARSER_VERSION}-{source_sha}"
