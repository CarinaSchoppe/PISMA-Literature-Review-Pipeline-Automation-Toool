"""Application entrypoint for headless runs, the console launcher, and the desktop UI."""

from __future__ import annotations

import logging
import sys

from config import ResearchConfig, build_arg_parser
from pipeline.pipeline_controller import PipelineController
from ui.launcher import LaunchMode, has_explicit_run_arguments, prompt_for_launch_mode
from utils.http import configure_http_logging
from utils.logging_utils import configure_application_logging, verbosity_to_logging_level


def configure_logging(level_name: str, *, log_file_path: str | None = None) -> str | None:
    """Configure process-wide logging to match the selected verbosity level."""

    if log_file_path is None:
        logging.basicConfig(
            level=verbosity_to_logging_level(level_name),
            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        )
        return None
    return str(configure_application_logging(level_name, log_file_path=log_file_path))


def _run_headless(args) -> int:
    """Execute the pipeline without the guided desktop workbench."""

    config = ResearchConfig.from_cli(args)
    resolved_log_path = configure_logging(config.verbosity, log_file_path=str(config.log_file_path))
    configure_http_logging(
        enabled=config.log_http_requests,
        log_payloads=config.log_http_payloads,
    )
    controller = PipelineController(config)
    result = controller.run()

    print("\nPipeline execution summary")
    print("==========================")
    print("Pipeline completed successfully.")
    print(f"Run mode selected: {config.run_mode}")
    print(f"Logging verbosity: {config.verbosity}")
    if resolved_log_path:
        print(f"Persistent log file written to: {resolved_log_path}")
    print(f"Discovered records before deduplication: {result['discovered_count']}")
    print(f"Unique records after deduplication: {result['deduplicated_count']}")
    print(f"Records stored for the active query: {result['database_count']}")
    print()
    print("Generated pipeline artifacts")
    print("===========================")
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
