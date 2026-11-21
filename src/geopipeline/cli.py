# geopipeline CLI
"""Thin entrypoint: satellite backfill and query, and crawl freshness build, promote, and demo."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from geopipeline.pipeline import (
    DEFAULT_DATA_ROOT,
    DEFAULT_FIELD_MASTER,
    DEFAULT_SCENE_CATALOG,
    run,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="geopipeline",
        description="Build Field-days from a Field master and Scene catalog.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Backfill Field-days from --from to --to")
    run_parser.add_argument(
        "--from", dest="start", required=True, help="Start date YYYY-MM-DD"
    )
    run_parser.add_argument(
        "--to", dest="end", required=True, help="End date YYYY-MM-DD"
    )
    run_parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    run_parser.add_argument("--field-master", type=Path, default=DEFAULT_FIELD_MASTER)
    run_parser.add_argument("--scene-catalog", type=Path, default=DEFAULT_SCENE_CATALOG)

    query_parser = sub.add_parser("query", help="Query the local Field-day Product")
    query_parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    query_parser.add_argument(
        "--sql", default=None, help="DuckDB SQL; default is a status rollup"
    )

    crawl_parser = sub.add_parser("crawl", help="Run offline crawl freshness comparisons")
    crawl_sub = crawl_parser.add_subparsers(dest="crawl_command", required=True)

    build_parser = crawl_sub.add_parser(
        "build",
        help="Build a candidate comparison into <runs-dir>/<UTC time>-<commit>/ (never publishes)",
    )
    build_parser.add_argument("--manifest", type=Path, required=True)
    build_parser.add_argument("--runs-dir", type=Path, required=True)

    promote_parser = crawl_sub.add_parser(
        "promote",
        help="Show a candidate beside the published comparison; publish it with --yes",
    )
    promote_parser.add_argument("run", type=Path, help="Run folder or releases/<commit> folder")
    promote_parser.add_argument("--publish-dir", type=Path, required=True)
    promote_parser.add_argument(
        "--yes", action="store_true", help="Replace the published comparison"
    )

    demo_parser = crawl_sub.add_parser(
        "demo", help="Build offline candidates for the handwritten and bundled Cloudflare fixtures"
    )
    demo_parser.add_argument("--output-dir", type=Path, default=Path("data/crawl-demo"))
    demo_parser.add_argument("--fixtures-root", type=Path, default=Path("fixtures"))

    args = parser.parse_args(argv)

    if args.command == "run":
        try:
            run(
                args.start,
                args.end,
                data_root=args.data_root,
                field_master=args.field_master,
                scene_catalog=args.scene_catalog,
            )
        except (ValueError, FileNotFoundError) as exc:
            print(exc, file=sys.stderr)
            return 1
        return 0

    if args.command == "crawl":
        return _crawl(args)

    from geopipeline.query import query_product

    try:
        print(query_product(args.data_root, sql=args.sql))
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


def _crawl(args: argparse.Namespace) -> int:
    from geopipeline.crawl.publish import build_run, promote, run_offline_demo

    try:
        if args.crawl_command == "build":
            print(f"Built candidate {build_run(args.manifest, args.runs_dir)}")
        elif args.crawl_command == "promote":
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
