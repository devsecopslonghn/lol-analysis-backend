from __future__ import annotations

import argparse
import json
from pathlib import Path

from .rofl import ReplayParseError, parse_replay, write_report_data


def main() -> int:
    parser = argparse.ArgumentParser(prog="rofl-analyze")
    parser.add_argument("replay", type=Path)
    parser.add_argument("--output", type=Path, default=Path("analysis"))
    parser.add_argument("--json", action="store_true", help="print the generated report")
    args = parser.parse_args()
    try:
        report = parse_replay(args.replay)
        output_dir = write_report_data(report, args.output)
    except ReplayParseError as exc:
        parser.error(str(exc))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
