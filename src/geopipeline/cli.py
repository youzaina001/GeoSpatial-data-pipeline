# geopipeline CLI
"""Thin entrypoint: run a date-range backfill or query the Product."""

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

    compare_parser = crawl_sub.add_parser(
        "compare", help="Compare two archived crawl samples defined by manifest.json"
    )
    compare_parser.add_argument("--manifest", type=Path, required=True)
    compare_parser.add_argument("--output", type=Path, required=True)
    compare_parser.add_argument("--summary-output", type=Path, default=None)
    compare_parser.add_argument("--current", type=Path, default=None)
    compare_parser.add_argument("--commit", default=None)

    demo_parser = crawl_sub.add_parser(
        "demo", help="Run the offline demo on handwritten and bundled Cloudflare fixtures"
    )
    demo_parser.add_argument("--output-dir", type=Path, default=Path("data/crawl-demo"))
    demo_parser.add_argument("--fixtures-root", type=Path, default=Path("fixtures"))
    demo_parser.add_argument("--commit", default=None)

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
        from geopipeline.crawl.publish import run_comparison, run_offline_demo

        try:
            if args.crawl_command == "compare":
                run_comparison(
                    args.manifest,
                    args.output,
                    summary_path=args.summary_output,
                    current_comparison_path=args.current,
                    producing_commit=args.commit,
                )
            else:
                hw_out, cf_out = run_offline_demo(
                    args.output_dir,
                    fixtures_root=args.fixtures_root,
                    producing_commit=args.commit,
                )
                print(f"Wrote {hw_out} and {cf_out}")
        except (ValueError, FileNotFoundError) as exc:
            print(exc, file=sys.stderr)
            return 1
        return 0

    from geopipeline.query import query_product

    try:
        print(query_product(args.data_root, sql=args.sql))
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
