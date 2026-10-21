"""python -m brief --mode preview|test|send"""

import argparse
import logging

from .pipeline import run


def main() -> None:
    p = argparse.ArgumentParser(description="Build (and optionally email) the weekly research brief.")
    p.add_argument("--mode", choices=["preview", "test", "send"], default="preview",
                   help="preview: write preview/latest.html only; test: also email the first recipient; "
                        "send: email everyone and remember what was sent")
    p.add_argument("--since", help="start date YYYY-MM-DD (default: today minus lookback_days)")
    p.add_argument("--until", help="end date YYYY-MM-DD (default: today)")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    run(args.mode, args.since, args.until)


if __name__ == "__main__":
    main()
