from __future__ import annotations

import argparse
import json
from pathlib import Path

from .riot_api import RiotApiClient, RiotApiError


def main() -> int:
    parser = argparse.ArgumentParser(prog="riot-collect")
    parser.add_argument("game_name")
    parser.add_argument("tag_line")
    parser.add_argument("--platform", default="vn2")
    parser.add_argument("--regional", default="sea")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--output", type=Path, default=Path("riot-dataset.json"))
    args = parser.parse_args()
    try:
        dataset = RiotApiClient.from_env(platform=args.platform, regional=args.regional).collect_player_history(
            args.game_name,
            args.tag_line,
            start=args.start,
            count=args.count,
        )
    except RiotApiError as exc:
        parser.error(str(exc))
    args.output.write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
