"""
CLI entry point: run pipeline with config and topics paths.
"""

import argparse
import logging
import sys
from pathlib import Path


def setup_logging(verbose: bool = False) -> None:
    fmt = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format=fmt, datefmt="%Y-%m-%d %H:%M:%S", stream=sys.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description="arXiv Digest: daily paper summarization service")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.yaml"),
        help="Path to config.yaml",
    )
    parser.add_argument(
        "--topics",
        type=Path,
        default=Path("topics.yaml"),
        help="Path to topics.yaml",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)

    from .pipeline import run_pipeline

    try:
        run_pipeline(args.config, args.topics)
        return 0
    except FileNotFoundError as e:
        logging.getLogger(__name__).error("%s", e)
        return 1
    except ValueError as e:
        logging.getLogger(__name__).error("Config/topics error: %s", e)
        return 1
    except Exception as e:
        logging.getLogger(__name__).exception("Fatal: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
