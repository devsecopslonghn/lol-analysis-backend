"""Atomic JSON persistence for MVP player datasets on the existing PVC."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .coaching import analyze_player_dataset, player_id_for_puuid
from .riot_api import build_history_chart


class PlayerDatasetStore:
    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root or os.getenv("RIOT_DATA_ROOT", "/var/lib/rofl-analysis/riot"))

    def save(self, dataset: dict[str, Any]) -> dict[str, Any]:
        player = dataset.get("player") if isinstance(dataset.get("player"), dict) else {}
        puuid = str(player.get("puuid") or "")
        if not puuid:
            raise ValueError("dataset player.puuid is required")
        player_id = player_id_for_puuid(puuid)
        existing_path = self.root / "players" / player_id / "dataset.json"
        if existing_path.is_file():
            try:
                existing = _read_json(existing_path)
                existing_matches = [item for item in existing.get("matches", []) if isinstance(item, dict)]
                incoming_matches = [item for item in dataset.get("matches", []) if isinstance(item, dict)]
                by_id = {str(item.get("match_id")): item for item in existing_matches if item.get("match_id")}
                by_id.update({str(item.get("match_id")): item for item in incoming_matches if item.get("match_id")})
                dataset = dict(dataset)
                dataset["matches"] = sorted(by_id.values(), key=lambda item: item.get("game_creation_ms") or 0, reverse=True)
                dataset["chart_data"] = build_history_chart(dataset["matches"], puuid=puuid)
            except (OSError, ValueError, TypeError):
                # A corrupt/old cache must not prevent a fresh collection.
                pass
        target = self.root / "players" / player_id
        target.mkdir(parents=True, exist_ok=True)
        analysis = analyze_player_dataset(dataset)
        _atomic_json(target / "dataset.json", dataset)
        _atomic_json(target / "analysis.json", analysis)
        _atomic_json(target / "profile.json", {"player_id": player_id, "player": player, "source": dataset.get("source")})
        return {"player_id": player_id, "dataset": dataset, "analysis": analysis}

    def load(self, player_id: str) -> dict[str, Any] | None:
        if not player_id or Path(player_id).name != player_id:
            return None
        path = self.root / "players" / player_id / "dataset.json"
        if not path.is_file():
            return None
        dataset = _read_json(path)
        puuid = str(dataset.get("player", {}).get("puuid") or "")
        if player_id_for_puuid(puuid) != player_id:
            return None
        return {"player_id": player_id, "dataset": dataset, "analysis": analyze_player_dataset(dataset)}


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("stored dataset is not an object")
    return payload
