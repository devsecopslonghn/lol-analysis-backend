from rofl_analyzer.coaching import analyze_player_dataset, player_id_for_puuid
from rofl_analyzer.player_store import PlayerDatasetStore


def _dataset():
    def match(match_id, win, gold, damage, objective, kp, deaths):
        return {
            "match_id": match_id,
            "game_duration_seconds": 1800,
            "participants": [
                {"puuid": "me", "team_id": 100, "win": win, "champion_name": "Rengar", "lane": "JUNGLE",
                 "kills": kp, "deaths": deaths, "assists": kp, "gold_earned": gold, "total_minions_killed": 150,
                 "champion_damage": damage, "objective_damage": objective, "vision_score": 30},
                {"puuid": "ally", "team_id": 100, "win": win, "champion_name": "Ashe", "kills": 10, "deaths": 3,
                 "assists": 8, "gold_earned": 10000, "total_minions_killed": 180, "champion_damage": 30000,
                 "objective_damage": 9000, "vision_score": 20},
            ],
        }
    return {"player": {"game_name": "Me", "tag_line": "VN2", "puuid": "me"}, "matches": [
        match("win-1", True, 15000, 40000, 15000, 12, 2), match("win-2", True, 15000, 40000, 15000, 12, 2),
        match("loss-1", False, 10000, 15000, 3000, 3, 6), match("loss-2", False, 10000, 15000, 3000, 3, 6),
    ]}


def test_personal_analysis_emits_loss_path_and_evidence():
    analysis = analyze_player_dataset(_dataset())
    assert analysis["baseline"]["losses"] == 2
    assert analysis["loss_paths"][0]["steps"]
    assert any(item["metric"] == "damage_share" for item in analysis["recurring_mistakes"])
    assert "matches[loss-1].features" in analysis["loss_paths"][0]["steps"][0]["evidence"][0]


def test_player_store_uses_opaque_id_and_recomputes_analysis(tmp_path):
    dataset = _dataset()
    stored = PlayerDatasetStore(tmp_path).save(dataset)
    assert stored["player_id"] == player_id_for_puuid("me")
    loaded = PlayerDatasetStore(tmp_path).load(stored["player_id"])
    assert loaded is not None
    assert loaded["analysis"]["baseline"]["matches"] == 4
    second = dict(dataset)
    second["matches"] = [dataset["matches"][0]]
    PlayerDatasetStore(tmp_path).save(second)
    merged = PlayerDatasetStore(tmp_path).load(stored["player_id"])
    assert merged is not None
    assert len(merged["dataset"]["matches"]) == 4
