"""Command-line interface.

directory-pipeline demo                 # offline, end-to-end showcase
directory-pipeline run [--input F]      # reconcile a directory, emit JSON
directory-pipeline backtest             # measured precision / calibration
directory-pipeline dashboard            # how to launch the review UI
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import json
import sys
from pathlib import Path

from directory_pipeline import __version__, config
from directory_pipeline.audit import AuditLog
from directory_pipeline.backtest import run_backtest, run_scale_backtest
from directory_pipeline.ingest import load_directory
from directory_pipeline.logging_config import configure_logging
from directory_pipeline.models import RecommendedAction
from directory_pipeline.pipeline import Pipeline, PipelineResult
from directory_pipeline.triage import build_verify_queue

_ACTION_GLYPH = {
    RecommendedAction.NO_CHANGE: "=",
    RecommendedAction.AUTO_UPDATE: "+",
    RecommendedAction.HUMAN_REVIEW: "?",
    RecommendedAction.DISCARD: ".",
}


def _build_settings(args: argparse.Namespace) -> config.Settings:
    settings = config.Settings.from_env()
    if getattr(args, "offline", False):
        settings = dataclasses.replace(settings, offline=True)
    if getattr(args, "audit", None):
        settings = dataclasses.replace(settings, audit_path=Path(args.audit))
    return settings


def _print_result(result: PipelineResult) -> None:
    rec = result.recommendation
    glyph = _ACTION_GLYPH.get(rec.recommended_action, "?")
    print(
        f"\n[{glyph}] {result.record.provider_id}  "
        f"{result.record.provider_name or result.record.practice_name or ''}".rstrip()
    )
    print(
        f"    action     : {rec.recommended_action.value}  (overall {rec.overall_confidence:.2f})"
    )
    print(f"    reason     : {rec.reason}")
    for change in rec.changes:
        sources = ", ".join(change.supporting_sources)
        print(
            f"    change     : {change.field}: {change.old_value!r} -> {change.new_value!r}"
            f"  (conf {change.confidence_score:.2f}; {sources})"
        )
    for signal in result.signals:
        print(f"    signal     : {signal}")
    geo = result.geocode
    if geo is not None and geo.canonical:
        coords = f" @ {geo.lat:.4f},{geo.lon:.4f}" if geo.lat is not None else ""
        status = "validated" if geo.matched else "unverified"
        print(f"    geocode    : address {status} (US Census){coords}")


def _cmd_run(args: argparse.Namespace) -> int:
    settings = _build_settings(args)
    records = load_directory(args.input)
    if args.record:
        records = [r for r in records if r.provider_id == args.record]
        if not records:
            print(f"No record with provider_id={args.record!r}", file=sys.stderr)
            return 2

    audit = AuditLog(settings.audit_path)
    pipeline = Pipeline(settings, audit_log=audit)
    results = pipeline.run(records)

    payload = [r.recommendation.model_dump(mode="json") for r in results]
    if args.json:
        out = json.dumps(payload, indent=2)
        if args.output:
            Path(args.output).write_text(out, encoding="utf-8")
            print(f"Wrote {len(payload)} recommendations to {args.output}")
        else:
            print(out)
    else:
        for result in results:
            _print_result(result)
        _print_duplicates(pipeline, records)
        print(f"\nAudit log: {settings.audit_path}")
    return 0


def _print_triage(records: list) -> None:
    queue = build_verify_queue(records)
    print("\nVerify queue (triage — most at-risk first):")
    for ts in queue:
        reason = "; ".join(ts.reasons) or "within verification window"
        print(f"    [{ts.score:.2f}] {ts.provider_id}  ({reason})")


def _print_duplicates(pipeline: Pipeline, records: list) -> None:
    clusters = pipeline.duplicates(records)
    if not clusters:
        return
    print("\nDuplicate clusters detected:")
    for cluster in clusters:
        ids = ", ".join(cluster.provider_ids)
        print(
            f"    [{cluster.cluster_id}] {ids}  (score {cluster.match_score:.2f}; {cluster.reason})"
        )


def _cmd_demo(args: argparse.Namespace) -> int:
    args.offline = True
    settings = _build_settings(args)
    records = load_directory()

    print("=" * 70)
    print(" Provider & Practice Directory Update Pipeline - offline demo")
    print("=" * 70)
    print(f" {len(records)} sample records | sources: NPPES + CMS + web/board (fixtures)")

    _print_triage(records)

    audit = AuditLog(settings.audit_path)
    # Fresh audit log for the demo run.
    if settings.audit_path.exists():
        settings.audit_path.unlink()
    pipeline = Pipeline(settings, audit_log=audit)
    results = pipeline.run(records)
    for result in results:
        _print_result(result)
    _print_duplicates(pipeline, records)

    review_events = audit.review_queue()
    review_records = {e.provider_id for e in review_events}
    print(f"\nAudit log written to: {settings.audit_path}  ({len(audit.read_all())} events)")
    print(
        f"Records awaiting human review: {len(review_records)}  "
        f"({len(review_events)} field-level events)"
    )

    print("\n" + "-" * 70)
    report = run_backtest(settings=settings)
    print(report.render())
    print("-" * 70)
    print("Launch the human-review dashboard with:  streamlit run dashboard/app.py")
    return 0


def _cmd_triage(args: argparse.Namespace) -> int:
    records = load_directory(args.input)
    _print_triage(records)
    return 0


def _cmd_backtest(args: argparse.Namespace) -> int:
    if args.scale:
        print(
            f"Generating a {args.scale}-record synthetic two-snapshot world (seed {args.seed})..."
        )
        report = run_scale_backtest(args.scale, seed=args.seed)
    else:
        report = run_backtest(args.cases)
    print(report.render())
    return 0


def _cmd_dashboard(_: argparse.Namespace) -> int:
    print("Run the human-review dashboard with:\n")
    print("    pip install -e '.[dashboard]'")
    print("    directory-pipeline demo          # generate an audit/review queue")
    print("    streamlit run dashboard/app.py")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="directory-pipeline", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--log-level", default=None, help="DEBUG/INFO/WARNING/ERROR")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="reconcile a directory and emit recommendations")
    run.add_argument("--input", help="path to a directory JSON file (default: sample)")
    run.add_argument("--record", help="process only this provider_id")
    run.add_argument("--offline", action="store_true", help="use bundled fixtures, no network")
    run.add_argument("--json", action="store_true", help="emit JSON instead of a summary")
    run.add_argument("--output", help="write JSON to this file")
    run.add_argument("--audit", help="audit log path (default: audit_log.jsonl)")
    run.set_defaults(func=_cmd_run)

    demo = sub.add_parser("demo", help="run the full offline showcase")
    demo.add_argument("--audit", help="audit log path (default: audit_log.jsonl)")
    demo.set_defaults(func=_cmd_demo)

    tri = sub.add_parser("triage", help="rank records by re-verification risk")
    tri.add_argument("--input", help="path to a directory JSON file (default: sample)")
    tri.set_defaults(func=_cmd_triage)

    bt = sub.add_parser("backtest", help="measured precision/recall + calibration")
    bt.add_argument("--cases", help="path to a labeled backtest cases file")
    bt.add_argument(
        "--scale",
        type=int,
        default=0,
        metavar="N",
        help="generate an N-record synthetic two-snapshot world for a real curve",
    )
    bt.add_argument("--seed", type=int, default=0, help="RNG seed for --scale")
    bt.set_defaults(func=_cmd_backtest)

    dash = sub.add_parser("dashboard", help="how to launch the review dashboard")
    dash.set_defaults(func=_cmd_dashboard)
    return parser


def main(argv: list[str] | None = None) -> int:
    # Make console output robust on legacy code pages (e.g. Windows cp1252).
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(ValueError, OSError):
                reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.log_level)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
