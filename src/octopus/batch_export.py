"""Folder export with bounded conversion and non-overwriting publication."""

from __future__ import annotations

import argparse
import io
import os
import sys
import tempfile
import unicodedata
from pathlib import Path

MAX_FILES = 200
MAX_BYTES = 64 * 1024 * 1024


def _publish(targets: tuple[Path, ...], pages: tuple[bytes, ...]) -> None:
    """Publish one score only when every target is available; roll back owned files."""
    if not pages or len(pages) != len(targets) or sum(map(len, pages)) > MAX_BYTES:
        raise ValueError("empty or oversized export")
    if any(target.exists() or target.is_symlink() for target in targets):
        raise FileExistsError("an export destination already exists")
    staged: list[tuple[Path, Path]] = []
    published: list[tuple[Path, os.stat_result]] = []
    try:
        for target, data in zip(targets, pages, strict=True):
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
                temporary = Path(stream.name)
                staged.append((target, temporary))
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        for target, temporary in staged:
            os.link(temporary, target)
            published.append((target, temporary.stat()))
    except BaseException:
        for target, identity in reversed(published):
            try:
                current = target.lstat()
                if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                    target.unlink()
            except OSError:
                pass
        raise
    finally:
        for _, temporary in staged:
            temporary.unlink(missing_ok=True)


def _check_output_parents(selected: Path, destination: Path) -> None:
    parent = selected.parent
    while parent != destination:
        if parent.is_symlink():
            raise ValueError("export subfolders must not be symlinks")
        if destination not in parent.parents:
            raise ValueError("export path is outside the destination folder")
        parent = parent.parent
    if destination.is_symlink():
        raise ValueError("export folder must not be a symlink")


def _raster_jpg(pages: tuple[str, ...], dpi: int) -> tuple[bytes, ...]:
    from PIL import Image

    from .export.png_export import rasterize_pages

    outputs: list[bytes] = []
    for png in rasterize_pages(pages, dpi=dpi):
        with Image.open(io.BytesIO(png)) as image:
            out = io.BytesIO()
            image.convert("RGB").save(out, format="JPEG", quality=95, dpi=(dpi, dpi))
        outputs.append(out.getvalue())
    return tuple(outputs)


def run_batch_export(args: argparse.Namespace) -> int:
    from .export.pdf_export import build_pdf_pages
    from .export.png_export import rasterize_pages
    from .export.svg import normalize_source, render_score_pages, sanitize_export_pages
    from .jps import JpsDocument, jps_key, load_jps

    if (args.out is None) == (args.out_dir is None):
        print("Error: choose exactly one of --out or --out-dir", file=sys.stderr)
        return 2
    if args.out is not None and (args.format != "pdf" or args.out.suffix.lower() != ".pdf"):
        print("Error: --out is only for a combined .pdf file", file=sys.stderr)
        return 2
    if not args.input.is_dir():
        print("Error: input must be a folder", file=sys.stderr)
        return 2
    root = args.input.resolve()
    files = sorted(
        (
            path
            for path in (root.rglob("*") if args.recursive else root.iterdir())
            if path.suffix.lower() == ".jps" and path.is_file() and not path.is_symlink()
        ),
        key=lambda path: (
            path.relative_to(root).as_posix().casefold(),
            path.relative_to(root).as_posix(),
        ),
    )
    if not files or len(files) > MAX_FILES:
        print(f"Error: batch requires between 1 and {MAX_FILES} JPS files", file=sys.stderr)
        return 2
    destination = (args.out if args.out is not None else args.out_dir).absolute()
    # Reject a destination symlink before resolution, and reserve names before writing anything.
    if destination.is_symlink() or (args.out is not None and destination.exists()):
        print("Error: export destination already exists or is a symlink", file=sys.stderr)
        return 2
    if args.out_dir is not None and destination.exists() and not destination.is_dir():
        print("Error: --out-dir must be a folder", file=sys.stderr)
        return 2
    if args.out_dir is not None:
        reserved = [
            unicodedata.normalize(
                "NFC", path.relative_to(root).with_suffix("." + args.format).as_posix()
            ).casefold()
            for path in files
        ]
        if len(set(reserved)) != len(reserved):
            print(
                "Error: input names would collide on a case-insensitive filesystem", file=sys.stderr
            )
            return 2
    failures = success = 0
    combined: list[str] = []
    published_names: set[str] = set()
    for source_path in files:
        try:
            source = load_jps(source_path)
            snapshot = JpsDocument(
                path=Path(source_path.name),
                key=jps_key(source_path.name),
                code=source.code,
                original_code=source.code,
                custom_code=source.custom_code,
                page_config=source.page_config,
                record={},
                json_wrapped=False,
                encoding_repaired=False,
            )
            model = normalize_source(snapshot)
            rendered_pages, custom_markup_omitted = render_score_pages(model, source.page_config)
            pages = sanitize_export_pages(tuple(rendered_pages))
            if custom_markup_omitted:
                print(
                    f"Warning: {source_path.relative_to(root)}: unsafe custom SVG omitted",
                    file=sys.stderr,
                )
            if args.out is not None:
                if len(combined) + len(pages) > 200:
                    raise ValueError("combined PDF exceeds the 200-page limit")
                combined.extend(pages)
            else:
                relative = source_path.relative_to(root).with_suffix("." + args.format)
                selected = destination / relative
                _check_output_parents(selected, destination)
                data: tuple[bytes, ...]
                if args.format == "pdf":
                    data = (build_pdf_pages(pages)[0],)
                elif args.format == "png":
                    data = rasterize_pages(pages, dpi=args.dpi)
                elif args.format == "jpg":
                    data = _raster_jpg(pages, args.dpi)
                else:
                    data = tuple(page.encode("utf-8") for page in pages)
                targets = (
                    (selected,)
                    if len(data) == 1
                    else tuple(
                        selected.with_name(f"{selected.stem}_page_{index:03}.{args.format}")
                        for index in range(1, len(data) + 1)
                    )
                )
                target_names = {
                    unicodedata.normalize(
                        "NFC", target.relative_to(destination).as_posix()
                    ).casefold()
                    for target in targets
                }
                if len(target_names) != len(targets) or target_names & published_names:
                    raise ValueError(
                        "generated export names would collide on a case-insensitive filesystem"
                    )
                _publish(targets, data)
                published_names.update(target_names)
            success += 1
            verb = "Prepared" if args.out is not None else "Exported"
            print(f"{verb}: {source_path.relative_to(root)} ({len(pages)} pages)")
        except Exception as exc:
            failures += 1
            print(f"Error: {source_path.relative_to(root)}: {exc}", file=sys.stderr)
    if args.out is not None and combined:
        try:
            _publish((destination,), (build_pdf_pages(tuple(combined))[0],))
            print(f"Written: {destination} ({len(combined)} pages)")
        except Exception as exc:
            print(f"Error: combined PDF: {exc}", file=sys.stderr)
            return 1
    print(f"Batch: {success} scores exported; {failures} failed")
    return 1 if failures else 0
