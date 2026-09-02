"""Deterministic, match-history coaching features.

This module deliberately stays at match granularity. Riot match-v5 gives
post-game facts, not a second-by-second event stream, so this output describes
recurring patterns and match-level loss paths rather than invented ganks.
"""

from __future__ import annotations

import hashlib
from statistics import mean
from typing import Any


FEATURE_LABELS = {
    "kill_participation": "kill participation",
    "gold_share": "share of team gold",
    "damage_share": "share of team champion damage",
    "objective_damage_share": "share of team objective damage",
    "cs_per_minute": "CS per minute",
    "vision_per_minute": "vision per minute",
    "deaths": "deaths",
    "time_dead_seconds": "time dead",
}


def player_id_for_puuid(puuid: str) -> str:
    """Return a stable opaque identifier without putting the PUUID in a URL."""
    return hashlib.sha256(puuid.encode("utf-8")).hexdigest()[:20]


def analyze_player_dataset(dataset: dict[str, Any]) -> dict[str, Any]:
    player = dataset.get("player") if isinstance(dataset.get("player"), dict) else {}
    puuid = str(player.get("puuid") or "")
    rows = [_features(match, puuid) for match in dataset.get("matches", []) if isinstance(match, dict)]
    rows = [row for row in rows if row.get("match_id")]
    wins = [row for row in rows if row.get("win") is True]
    losses = [row for row in rows if row.get("win") is False]
    baseline = {
        "matches": len(rows),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": _ratio(len(wins), len(rows)),
        "wins_features": _averages(wins),
        "losses_features": _averages(losses),
        "sample_quality": "strong" if len(wins) >= 5 and len(losses) >= 5 else "limited",
    }
    return {
        "schema_version": 1,
        "analysis_type": "personal_match_history_coaching",
        "player_id": player_id_for_puuid(puuid) if puuid else None,
        "player": {key: player.get(key) for key in ("game_name", "tag_line") if player.get(key)},
        "evidence_contract": {
            "granularity": "match",
            "source": "Riot match-v5 post-game participant data",
            "unknown": ["Exact event timestamps, route, gank location and play-by-play causality are not available from this dataset."],
        },
        "baseline": baseline,
        "recurring_mistakes": _recurring_mistakes(wins, losses),
        "loss_paths": [_loss_path(row, baseline) for row in losses],
        "charts": {"history": _history_chart(rows), "win_loss_comparison": _comparison_chart(wins, losses)},
        "match_features": rows,
    }


def _features(match: dict[str, Any], puuid: str) -> dict[str, Any]:
    participants = [item for item in match.get("participants", []) if isinstance(item, dict)]
    player = next((item for item in participants if item.get("puuid") == puuid), None)
    if player is None:
        return {}
    team_id = player.get("team_id")
    allies = [item for item in participants if item.get("team_id") == team_id]
    minutes = max(_num(match.get("game_duration_seconds")) / 60, 1 / 60)
    team_kills = sum(_num(item.get("kills")) for item in allies)
    team_gold = sum(_num(item.get("gold_earned")) for item in allies)
    team_damage = sum(_num(item.get("champion_damage")) for item in allies)
    team_objective_damage = sum(_num(item.get("objective_damage")) for item in allies)
    takedowns = _num(player.get("kills")) + _num(player.get("assists"))
    return {
        "match_id": match.get("match_id"), "game_creation_ms": match.get("game_creation_ms"),
        "game_version": match.get("game_version"), "win": player.get("win"),
        "champion": player.get("champion_name"), "role": _role(player), "team_id": team_id,
        "kills": _num(player.get("kills")), "deaths": _num(player.get("deaths")), "assists": _num(player.get("assists")),
        "gold": _num(player.get("gold_earned")), "cs": _num(player.get("total_minions_killed")),
        "team_kills": team_kills, "team_gold": team_gold, "team_damage": team_damage,
        "team_objective_damage": team_objective_damage,
        "kill_participation": _ratio(takedowns, team_kills), "gold_share": _ratio(_num(player.get("gold_earned")), team_gold),
        "damage_share": _ratio(_num(player.get("champion_damage")), team_damage),
        "objective_damage_share": _ratio(_num(player.get("objective_damage")), team_objective_damage),
        "cs_per_minute": _num(player.get("total_minions_killed")) / minutes,
        "vision_per_minute": _num(player.get("vision_score")) / minutes,
        "time_dead_seconds": _num(player.get("time_dead_seconds")), "champion_damage": _num(player.get("champion_damage")),
        "objective_damage": _num(player.get("objective_damage")), "vision_score": _num(player.get("vision_score")),
        "game_duration_seconds": _num(match.get("game_duration_seconds")),
    }


def _recurring_mistakes(wins: list[dict[str, Any]], losses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rules = (
        ("kill_participation", "low", .12, "combat participation fell in losses"),
        ("gold_share", "low", .05, "resource share fell in losses"),
        ("damage_share", "low", .08, "resource was not converted into champion damage"),
        ("objective_damage_share", "low", .08, "damage was not converted into objective pressure"),
        ("cs_per_minute", "low", 1.0, "farm rate fell in losses"),
        ("vision_per_minute", "low", .015, "map-control activity fell in losses"),
        ("deaths", "high", 1.5, "deaths increased in losses"),
        ("time_dead_seconds", "high", 25.0, "availability decreased through time dead"),
    )
    results = []
    for metric, direction, threshold, summary in rules:
        win_value, loss_value = _average(wins, metric), _average(losses, metric)
        if win_value is None or loss_value is None:
            continue
        delta = loss_value - win_value
        triggered = delta <= -threshold if direction == "low" else delta >= threshold
        if triggered:
            results.append({
                "id": f"{metric}_loss_pattern", "type": "recurring_pattern",
                "status": "observed" if len(wins) >= 3 and len(losses) >= 3 else "candidate",
                "metric": metric, "label": FEATURE_LABELS[metric], "summary": summary,
                "comparison": {"wins": round(win_value, 4), "losses": round(loss_value, 4), "delta": round(delta, 4)},
                "evidence": [f"matches[{row['match_id']}].features.{metric}" for row in losses],
                "confidence": "high" if len(wins) >= 5 and len(losses) >= 5 else "limited_sample",
            })
    return sorted(results, key=lambda item: abs(item["comparison"]["delta"]), reverse=True)


def _loss_path(row: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    win_features = baseline.get("wins_features", {})
    steps = []
    for phase, metric, direction, threshold, finding in (
        ("resource", "gold_share", "low", .04, "the player received less team-resource share"),
        ("combat", "kill_participation", "low", .12, "the player contributed to fewer takedowns"),
        ("conversion", "objective_damage_share", "low", .08, "output converted into less objective pressure"),
        ("availability", "deaths", "high", 1.5, "deaths reduced the time available to make the next play"),
    ):
        current, reference = _num(row.get(metric)), _num(win_features.get(metric))
        triggered = current <= reference - threshold if direction == "low" else current >= reference + threshold
        if triggered and reference:
            steps.append({"phase": phase, "finding": finding,
                          "comparison": {"match": round(current, 4), "win_baseline": round(reference, 4), "delta": round(current - reference, 4)},
                          "evidence": [f"matches[{row['match_id']}].features.{metric}"],
                          "confidence": "limited_sample" if baseline.get("sample_quality") == "limited" else "derived"})
    return {"match_id": row["match_id"], "result": "loss",
            "headline": " → ".join(item["phase"] for item in steps) or "no_material_deviation_from_personal_win_baseline",
            "steps": steps, "limitations": ["Match-level diagnostic; it does not claim when or where the cause happened."]}


def _history_chart(rows: list[dict[str, Any]]) -> dict[str, Any]:
    keys = ("match_id", "game_creation_ms", "win", "champion", "role", "kills", "deaths", "assists", "gold", "cs", "champion_damage")
    return {"x": "game_creation_ms", "series": [{key: row.get(key) for key in keys} for row in rows]}


def _comparison_chart(wins: list[dict[str, Any]], losses: list[dict[str, Any]]) -> dict[str, Any]:
    return {"metrics": [{"key": key, "label": label, "wins": _average(wins, key), "losses": _average(losses, key)} for key, label in FEATURE_LABELS.items()]}


def _averages(rows: list[dict[str, Any]]) -> dict[str, float | None]:
    return {key: _average(rows, key) for key in FEATURE_LABELS}


def _average(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [_num(row.get(key)) for row in rows]
    return round(mean(values), 4) if values else None


def _role(player: dict[str, Any]) -> str:
    lane, role = str(player.get("lane") or "").upper(), str(player.get("role") or "").upper()
    return lane if lane and lane != "NONE" else role if role and role != "NONE" else "UNKNOWN"


def _ratio(value: float, total: float) -> float:
    return round(value / total, 4) if total else 0.0


def _num(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) and value is not None else 0.0
