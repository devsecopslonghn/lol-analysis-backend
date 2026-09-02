from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import Any


ROFL_MAGIC = b"RIOT"
FORMAT_VERSION = 2
SCHEMA_VERSION = 2
PARSER_VERSION = "0.2.0"
MAX_REPLAY_BYTES = 128 * 1024 * 1024


class ReplayParseError(ValueError):
    """Raised when a replay cannot be safely parsed."""


def parse_replay(path: str | Path) -> dict[str, Any]:
    replay_path = Path(path).expanduser().resolve()
    if not replay_path.is_file():
        raise ReplayParseError("replay file does not exist")
    if replay_path.stat().st_size > MAX_REPLAY_BYTES:
        raise ReplayParseError("replay file exceeds the 128 MiB safety limit")

    raw = replay_path.read_bytes()
    header = _parse_header(raw)
    metadata = _parse_tail_metadata(raw)
    participants = [_participant_summary(item, index) for index, item in enumerate(metadata["stats"])]
    duration = metadata["gameLength"] / 1000 if metadata.get("gameLength") is not None else None
    teams = _team_summaries(participants, duration)
    capabilities = {
        "container": {"status": "verified", "reason": "ROFL v2 header and metadata parsed"},
        "participants": {"status": "verified", "reason": "statsJson participant records parsed"},
        "summary_metrics": {"status": "derived", "reason": "calculated from participant metadata"},
        "event_timeline": {
            "status": "unknown",
            "reason": "patch-specific event decoder is not bundled for this replay",
        },
        "movement_semantics": {
            "status": "unknown",
            "reason": f"no verified semantic profile for {header['client_version']}",
        },
    }
    match_id = replay_path.stem
    report = {
        "schema_version": SCHEMA_VERSION,
        "match_id": match_id,
        "source": {
            "file_name": replay_path.name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "cache_key": _cache_key(hashlib.sha256(raw).hexdigest()),
        },
        "parser": {"name": "lol-rofl-analysis-backend", "version": PARSER_VERSION},
        "game": {
            "patch": header["client_version"],
            "duration_seconds": duration,
            "format_version": header["format_version"],
        },
        "capabilities": capabilities,
        "teams": teams,
        "players": participants,
        "timeline": {
            "events": [],
            "status": "unavailable",
            "reason": capabilities["event_timeline"]["reason"],
        },
        "objectives": {
            "events": [],
            "status": "unavailable",
            "reason": "objective events require a verified patch-specific event decoder",
        },
        "movement": {
            "segments": [],
            "status": "unavailable",
            "reason": capabilities["movement_semantics"]["reason"],
        },
        "event_chains": {
            "items": [],
            "status": "unavailable",
            "reason": "causal chains require verified event and movement evidence",
            "shape": ["precondition", "action", "outcome", "conversion", "impact"],
        },
        "analysis": {
            "facts": _report_facts(participants, teams, duration),
            "inferences": [],
            "unknowns": [
                "Exact gank, invade, route, death and objective timestamps are not emitted without a verified event profile.",
                "No coordinate or path claim may be made from this report.",
            ],
            "method": "metadata_first",
        },
    }
    return report


def write_report(path: str | Path, output_dir: str | Path, *, match_id: str | None = None) -> Path:
    return write_report_data(parse_replay(path), output_dir, match_id=match_id)


def write_report_data(report: dict[str, Any], output_dir: str | Path, *, match_id: str | None = None) -> Path:
    report = dict(report)
    if match_id:
        report["match_id"] = match_id
    target = Path(output_dir).expanduser().resolve() / report["match_id"]
    target.mkdir(parents=True, exist_ok=True)
    _write_json(target / "summary.json", report)
    _write_json(target / "metadata.json", {"game": report["game"], "source": report["source"], "capabilities": report["capabilities"]})
    _write_json(target / "players.json", {"match_id": report["match_id"], "players": report["players"]})
    _write_json(target / "timeline.json", report["timeline"])
    _write_json(target / "objectives.json", report["objectives"])
    _write_json(target / "movement.json", report["movement"])
    _write_json(target / "event_chains.json", report["event_chains"])
    _write_json(target / "player_impacts.json", {"match_id": report["match_id"], "players": report["players"]})
    (target / "events.jsonl").write_text("", encoding="utf-8")
    (target / "movement_segments.jsonl").write_text("", encoding="utf-8")
    _write_json(target / "analysis_context.json", _analysis_context(report))
    _write_json(target / "run.json", {"parser": report["parser"], "source": report["source"], "capabilities": report["capabilities"]})
    return target


def _parse_header(raw: bytes) -> dict[str, Any]:
    if len(raw) < 15 or raw[:4] != ROFL_MAGIC:
        raise ReplayParseError("invalid ROFL magic")
    format_version = struct.unpack_from("<H", raw, 4)[0]
    if format_version != FORMAT_VERSION:
        raise ReplayParseError(f"unsupported ROFL format version: {format_version}")
    version_length = raw[14]
    end = 15 + version_length
    if not version_length or end > len(raw):
        raise ReplayParseError("invalid client version length")
    try:
        client_version = raw[15:end].decode("ascii")
    except UnicodeDecodeError as exc:
        raise ReplayParseError("client version is not ASCII") from exc
    return {
        "format_version": format_version,
        "client_version": client_version,
        "header_size": end,
    }


def _parse_tail_metadata(raw: bytes) -> dict[str, Any]:
    if len(raw) < 4:
        raise ReplayParseError("replay is too small")
    metadata_length = struct.unpack_from("<I", raw, len(raw) - 4)[0]
    start = len(raw) - 4 - metadata_length
    if start < 0:
        raise ReplayParseError("metadata boundary is invalid")
    try:
        payload = json.loads(raw[start : len(raw) - 4])
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReplayParseError("metadata is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ReplayParseError("metadata root must be an object")
    raw_stats = payload.get("statsJson", "[]")
    try:
        stats = json.loads(raw_stats) if isinstance(raw_stats, str) else []
    except json.JSONDecodeError as exc:
        raise ReplayParseError("statsJson is not valid JSON") from exc
    if not isinstance(stats, list) or any(not isinstance(item, dict) for item in stats):
        raise ReplayParseError("statsJson must be a list of participant objects")
    return {**payload, "stats": stats}


def _int(item: dict[str, Any], key: str) -> int:
    try:
        return int(item.get(key, 0))
    except (TypeError, ValueError):
        return 0


def _participant_summary(item: dict[str, Any], index: int) -> dict[str, Any]:
    kills = _int(item, "CHAMPIONS_KILLED")
    deaths = _int(item, "NUM_DEATHS")
    assists = _int(item, "ASSISTS")
    team = _int(item, "TEAM")
    return {
        "player_id": str(item.get("PUUID") or item.get("ID") or index),
        "player": item.get("RIOT_ID_GAME_NAME") or item.get("NAME") or f"Player {index + 1}",
        "tag": item.get("RIOT_ID_TAG_LINE") or None,
        "champion": item.get("SKIN") or "Unknown",
        "team": team,
        "side": "blue" if team == 100 else "red" if team == 200 else "unknown",
        "role": item.get("INDIVIDUAL_POSITION") or "UNKNOWN",
        "result": "win" if item.get("WIN") == "Win" else "loss",
        "kda": {"kills": kills, "deaths": deaths, "assists": assists},
        "level": _int(item, "LEVEL"),
        "gold": _int(item, "GOLD_EARNED"),
        "cs": _int(item, "MINIONS_KILLED"),
        "jungle_cs": _int(item, "NEUTRAL_MINIONS_KILLED"),
        "stats": {
            "champion_damage": _int(item, "TOTAL_DAMAGE_DEALT_TO_CHAMPIONS"),
            "building_damage": _int(item, "TOTAL_DAMAGE_DEALT_TO_BUILDINGS"),
            "objective_damage": _int(item, "TOTAL_DAMAGE_DEALT_TO_OBJECTIVES"),
            "epic_monster_damage": _int(item, "TOTAL_DAMAGE_DEALT_TO_EPIC_MONSTERS"),
            "damage_taken_from_champions": _int(item, "TOTAL_DAMAGE_TAKEN_FROM_CHAMPIONS"),
            "time_dead_seconds": _int(item, "TOTAL_TIME_SPENT_DEAD"),
            "vision_score": _int(item, "VISION_SCORE"),
            "wards_placed": _int(item, "WARD_PLACED"),
            "wards_killed": _int(item, "WARD_KILLED"),
            "crowd_control_seconds": _int(item, "TOTAL_TIME_CROWD_CONTROL_DEALT_TO_CHAMPIONS"),
            "turrets_killed": _int(item, "TURRETS_KILLED"),
            "turret_takedowns": _int(item, "TURRET_TAKEDOWNS"),
        },
        "objectives": {
            "dragons": _int(item, "DRAGON_KILLS"),
            "heralds": _int(item, "RIFT_HERALD_KILLS"),
            "barons": _int(item, "BARON_KILLS"),
        },
        "derived": {
            "kill_participation": None,
            "last_takedown_seconds": _int(item, "LAST_TAKEDOWN_TIME"),
            "takedowns_before_15m": _int(item, "Missions_TakedownsBefore15Min"),
            "structure_takedowns": _int(item, "Missions_TakedownStructures"),
            "epic_monster_takedowns": _int(item, "Missions_TakedownEpicMonsters"),
            "time_disconnected_seconds": _int(item, "TIME_SPENT_DISCONNECTED"),
        },
        "evidence": {"source": "ROFL metadata statsJson", "confidence": "verified"},
    }


def _team_summaries(players: list[dict[str, Any]], duration_seconds: float | None) -> list[dict[str, Any]]:
    result = []
    for team, side in ((100, "blue"), (200, "red")):
        members = [p for p in players if p["team"] == team]
        kills = sum(p["kda"]["kills"] for p in members)
        for player in members:
            player["derived"]["kill_participation"] = round((player["kda"]["kills"] + player["kda"]["assists"]) / kills, 4) if kills else None
        result.append({
            "team": team,
            "side": side,
            "result": "win" if any(p["result"] == "win" for p in members) else "loss",
            "players": len(members),
            "kills": kills,
            "deaths": sum(p["kda"]["deaths"] for p in members),
            "assists": sum(p["kda"]["assists"] for p in members),
            "gold": sum(p["gold"] for p in members),
            "champion_damage": sum(p["stats"]["champion_damage"] for p in members),
            "time_dead_seconds": sum(p["stats"]["time_dead_seconds"] for p in members),
            "avg_level": round(sum(p["level"] for p in members) / len(members), 2) if members else None,
            "members": [p["player_id"] for p in members],
        })
        team_damage = sum(p["stats"]["champion_damage"] for p in members)
        team_gold = sum(p["gold"] for p in members)
        for player in members:
            player["derived"].update(
                {
                    "kill_share": round(player["kda"]["kills"] / kills, 4) if kills else None,
                    "damage_share": round(player["stats"]["champion_damage"] / team_damage, 4) if team_damage else None,
                    "gold_share": round(player["gold"] / team_gold, 4) if team_gold else None,
                    "time_dead_ratio": round(player["stats"]["time_dead_seconds"] / duration_seconds, 4) if duration_seconds else None,
                    "objective_takedowns": player["derived"]["epic_monster_takedowns"],
                }
            )
            player["impact"] = {
                "dimensions": {
                    "tempo": {"takedowns_before_15m": player["derived"]["takedowns_before_15m"]},
                    "resource": {"gold": player["gold"], "cs": player["cs"], "jungle_cs": player["jungle_cs"]},
                    "combat": {
                        "kill_participation": player["derived"]["kill_participation"],
                        "damage_share": player["derived"]["damage_share"],
                        "time_dead_ratio": player["derived"]["time_dead_ratio"],
                    },
                    "objective": {
                        "epic_monster_takedowns": player["derived"]["epic_monster_takedowns"],
                        "objective_damage": player["stats"]["objective_damage"],
                        "structure_takedowns": player["derived"]["structure_takedowns"],
                    },
                    "map": {
                        "vision_score": player["stats"]["vision_score"],
                        "wards_placed": player["stats"]["wards_placed"],
                    },
                },
                "evidence": {"source": "ROFL metadata and deterministic team-relative calculations", "confidence": "derived"},
            }
    return result


def _report_facts(players: list[dict[str, Any]], teams: list[dict[str, Any]], duration: float | None) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    if duration is not None:
        facts.append({"type": "game_duration", "value_seconds": duration, "confidence": "verified"})
    for team in teams:
        facts.append({"type": "team_score", "side": team["side"], "kills": team["kills"], "deaths": team["deaths"], "confidence": "derived"})
    for player in players:
        if player["derived"]["time_disconnected_seconds"]:
            facts.append({"type": "disconnect", "player_id": player["player_id"], "seconds": player["derived"]["time_disconnected_seconds"], "confidence": "verified"})
    return facts


def _analysis_context(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "match_id": report["match_id"],
        "game": report["game"],
        "teams": report["teams"],
        "players": report["players"],
        "timeline": report["timeline"],
        "objectives": report["objectives"],
        "movement": report["movement"],
        "event_chains": report["event_chains"],
        "analysis": report["analysis"],
        "capabilities": report["capabilities"],
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _cache_key(source_sha: str) -> str:
    return f"schema-{SCHEMA_VERSION}-parser-{PARSER_VERSION}-{source_sha}"
