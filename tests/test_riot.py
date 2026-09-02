from rofl_analyzer.riot_api import RiotApiClient


def _match(match_id: str, requested: bool = True) -> dict:
    puuid = "player-puuid" if requested else "other-puuid"
    return {
        "metadata": {"matchId": match_id},
        "info": {
            "gameCreation": 1725000000000,
            "gameDuration": 1800,
            "gameVersion": "16.17.1",
            "queueId": 420,
            "mapId": 11,
            "gameMode": "CLASSIC",
            "teams": [{"teamId": 100, "win": True, "objectives": {"dragon": {"kills": 2}}}],
            "participants": [
                {
                    "puuid": puuid,
                    "riotIdGameName": "Test Player",
                    "riotIdTagline": "VN2",
                    "championId": 107,
                    "championName": "Rengar",
                    "teamId": 100,
                    "win": True,
                    "kills": 8,
                    "deaths": 2,
                    "assists": 6,
                    "goldEarned": 14000,
                    "totalMinionsKilled": 120,
                    "neutralMinionsKilled": 80,
                    "totalDamageDealtToChampions": 28000,
                    "damageDealtToObjectives": 5000,
                    "visionScore": 30,
                    "role": "NONE",
                    "lane": "JUNGLE",
                    "item0": 1,
                }
            ],
        },
    }


def test_collect_player_history_normalizes_match_and_chart(monkeypatch):
    def fake_get(self, routing, path, params=None):
        if path.startswith("/riot/account"):
            return {"gameName": "Test Player", "tagLine": "VN2", "puuid": "player-puuid"}
        if path.startswith("/lol/summoner"):
            return {"id": "summoner-id", "summonerLevel": 100}
        if path.startswith("/lol/league"):
            return [{"queueType": "RANKED_SOLO_5x5", "tier": "GOLD"}]
        if path.endswith("/ids"):
            assert params == {"start": 0, "count": 2}
            return ["VN2_1", "VN2_2"]
        return _match(path.rsplit("/", 1)[-1])

    monkeypatch.setattr(RiotApiClient, "_get", fake_get)
    dataset = RiotApiClient("test-key").collect_player_history("Test Player", "VN2", count=2)

    assert dataset["dataset_type"] == "riot_player_match_history"
    assert dataset["source"]["regional_routing"] == "sea"
    assert len(dataset["matches"]) == 2
    assert dataset["matches"][0]["participants"][0]["champion_name"] == "Rengar"
    assert dataset["chart_data"]["series"][0]["kills"] == 8


def test_client_requires_api_key():
    try:
        RiotApiClient("")
    except Exception as exc:
        assert "RIOT_API_KEY" in str(exc)
    else:
        raise AssertionError("missing Riot key should fail closed")
