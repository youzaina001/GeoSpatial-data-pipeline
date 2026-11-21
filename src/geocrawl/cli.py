# geocrawl CLI
"""Thin entrypoint: crawl freshness build, promote, and demo."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="geocrawl",
        description="Measure how much new prose a later web crawl adds.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    build_parser = sub.add_parser(
        "build",
        help="Build a candidate comparison into <runs-dir>/<UTC time>-<commit>/ (never publishes)",
    )
    build_parser.add_argument("--manifest", type=Path, required=True)
    build_parser.add_argument("--runs-dir", type=Path, required=True)

    promote_parser = sub.add_parser(
        "promote",
        help="Show a candidate beside the published comparison; publish it with --yes",
    )
    promote_parser.add_argument("run", type=Path, help="Run folder or releases/<commit> folder")
    promote_parser.add_argument("--publish-dir", type=Path, required=True)
    promote_parser.add_argument(
        "--yes", action="store_true", help="Replace the published comparison"
    )

    demo_parser = sub.add_parser(
        "demo", help="Build offline candidates for the handwritten and bundled Cloudflare fixtures"
    )
    demo_parser.add_argument("--output-dir", type=Path, default=Path("data/demo"))
    demo_parser.add_argument("--fixtures-root", type=Path, default=Path("fixtures"))

    return _run(parser.parse_args(argv))


def _run(args: argparse.Namespace) -> int:
    from geocrawl.publish import build_run, promote, run_offline_demo

    try:
        if args.command == "build":
            print(f"Built candidate {build_run(args.manifest, args.runs_dir)}")
        elif args.command == "promote":
            result = promote(args.run, args.publish_dir, confirm=args.yes)
            print(result.preview)
            if not result.published:
                print("Not published. Re-run with --yes to replace the published comparison.", file=sys.stderr)
                return 1
            print(f"Published {args.publish_dir / 'comparison.json'}")
        else:
            hw_run, cf_run = run_offline_demo(args.output_dir, fixtures_root=args.fixtures_root)
            print(f"Built candidates {hw_run} and {cf_run}")
    except (ValueError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
