"""Small, server-side Riot API collector for profile and match-history data."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


PLATFORM_HOSTS = {
    "br1", "eun1", "euw1", "jp1", "kr", "la1", "la2", "na1", "oc1",
    "ru", "tr1", "ph2", "sg2", "th2", "tw2", "vn2",
}
REGIONAL_HOSTS = {"americas", "asia", "europe", "sea"}
MAX_MATCH_COUNT = 100


class RiotApiError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class RiotApiClient:
    api_key: str
    platform: str = "vn2"
    regional: str = "sea"
    timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        if not self.api_key:
            raise RiotApiError("RIOT_API_KEY is not configured")
        if self.platform not in PLATFORM_HOSTS:
            raise RiotApiError("unsupported Riot platform routing")
        if self.regional not in REGIONAL_HOSTS:
            raise RiotApiError("unsupported Riot regional routing")

    @classmethod
    def from_env(cls, *, platform: str = "vn2", regional: str = "sea") -> "RiotApiClient":
        return cls(
            os.getenv("RIOT_API_KEY", ""),
            platform=platform.lower(),
            regional=regional.lower(),
            timeout_seconds=float(os.getenv("RIOT_API_TIMEOUT_SECONDS", "15")),
        )

    def collect_player_history(
        self,
        game_name: str,
        tag_line: str,
        *,
        start: int = 0,
        count: int = 20,
        cached_matches: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if not game_name.strip() or not tag_line.strip():
            raise RiotApiError("game_name and tag_line are required")
        if start < 0 or count < 1 or count > MAX_MATCH_COUNT:
            raise RiotApiError(f"start must be >= 0 and count must be 1..{MAX_MATCH_COUNT}")

        account = self._get(
            self.regional,
            f"/riot/account/v1/accounts/by-riot-id/{_path(game_name)}/{_path(tag_line)}",
        )
        puuid = _required_string(account, "puuid", "account.puuid")
        summoner = self._get(
            self.platform,
            f"/lol/summoner/v4/summoners/by-puuid/{_path(puuid)}",
        )
        summoner_id = _required_string(summoner, "id", "summoner.id")
        ranked = self._get(self.platform, f"/lol/league/v4/entries/by-summoner/{_path(summoner_id)}")
        match_ids = self._get(
            self.regional,
            f"/lol/match/v5/matches/by-puuid/{_path(puuid)}/ids",
            {"start": start, "count": count},
        )
        if not isinstance(match_ids, list):
            raise RiotApiError("Riot match ID response is not a list")

        matches: list[dict[str, Any]] = []
        for match_id in match_ids:
            if not isinstance(match_id, str) or not match_id:
                continue
            cached = cached_matches.get(match_id) if cached_matches else None
            if cached is not None:
                matches.append(cached)
            else:
                payload = self._get(self.regional, f"/lol/match/v5/matches/{_path(match_id)}")
                matches.append(normalize_match(payload, puuid=puuid))

        return {
            "schema_version": 1,
            "dataset_type": "riot_player_match_history",
            "source": {
                "provider": "Riot Games API",
                "api_versions": ["account-v1", "summoner-v4", "league-v4", "match-v5"],
                "regional_routing": self.regional,
                "platform_routing": self.platform,
                "collected_at": datetime.now(timezone.utc).isoformat(),
            },
            "player": {
                "game_name": account.get("gameName") or game_name,
                "tag_line": account.get("tagLine") or tag_line,
                "puuid": puuid,
                "summoner_id": summoner_id,
                "summoner": _safe_fields(summoner, {"profileIconId", "summonerLevel"}),
            },
            "ranked": ranked if isinstance(ranked, list) else [],
            "matches": matches,
            "chart_data": build_history_chart(matches, puuid=puuid),
        }

    def _get(
        self,
        routing: str,
        path: str,
        params: dict[str, int] | None = None,
    ) -> Any:
        host = f"https://{routing}.api.riotgames.com"
        query = f"?{urlencode(params)}" if params else ""
        request = Request(
            f"{host}{path}{query}",
            headers={"X-Riot-Token": self.api_key, "Accept": "application/json"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 429:
                raise RiotApiError("Riot API rate limit exceeded", status_code=429) from exc
            if exc.code == 404:
                raise RiotApiError("Riot resource was not found", status_code=404) from exc
            if exc.code in {401, 403}:
                raise RiotApiError("Riot API authentication failed", status_code=exc.code) from exc
            raise RiotApiError(f"Riot API request failed with HTTP {exc.code}", status_code=exc.code) from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RiotApiError("Riot API request could not be completed") from exc


def normalize_match(payload: Any, *, puuid: str) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("info"), dict):
        raise RiotApiError("Riot match response has no info object")
    info = payload["info"]
    participants = info.get("participants")
    if not isinstance(participants, list):
        participants = []
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    return {
        "match_id": metadata.get("matchId"),
        "game_creation_ms": info.get("gameCreation"),
        "game_duration_seconds": info.get("gameDuration"),
        "game_version": info.get("gameVersion"),
        "queue_id": info.get("queueId"),
        "map_id": info.get("mapId"),
        "game_mode": info.get("gameMode"),
        "teams": [_normalize_team(team) for team in info.get("teams", []) if isinstance(team, dict)],
        "participants": [_normalize_participant(item, puuid) for item in participants if isinstance(item, dict)],
    }


def build_history_chart(matches: list[dict[str, Any]], *, puuid: str) -> dict[str, Any]:
    """Return chart-ready profile history; this is not an in-game timeline."""
    points = []
    for match in matches:
        player = next((p for p in match.get("participants", []) if p.get("puuid") == puuid), None)
        if player is None:
            continue
        points.append({
            "match_id": match.get("match_id"),
            "game_creation_ms": match.get("game_creation_ms"),
            "win": player.get("win"),
            "kills": player.get("kills"),
            "deaths": player.get("deaths"),
            "assists": player.get("assists"),
            "gold": player.get("gold_earned"),
            "cs": player.get("total_minions_killed"),
            "champion_damage": player.get("champion_damage"),
        })
    return {"x": "game_creation_ms", "series": points}


def _normalize_team(team: dict[str, Any]) -> dict[str, Any]:
    objectives = team.get("objectives") if isinstance(team.get("objectives"), dict) else {}
    return {
        "team_id": team.get("teamId"),
        "win": team.get("win"),
        "objectives": {
            name: value.get("kills")
            for name, value in objectives.items()
            if isinstance(value, dict) and "kills" in value
        },
    }


def _normalize_participant(item: dict[str, Any], requested_puuid: str) -> dict[str, Any]:
    participant = {
        "puuid": item.get("puuid"),
        "riot_id": item.get("riotIdGameName"),
        "riot_tag": item.get("riotIdTagline"),
        "champion_id": item.get("championId"),
        "champion_name": item.get("championName"),
        "team_id": item.get("teamId"),
        "win": item.get("win"),
        "kills": item.get("kills"),
        "deaths": item.get("deaths"),
        "assists": item.get("assists"),
        "gold_earned": item.get("goldEarned"),
        "total_minions_killed": item.get("totalMinionsKilled"),
        "neutral_minions_killed": item.get("neutralMinionsKilled"),
        "champion_damage": item.get("totalDamageDealtToChampions"),
        "objective_damage": item.get("damageDealtToObjectives"),
        "vision_score": item.get("visionScore"),
        "time_dead_seconds": item.get("totalTimeSpentDead"),
        "turret_damage": item.get("damageDealtToTurrets"),
        "wards_placed": item.get("wardsPlaced"),
        "wards_killed": item.get("wardsKilled"),
        "role": item.get("role"),
        "lane": item.get("lane"),
        "items": [item.get(f"item{i}") for i in range(7)],
        "challenges": item.get("challenges", {}),
    }
    if item.get("puuid") == requested_puuid:
        participant["is_requested_player"] = True
    return participant


def _required_string(payload: Any, key: str, label: str) -> str:
    value = payload.get(key) if isinstance(payload, dict) else None
    if not isinstance(value, str) or not value:
        raise RiotApiError(f"Riot response missing {label}")
    return value


def _safe_fields(payload: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    return {key: payload[key] for key in allowed if key in payload}


def _path(value: str) -> str:
    return quote(value, safe="")
