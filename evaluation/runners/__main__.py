"""CLI wrapper: ``python -m evaluation.runners.run_eval --config ...``."""

from __future__ import annotations

import argparse
from pathlib import Path

from evaluation.runners.run_eval import execute


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a controlled evaluation on frozen evidence.")
    parser.add_argument("--config", required=True, help="Path to an EvalConfig JSON file (e.g. evaluation/configs/fixture.json).")
    parser.add_argument("--dataset", help="Override dataset JSON path (defaults to evaluation/datasets/<dataset>.json).")
    parser.add_argument("--output-root", help="Override results root (defaults to evaluation/results).")
    parser.add_argument("--run-id", help="Override run_id (defaults to <system>_<dataset>_<date>_<seed>[_<short-sha>]).")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result = execute(
        config_path=Path(args.config),
        dataset_path=Path(args.dataset) if args.dataset else None,
        output_root=Path(args.output_root) if args.output_root else None,
        run_id_override=args.run_id,
    )
    print(f"run_id={result['run_id']}")
    print(f"output=evaluation/results/{result['run_id']}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
