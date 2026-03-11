"""Application entrypoint for headless runs, the console launcher, and the desktop UI."""

from __future__ import annotations

import logging
import sys

from config import ResearchConfig, build_arg_parser
from pipeline.pipeline_controller import PipelineController
from ui.launcher import LaunchMode, has_explicit_run_arguments, prompt_for_launch_mode
from utils.http import configure_http_logging


def configure_logging(level_name: str) -> None:
    """Configure process-wide logging to match the selected verbosity level."""

    level_map = {
        "quiet": logging.WARNING,
        "normal": logging.INFO,
        "verbose": logging.INFO,
        "debug": logging.DEBUG,
    }
    logging.basicConfig(
        level=level_map.get(level_name, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def _run_headless(args) -> int:
    """Execute the pipeline without the guided desktop workbench."""

    config = ResearchConfig.from_cli(args)
    configure_logging(config.verbosity)
    configure_http_logging(
        enabled=config.log_http_requests,
        log_payloads=config.log_http_payloads,
    )
    controller = PipelineController(config)
    result = controller.run()

    print("\nPipeline completed.")
    print(f"Run mode: {config.run_mode}")
    print(f"Verbosity: {config.verbosity}")
    print(f"Discovered records: {result['discovered_count']}")
    print(f"Deduplicated records: {result['deduplicated_count']}")
    print(f"Database records for this query: {result['database_count']}")
    output_labels = {
        "papers_csv": "CSV summary",
        "included_papers_csv": "Included papers CSV",
        "excluded_papers_csv": "Excluded papers CSV",
        "top_papers_json": "Top papers JSON",
        "citation_graph_json": "Citation graph JSON",
        "prisma_flow_json": "PRISMA flow JSON",
        "prisma_flow_md": "PRISMA flow Markdown",
        "included_papers_db": "Included papers DB",
        "excluded_papers_db": "Excluded papers DB",
        "review_summary_md": "Review summary",
    }
    for key, label in output_labels.items():
        if key in result:
            print(f"{label}: {result[key]}")
    return 0


def main() -> int:
    """Dispatch into UI, wizard, or direct CLI execution based on startup arguments."""

    parser = build_arg_parser()
    args = parser.parse_args()

    if args.ui:
        from ui.desktop_app import launch_desktop_app

        return launch_desktop_app(args)

    if args.wizard or has_explicit_run_arguments(args, sys.argv[1:]):
        return _run_headless(args)

    mode = prompt_for_launch_mode()
    if mode == LaunchMode.GUIDED_DESKTOP:
        from ui.desktop_app import launch_desktop_app

        return launch_desktop_app(args)
    if mode == LaunchMode.CLASSIC_WIZARD:
        return _run_headless(args)
    return 0


if __name__ == "__main__":  # pragma: no cover - direct module execution helper
    raise SystemExit(main())
