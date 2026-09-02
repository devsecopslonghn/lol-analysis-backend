import json
import struct

from rofl_analyzer.rofl import _champion_identity, _upgrade_report, parse_replay, write_report


def _replay(tmp_path):
    stats = [
        {
            "PUUID": "blue-player",
            "RIOT_ID_GAME_NAME": "Blue Player",
            "RIOT_ID_TAG_LINE": "VN",
            "SKIN": "Rengar",
            "TEAM": "100",
            "INDIVIDUAL_POSITION": "JUNGLE",
            "WIN": "Win",
            "LEVEL": "18",
            "CHAMPIONS_KILLED": "10",
            "NUM_DEATHS": "2",
            "ASSISTS": "0",
            "GOLD_EARNED": "15000",
            "MINIONS_KILLED": "100",
            "NEUTRAL_MINIONS_KILLED": "150",
            "TOTAL_DAMAGE_DEALT_TO_CHAMPIONS": "30000",
            "TIME_SPENT_DISCONNECTED": "0",
        },
        {
            "PUUID": "red-player",
            "RIOT_ID_GAME_NAME": "Red Player",
            "SKIN": "Karthus",
            "TEAM": "200",
            "INDIVIDUAL_POSITION": "JUNGLE",
            "WIN": "Fail",
            "LEVEL": "15",
            "CHAMPIONS_KILLED": "2",
            "NUM_DEATHS": "10",
            "ASSISTS": "4",
            "GOLD_EARNED": "9000",
            "MINIONS_KILLED": "40",
            "NEUTRAL_MINIONS_KILLED": "80",
            "TOTAL_DAMAGE_DEALT_TO_CHAMPIONS": "18000",
        },
    ]
    payload = json.dumps({"gameLength": 60000, "statsJson": json.dumps(stats)}).encode()
    raw = bytearray(b"RIOT\x02\x00\x01\x00\x00\x00\x00\x00\x00\x00\x0e16.17.810.4348")
    block = bytes([0x90, 0, 0, 0x2C, 0x02, 1, 0, 0, 0])
    raw.extend(struct.pack("<IBIII", 1, 0, 0x01000000, len(block), 0))
    raw.extend(block)
    raw.extend(b"\x00" * 256)
    raw.extend(payload)
    raw.extend(struct.pack("<I", len(payload)))
    path = tmp_path / "VN2-test.rofl"
    path.write_bytes(raw)
    return path


def test_parse_replay_aggregates_players(tmp_path):
    report = parse_replay(_replay(tmp_path))
    assert report["match_id"] == "VN2-test"
    assert report["teams"][0]["kills"] == 10
    assert report["teams"][1]["deaths"] == 10
    assert report["players"][0]["champion"] == "Rengar"
    assert report["players"][0]["champion_key"] == "Rengar"
    assert report["players"][0]["champion_id"] == 107
    assert report["players"][0]["derived"]["kill_participation"] == 1.0
    assert report["movement"]["status"] == "transport_only"
    assert report["transport"]["block_count"] == 1
    assert report["transport"]["opcode_observations"][0]["hex"] == "0x022c"


def test_write_report_uses_generic_player_artifact_names(tmp_path):
    source = _replay(tmp_path)
    target = write_report(source, tmp_path / "analysis")
    assert (target / "players.json").is_file()
    assert (target / "analysis_context.json").is_file()
    assert (target / "player_impacts.json").is_file()
    assert (target / "event_chains.json").is_file()
    assert (target / "transport.json").is_file()
    assert (target / "movement_transport.jsonl").is_file()
    assert len((target / "movement_transport.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    assert (target / "events.jsonl").is_file()
    assert not list(target.glob("*rengar*"))


def test_report_is_explicit_about_unverified_semantics(tmp_path):
    report = parse_replay(_replay(tmp_path))
    assert report["schema_version"] == 2
    assert report["analysis"]["method"] == "metadata_first"
    assert report["event_chains"]["shape"] == ["precondition", "action", "outcome", "conversion", "impact"]
    assert report["capabilities"]["movement_semantics"]["status"] == "unknown"
    assert report["capabilities"]["jungle_economy"]["status"] == "derived"
    assert report["analysis"]["facts"][0]["title"] == "Match duration"


def test_champion_identity_normalizes_apostrophes_and_display_names(tmp_path):
    assert _champion_identity("Kha'Zix") == (121, "Khazix", "Kha'Zix")
    assert _champion_identity("Khazix") == (121, "Khazix", "Kha'Zix")


def test_upgrade_report_backfills_fields_for_persisted_reports(tmp_path):
    report = parse_replay(_replay(tmp_path))
    report["players"][0].pop("champion_id")
    report["players"][0].pop("champion_key")
    report["capabilities"].pop("jungle_economy")

    upgraded = _upgrade_report(report)

    assert upgraded["players"][0]["champion_id"] == 107
    assert upgraded["players"][0]["champion_key"] == "Rengar"
    assert upgraded["capabilities"]["jungle_economy"]["status"] == "derived"
    assert upgraded["analysis"]["facts"][0]["title"] == "Match duration"
