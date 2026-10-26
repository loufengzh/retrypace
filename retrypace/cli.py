"""Command-line interface; reports go to stdout, diagnostics to stderr."""
import argparse
import csv
import json
import sys
from dataclasses import replace
from . import __version__
from .model import Config, STRATEGIES, compare, simulate

MAX_CONFIG_BYTES = 64 * 1024


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON configuration key")
        result[key] = value
    return result


def _invalid_constant(_):
    raise ValueError("nonstandard JSON numeric constant")


def _load_config(path):
    # Bound the bytes before decoding or parsing, including JSON whitespace.
    with open(path, "rb") as source:
        raw = source.read(MAX_CONFIG_BYTES + 1)
    if len(raw) > MAX_CONFIG_BYTES:
        raise ValueError("configuration exceeds 64 KiB")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_constant=_invalid_constant)
    except RecursionError as exc:
        raise ValueError("configuration nesting exceeds the supported limit") from exc
    return Config.from_dict(value)


def _positive(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be nonnegative")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description="Audit deterministic worst-case retry schedules")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--config", help="JSON configuration file (defaults if omitted)")
    parser.add_argument("--strategy", choices=STRATEGIES)
    parser.add_argument("--compare", action="store_true", help="compare all strategies")
    parser.add_argument("--format", choices=("json", "csv"), default="json")
    parser.add_argument("--summary-only", action="store_true", help="omit per-attempt events")
    parser.add_argument("--max-peak-concurrency", type=_positive, help="fail if peak exceeds value")
    parser.add_argument("--max-window-starts", type=_positive, help="fail if sliding-window starts exceed value")
    args = parser.parse_args(argv)
    if args.compare and args.strategy:
        parser.error("--compare and --strategy are mutually exclusive")
    if args.format == "csv" and (args.compare or args.summary_only):
        parser.error("CSV exports events; cannot combine with --compare or --summary-only")
    try:
        if args.config is not None:
            config = _load_config(args.config)
        else:
            config = Config()
        if args.strategy:
            config = replace(config, strategy=args.strategy)
        report = compare(config) if args.compare else simulate(config, include_events=not args.summary_only)
    except (OSError, ValueError, TypeError) as error:
        print(f"retrypace: {error}", file=sys.stderr)
        return 1
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    else:
        writer = csv.DictWriter(sys.stdout, fieldnames=("client", "attempt", "start_ms", "end_ms"))
        writer.writeheader()
        writer.writerows(report["events"])
    reports = report.values() if args.compare else [report]
    failed = False
    for result in reports:
        for key, threshold in (("peak_concurrency", args.max_peak_concurrency),
                               ("peak_window_starts", args.max_window_starts)):
            observed = result["summary"][key]
            if threshold is not None and observed > threshold:
                print(f"retrypace: {result['config']['strategy']}: {key}={observed} exceeds {threshold}", file=sys.stderr)
                failed = True
    return 2 if failed else 0
