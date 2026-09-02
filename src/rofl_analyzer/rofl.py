from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path
from typing import Any

from .transport import (
    SIGNATURE_SIZE,
    TransportParseError,
    legacy_profile_reference,
    summarize_transport,
    write_transport_artifacts,
)


ROFL_MAGIC = b"RIOT"
FORMAT_VERSION = 2
SCHEMA_VERSION = 2
PARSER_VERSION = "0.3.2"
MAX_REPLAY_BYTES = 128 * 1024 * 1024


# The replay metadata exposes the champion display name, not a stable asset
# identifier. Keep the small catalog local so report generation remains
# offline and deterministic. Unknown champions remain explicit instead of
# being guessed from a similarly named asset.
CHAMPION_CATALOG: dict[str, tuple[int, str, str]] = {
    "akali": (84, "Akali", "Akali"),
    "ashe": (22, "Ashe", "Ashe"),
    "ahri": (103, "Ahri", "Ahri"),
    "garen": (86, "Garen", "Garen"),
    "graves": (104, "Graves", "Graves"),
    "illaoi": (420, "Illaoi", "Illaoi"),
    "karthus": (30, "Karthus", "Karthus"),
    "khazix": (121, "Khazix", "Kha'Zix"),
    "kha'zix": (121, "Khazix", "Kha'Zix"),
    "kaisa": (145, "Kaisa", "Kai'Sa"),
    "kai'sa": (145, "Kaisa", "Kai'Sa"),
    "malphite": (54, "Malphite", "Malphite"),
    "mel": (902, "Mel", "Mel"),
    "poppy": (78, "Poppy", "Poppy"),
    "pyke": (555, "Pyke", "Pyke"),
    "rengar": (107, "Rengar", "Rengar"),
    "renekton": (58, "Renekton", "Renekton"),
    "sejuani": (77, "Sejuani", "Sejuani"),
    "sivir": (15, "Sivir", "Sivir"),
    "smolder": (147, "Smolder", "Smolder"),
    "syndra": (134, "Syndra", "Syndra"),
    "talon": (91, "Talon", "Talon"),
    "thresh": (412, "Thresh", "Thresh"),
    "varus": (110, "Varus", "Varus"),
    "viktor": (112, "Viktor", "Viktor"),
    "xerath": (101, "Xerath", "Xerath"),
    "xin zhao": (5, "XinZhao", "Xin Zhao"),
    "yasuo": (157, "Yasuo", "Yasuo"),
    "yone": (777, "Yone", "Yone"),
    "zac": (154, "Zac", "Zac"),
    "zyra": (143, "Zyra", "Zyra"),
}


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
    metadata_length = struct.unpack_from("<I", raw, len(raw) - 4)[0]
    metadata_start = len(raw) - 4 - metadata_length
    signature_start = metadata_start - SIGNATURE_SIZE
    try:
        transport = summarize_transport(
            raw,
            chunks_start=header["header_size"],
            chunks_end=signature_start,
            client_version=header["client_version"],
        )
    except TransportParseError as exc:
        raise ReplayParseError(f"invalid ROFL transport: {exc}") from exc
    participants = [_participant_summary(item, index) for index, item in enumerate(metadata["stats"])]
    duration = metadata["gameLength"] / 1000 if metadata.get("gameLength") is not None else None
    teams = _team_summaries(participants, duration)
    legacy = transport["legacy_profile_reference"]
    capabilities = {
        "container": {"status": "verified", "reason": "ROFL v2 header and metadata parsed"},
        "transport_layer": {"status": "verified", "reason": "ROFL chunks and network block framing parsed"},
        "participants": {"status": "verified", "reason": "statsJson participant records parsed"},
        "summary_metrics": {"status": "derived", "reason": "calculated from participant metadata"},
        "jungle_economy": {
            "status": "derived",
            "reason": "own/enemy neutral CS is available from verified participant metadata; camp routes are not decoded",
        },
        "event_timeline": {
            "status": "candidate",
            "reason": legacy["reason"],
            "warning": legacy["warning"],
            "profile_client_version": legacy["profile_client_version"],
        },
        "movement_semantics": {
            "status": "candidate",
            "reason": legacy["reason"],
            "warning": legacy["warning"],
            "profile_client_version": legacy["profile_client_version"],
        },
        "legacy_profile": legacy,
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
        "transport": transport,
        "teams": teams,
        "players": participants,
        "timeline": {
            "events": [],
            "status": "candidate",
            "reason": capabilities["event_timeline"]["reason"],
            "warning": capabilities["event_timeline"]["warning"],
            "transport_observations": transport["opcode_observations"],
        },
        "objectives": {
            "events": [],
            "status": "unavailable",
            "reason": "objective events require a verified patch-specific event decoder",
        },
        "movement": {
            "segments": [],
            "status": "candidate",
            "reason": capabilities["movement_semantics"]["reason"],
            "warning": capabilities["movement_semantics"]["warning"],
            "transport_observations": [item for item in transport["opcode_observations"] if item["opcode"] == 0x022C],
            "transport_artifacts": transport["artifacts"],
            "legacy_profile_reference": legacy,
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
                f"Legacy profile {legacy['profile_client_version']} is candidate-only and may be wrong for client {header['client_version']}.",
            ],
            "method": "metadata_first",
        },
    }
    return report


def write_report(path: str | Path, output_dir: str | Path, *, match_id: str | None = None) -> Path:
    return write_report_data(parse_replay(path), output_dir, match_id=match_id, transport_source=path)


def write_report_data(
    report: dict[str, Any],
    output_dir: str | Path,
    *,
    match_id: str | None = None,
    transport_source: str | Path | None = None,
) -> Path:
    report = dict(report)
    if match_id:
        report["match_id"] = match_id
    target = Path(output_dir).expanduser().resolve() / report["match_id"]
    target.mkdir(parents=True, exist_ok=True)
    _write_json(target / "summary.json", report)
    _write_json(target / "metadata.json", {"game": report["game"], "source": report["source"], "capabilities": report["capabilities"]})
    _write_json(target / "transport.json", report["transport"])
    _write_json(target / "players.json", {"match_id": report["match_id"], "players": report["players"]})
    _write_json(target / "timeline.json", report["timeline"])
    _write_json(target / "objectives.json", report["objectives"])
    _write_json(target / "movement.json", report["movement"])
    _write_json(target / "event_chains.json", report["event_chains"])
    _write_json(target / "player_impacts.json", {"match_id": report["match_id"], "players": report["players"]})
    (target / "events.jsonl").write_text("", encoding="utf-8")
    (target / "movement_segments.jsonl").write_text("", encoding="utf-8")
    if transport_source:
        try:
            raw = Path(transport_source).read_bytes()
            header = _parse_header(raw)
            metadata_length = struct.unpack_from("<I", raw, len(raw) - 4)[0]
            chunks_end = len(raw) - 4 - metadata_length - SIGNATURE_SIZE
            write_transport_artifacts(
                transport_source,
                target,
                chunks_start=header["header_size"],
                chunks_end=chunks_end,
            )
        except (OSError, struct.error, TransportParseError, ReplayParseError) as exc:
            raise ReplayParseError(f"failed to write transport artifacts: {exc}") from exc
    else:
        (target / "movement_transport.jsonl").write_text("", encoding="utf-8")
        (target / "opcode_0226_transport.jsonl").write_text("", encoding="utf-8")
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


def _flag(item: dict[str, Any], key: str) -> bool:
    return str(item.get(key, "0")).lower() in {"1", "true", "yes", "win"}


def _participant_summary(item: dict[str, Any], index: int) -> dict[str, Any]:
    kills = _int(item, "CHAMPIONS_KILLED")
    deaths = _int(item, "NUM_DEATHS")
    assists = _int(item, "ASSISTS")
    team = _int(item, "TEAM")
    champion_raw = str(item.get("SKIN") or "Unknown").strip()
    champion_id, champion_key, champion_name = _champion_identity(champion_raw)
    return {
        "player_id": str(item.get("PUUID") or item.get("ID") or index),
        "player": item.get("RIOT_ID_GAME_NAME") or item.get("NAME") or f"Player {index + 1}",
        "tag": item.get("RIOT_ID_TAG_LINE") or None,
        "champion": champion_name,
        "champion_key": champion_key,
        "champion_id": champion_id,
        "team": team,
        "side": "blue" if team == 100 else "red" if team == 200 else "unknown",
        "role": item.get("INDIVIDUAL_POSITION") or "UNKNOWN",
        "result": "win" if item.get("WIN") == "Win" else "loss",
        "kda": {"kills": kills, "deaths": deaths, "assists": assists},
        "level": _int(item, "LEVEL"),
        "gold": _int(item, "GOLD_EARNED"),
        "cs": _int(item, "MINIONS_KILLED"),
        "jungle_cs": _int(item, "NEUTRAL_MINIONS_KILLED"),
        "jungle": {
            "enemy_jungle_cs": _int(item, "NEUTRAL_MINIONS_KILLED_ENEMY_JUNGLE"),
            "own_jungle_cs": _int(item, "NEUTRAL_MINIONS_KILLED_YOUR_JUNGLE"),
        },
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
            "total_damage_dealt": _int(item, "TOTAL_DAMAGE_DEALT"),
            "total_damage_taken": _int(item, "TOTAL_DAMAGE_TAKEN"),
            "total_heal": _int(item, "TOTAL_HEAL"),
            "total_shield_on_teammates": _int(item, "TOTAL_DAMAGE_SHIELDED_ON_TEAMMATES"),
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
            "time_played_seconds": _int(item, "TIME_PLAYED"),
            "is_leaver": _flag(item, "WAS_LEAVER"),
            "was_afk": _flag(item, "WAS_AFK"),
        },
        "pings": {
            "on_my_way": _int(item, "ON_MY_WAY_PINGS"),
            "danger": _int(item, "DANGER_PINGS"),
            "enemy_missing": _int(item, "ENEMY_MISSING_PINGS"),
            "vision": _int(item, "VISION_CLEARED_PINGS"),
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
            "building_damage": sum(p["stats"]["building_damage"] for p in members),
            "time_dead_seconds": sum(p["stats"]["time_dead_seconds"] for p in members),
            "objective_control": {
                "dragons": sum(p["objectives"]["dragons"] for p in members),
                "heralds": sum(p["objectives"]["heralds"] for p in members),
                "barons": sum(p["objectives"]["barons"] for p in members),
                "epic_monster_takedowns": sum(p["derived"]["epic_monster_takedowns"] for p in members),
                "structure_takedowns": sum(p["derived"]["structure_takedowns"] for p in members),
            },
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
                    "jungle_control": player["jungle"],
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
                    "availability": {
                        "time_played_seconds": player["derived"]["time_played_seconds"],
                        "time_disconnected_seconds": player["derived"]["time_disconnected_seconds"],
                        "active_seconds": max(0, player["derived"]["time_played_seconds"] - player["derived"]["time_disconnected_seconds"]),
                    },
                },
                "signals": _impact_signals(player),
                "evidence": {"source": "ROFL metadata and deterministic team-relative calculations", "confidence": "derived"},
            }
    return result


def _report_facts(players: list[dict[str, Any]], teams: list[dict[str, Any]], duration: float | None) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    if duration is not None:
        facts.append({"type": "game_duration", "title": "Match duration", "body": f"The replay lasted {duration:.3f} seconds.", "value_seconds": duration, "confidence": "verified", "evidence": ["game.gameLength"]})
    for team in teams:
        facts.append({"type": "team_score", "title": f"{team['side'].title()} team score", "body": f"{team['side'].title()} recorded {team['kills']} kills and {team['deaths']} deaths.", "side": team["side"], "kills": team["kills"], "deaths": team["deaths"], "confidence": "derived", "evidence": [f"teams[{team['side']}].kills", f"teams[{team['side']}].deaths"]})
        facts.append({"type": "team_objective_control", "title": f"{team['side'].title()} objective totals", "body": f"Dragons {team['objective_control']['dragons']}, Heralds {team['objective_control']['heralds']}, Barons {team['objective_control']['barons']}.", "side": team["side"], **team["objective_control"], "confidence": "derived", "evidence": [f"teams[{team['side']}].objective_control"]})
    for player in players:
        if player["derived"]["time_disconnected_seconds"]:
            facts.append({"type": "disconnect", "title": f"{player['player']} disconnect signal", "body": f"Verified disconnected time: {player['derived']['time_disconnected_seconds']} seconds.", "player_id": player["player_id"], "seconds": player["derived"]["time_disconnected_seconds"], "confidence": "verified", "evidence": [f"players[{player['player_id']}].derived.time_disconnected_seconds"]})
        if player["jungle"]["enemy_jungle_cs"]:
            facts.append({"type": "enemy_jungle_resource", "title": f"{player['player']} enemy-jungle CS", "body": f"Verified enemy-jungle neutral CS: {player['jungle']['enemy_jungle_cs']}.", "player_id": player["player_id"], "cs": player["jungle"]["enemy_jungle_cs"], "confidence": "verified", "evidence": [f"players[{player['player_id']}].jungle.enemy_jungle_cs"]})
        if player["derived"]["takedowns_before_15m"]:
            facts.append({"type": "early_pressure", "title": f"{player['player']} early pressure", "body": f"Verified takedowns before 15:00: {player['derived']['takedowns_before_15m']}.", "player_id": player["player_id"], "takedowns_before_15m": player["derived"]["takedowns_before_15m"], "confidence": "verified", "evidence": [f"players[{player['player_id']}].derived.takedowns_before_15m"]})
    return facts


def _champion_identity(raw_name: str) -> tuple[int | None, str | None, str]:
    normalized = raw_name.strip().lower()
    identity = CHAMPION_CATALOG.get(normalized)
    if identity is None:
        compact = re.sub(r"[^a-z0-9]", "", normalized)
        identity = next((value for key, value in CHAMPION_CATALOG.items() if re.sub(r"[^a-z0-9]", "", key) == compact), None)
    if identity is None:
        return None, None, raw_name or "Unknown"
    champion_id, champion_key, champion_name = identity
    return champion_id, champion_key, champion_name


def _upgrade_report(report: dict[str, Any]) -> dict[str, Any]:
    """Add non-destructive fields introduced after reports were persisted."""
    players = report.get("players")
    if isinstance(players, list):
        for player in players:
            if not isinstance(player, dict):
                continue
            champion = str(player.get("champion") or "Unknown")
            champion_id, champion_key, champion_name = _champion_identity(champion)
            player.setdefault("champion_id", champion_id)
            player.setdefault("champion_key", champion_key)
            if champion_key and player.get("champion") == champion:
                player["champion"] = champion_name

    capabilities = report.setdefault("capabilities", {})
    if isinstance(capabilities, dict):
        capabilities.setdefault("jungle_economy", {
            "status": "derived",
            "reason": "own/enemy neutral CS is available from verified participant metadata; camp routes are not decoded",
        })

        game = report.get("game")
        client_version = game.get("patch") if isinstance(game, dict) else None
        legacy = legacy_profile_reference(client_version if isinstance(client_version, str) else None)
        transport = report.get("transport")
        if isinstance(transport, dict):
            transport["legacy_profile_reference"] = legacy
        capabilities.setdefault("legacy_profile", legacy)
        for name in ("event_timeline", "movement_semantics"):
            current = capabilities.get(name)
            if not isinstance(current, dict) or current.get("status") in {None, "unknown", "transport_only"}:
                capabilities[name] = {
                    "status": "candidate",
                    "reason": legacy["reason"],
                    "warning": legacy["warning"],
                    "profile_client_version": legacy["profile_client_version"],
                }

        for artifact_name, capability_name in (("timeline", "event_timeline"), ("movement", "movement_semantics")):
            artifact = report.get(artifact_name)
            capability = capabilities.get(capability_name)
            if isinstance(artifact, dict) and isinstance(capability, dict) and artifact.get("status") in {None, "unknown", "transport_only"}:
                artifact["status"] = "candidate"
                artifact["reason"] = capability["reason"]
                artifact["warning"] = capability["warning"]
                if artifact_name == "movement":
                    artifact.setdefault("legacy_profile_reference", legacy)

    teams = report.get("teams")
    game = report.get("game")
    if isinstance(players, list) and isinstance(teams, list) and isinstance(game, dict):
        analysis = report.setdefault("analysis", {})
        if isinstance(analysis, dict):
            duration = game.get("duration_seconds")
            analysis["facts"] = _report_facts(players, teams, duration if isinstance(duration, (int, float)) else None)
    return report


def _impact_signals(player: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"name": "early_pressure", "value": player["derived"]["takedowns_before_15m"], "unit": "takedowns_before_15m", "confidence": "verified"},
        {"name": "enemy_jungle_access", "value": player["jungle"]["enemy_jungle_cs"], "unit": "neutral_cs_in_enemy_jungle", "confidence": "verified"},
        {"name": "objective_conversion", "value": player["derived"]["epic_monster_takedowns"], "unit": "epic_monster_takedowns", "confidence": "derived"},
        {"name": "structure_conversion", "value": player["derived"]["structure_takedowns"], "unit": "structure_takedowns", "confidence": "derived"},
        {"name": "availability", "value": max(0, player["derived"]["time_played_seconds"] - player["derived"]["time_disconnected_seconds"]), "unit": "active_seconds", "confidence": "derived"},
    ]


def _analysis_context(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "match_id": report["match_id"],
        "game": report["game"],
        "transport": report["transport"],
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
