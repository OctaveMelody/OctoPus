"""Command-line entry point for JPS parsing, normalization, and SVG rendering."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .model import model_to_dict, normalize_jps
from .parser import document_to_dict, parse_jps
from .render.export import DEFAULT_EXPORT_MODE, EXPORT_MODES
from .render.output import write_utf8_text
from .render.svg import render_jps, render_score_model

_AUDIT_COMMANDS = frozenset(
    {"inspect-corpus", "compare-svg", "compare-svg-body", "audit-corpus"}
)


def add_runtime_parsers(subparsers: argparse._SubParsersAction) -> None:
    parse_parser = subparsers.add_parser(
        "parse", help="parse a JPS file into recovery-oriented AST JSON"
    )
    parse_parser.add_argument("input", type=Path)
    parse_parser.add_argument("--json", dest="json_path", type=Path)
    parse_parser.add_argument(
        "--diagnostics", action="store_true", help="include source provenance in JSON"
    )
    normalize_parser = subparsers.add_parser(
        "normalize", help="normalize a JPS file into score-model JSON"
    )
    normalize_parser.add_argument("input", type=Path)
    normalize_parser.add_argument("--json", dest="json_path", type=Path)
    normalize_parser.add_argument(
        "--diagnostics", action="store_true", help="include source provenance in JSON"
    )
    render_parser = subparsers.add_parser(
        "render", help="render a JPS file to SVG HTML pages"
    )
    render_parser.add_argument("input", type=Path)
    render_parser.add_argument(
        "--export-mode",
        choices=EXPORT_MODES,
        default=DEFAULT_EXPORT_MODE,
        help=(
            "SVG serialization profile (safe-source strips custom markup; "
            "browser-dom uses Chromium)"
        ),
    )
    render_parser.add_argument("--title", default=None, help="safe HTML title (default: score)")
    render_parser.add_argument("--out", type=Path, default=None, help="output single SVG file")
    render_parser.add_argument(
        "--out-dir", type=Path, default=None, help="output directory for multi-page HTML files"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="octopus")
    add_runtime_parsers(parser.add_subparsers(dest="command", required=True))
    return parser


def run_runtime_command(args: argparse.Namespace) -> int:
    if args.command == "parse":
        output = json.dumps(
            document_to_dict(parse_jps(args.input), include_diagnostics=args.diagnostics),
            ensure_ascii=False,
            indent=2,
        )
        if args.json_path:
            args.json_path.parent.mkdir(parents=True, exist_ok=True)
            write_utf8_text(args.json_path, output + "\n")
        else:
            sys.stdout.buffer.write((output + "\n").encode("utf-8"))
        return 0
    if args.command == "normalize":
        output = json.dumps(
            model_to_dict(normalize_jps(args.input), include_diagnostics=args.diagnostics),
            ensure_ascii=False,
            indent=2,
        )
        if args.json_path:
            args.json_path.parent.mkdir(parents=True, exist_ok=True)
            write_utf8_text(args.json_path, output + "\n")
        else:
            sys.stdout.buffer.write((output + "\n").encode("utf-8"))
        return 0
    if args.out is not None:
        pages = render_score_model(normalize_jps(args.input), export_mode=args.export_mode)
        if len(pages) == 1:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            write_utf8_text(args.out, pages[0])
            print(f"Written: {args.out}")
        else:
            print(
                f"Error: {len(pages)} pages produced; use --out-dir for multi-page",
                file=sys.stderr,
            )
            return 1
    elif args.out_dir is not None:
        render_jps(
            normalize_jps(args.input),
            args.out_dir,
            export_mode=args.export_mode,
            title=args.title,
        )
        print(f"Rendered to: {args.out_dir}")
    else:
        print("Error: --out or --out-dir is required", file=sys.stderr)
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] in _AUDIT_COMMANDS:
        try:
            from audit.cli import main as audit_main
        except ModuleNotFoundError as exc:
            if exc.name != "audit":
                raise
            print(
                "Audit commands require a repository checkout or the separate audit package.",
                file=sys.stderr,
            )
            return 2
        return audit_main(arguments)

    args = build_parser().parse_args(arguments)
    return run_runtime_command(args)


if __name__ == "__main__":
    raise SystemExit(main())
