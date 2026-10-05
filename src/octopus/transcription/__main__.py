"""Run the image/PDF transcription draft from the command line."""

from __future__ import annotations

import argparse
from itertools import combinations
from pathlib import Path

from . import transcribe


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="PNG, JPG, JPEG or PDF score")
    parser.add_argument("--out", required=True, type=Path, help="reviewable JPS draft")
    parser.add_argument(
        "--issues", type=Path, help="review issues JSON beside the draft by default"
    )
    parser.add_argument(
        "--ocr-backend", choices=(
            "rapidocr-onnxruntime", "rapidocr-onnx", "rapidocr-openvino",
        ),
        default="rapidocr-onnxruntime", help="OCR backend (default: rapidocr-onnxruntime)",
    )
    args = parser.parse_args()
    issue_path = args.issues or args.out.with_suffix(".issues.json")
    for first, second in combinations((args.input, args.out, issue_path), 2):
        if first.resolve() == second.resolve() or (
            first.exists() and second.exists() and first.samefile(second)
        ):
            parser.error("input, draft and review issues must be distinct files")
    draft = (transcribe(args.input) if args.ocr_backend == "rapidocr-onnxruntime"
             else transcribe(args.input, ocr_backend=args.ocr_backend))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    issue_path.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(draft.jps, encoding="utf-8")
    issue_path.write_text(draft.issue_json(), encoding="utf-8")
    row_count = sum(line.startswith("Q") for line in draft.jps.splitlines())
    print(f"{args.out}: {row_count} draft Q rows")
    print(f"Review issues: {issue_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
