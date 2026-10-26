"""python -m brief --mode preview|test|send"""

import argparse
import logging

from .pipeline import due, resend_latest, run, run_dives


def main() -> None:
    p = argparse.ArgumentParser(description="Build (and optionally email) the research brief.")
    p.add_argument("--mode", choices=["preview", "test", "send"], default="preview",
                   help="preview: write preview/latest.html only; test: email test_recipients with a [TEST] subject "
                        "and record nothing; send: email everyone and remember what was sent")
    p.add_argument("--since", help="start date YYYY-MM-DD (default: today minus lookback_days)")
    p.add_argument("--until", help="end date YYYY-MM-DD (default: today)")
    p.add_argument("--kind", choices=["brief", "dives", "both"], default="brief",
                   help="brief: the regular issue; dives: the deep-dive email on new reader requests "
                        "(skipped when there are none); both: dives first, then the brief")
    p.add_argument("--scheduled", action="store_true",
                   help="daily cron run: the brief is skipped unless send_every_days have passed since the last issue")
    p.add_argument("--resend-to", help="comma-separated addresses: send the last built email (preview/latest) "
                   "to them as it is and record its papers as sent; nothing else runs")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.resend_to:
        resend_latest([x.strip() for x in args.resend_to.split(",") if x.strip()])
        return
    if args.kind in ("dives", "both"):
        run_dives(args.mode)
    if args.kind in ("brief", "both") and not (args.scheduled and not due()):
        run(args.mode, args.since, args.until)


if __name__ == "__main__":
    main()
