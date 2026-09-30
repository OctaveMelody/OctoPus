"""Reproduce pinned release fonts, or verify committed assets without network access.

Regenerate with uv --no-project and pinned fonttools/zstandard; see the font asset README.
Verify: python scripts/prepare_fonts.py --verify
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import tarfile
import urllib.request
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FONTS = ROOT / "src/octopus/assets/fonts"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(url: str, expected: str, target: Path) -> bytes:
    if target.is_file():
        data = target.read_bytes()
    else:
        with urllib.request.urlopen(url, timeout=120) as response:
            data = response.read()
    if digest(data) != expected:
        raise ValueError(f"font source checksum mismatch: {target.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return data


def deb_files(data: bytes) -> dict[str, bytes]:
    """Read selected files from a Debian ar/tar archive without a platform CLI."""
    if not data.startswith(b"!<arch>\n"):
        raise ValueError("invalid font package archive")
    offset = 8
    while offset + 60 <= len(data):
        header = data[offset:offset + 60]
        size = int(header[48:58])
        name = header[:16].decode("ascii").strip().rstrip("/")
        start = offset + 60
        if name.startswith("data.tar"):
            payload = data[start:start + size]
            if name.endswith(".zst"):
                import zstandard

                with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(payload)) as reader:
                    payload = reader.read()
            with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as tar:
                wanted = {
                    "LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf",
                    "LiberationSans-Italic.ttf", "LiberationSans-BoldItalic.ttf", "copyright",
                }
                result = {}
                for member in tar.getmembers():
                    filename = member.name.rsplit("/", 1)[-1]
                    if member.isfile() and filename in wanted:
                        extracted = tar.extractfile(member)
                        if extracted is not None:
                            result[filename] = extracted.read()
                if result.keys() != wanted:
                    raise ValueError("font package is missing required files")
                return result
        offset = start + size + size % 2
    raise ValueError("font package has no data archive")


def verify() -> None:
    manifest = json.loads((FONTS / "manifest.json").read_text(encoding="utf-8"))
    expected = {face["file"] for face in manifest["faces"]}
    if expected != {path.name for path in FONTS.glob("*.ttf")}:
        raise ValueError("release font inventory does not match the manifest")
    for entry in [*manifest["faces"], *manifest["licenses"]]:
        if digest((FONTS / entry["file"]).read_bytes()) != entry["sha256"]:
            raise ValueError(f"release asset checksum mismatch: {entry['file']}")
    print(f"Verified {len(expected)} release font faces and their licenses")


def prepare(cache: Path) -> None:
    import fontTools
    from fontTools.ttLib import TTFont
    from fontTools.varLib.instancer import instantiateVariableFont

    recipe = json.loads((FONTS / "sources.json").read_text(encoding="utf-8"))
    if version("zstandard") != recipe["zstandard_version"]:
        raise ValueError(f"zstandard {recipe['zstandard_version']} is required")
    if fontTools.__version__ != recipe["fonttools_version"]:
        raise ValueError(f"fontTools {recipe['fonttools_version']} is required")
    faces = []
    for source in recipe["sources"]:
        data = fetch(source["url"], source["sha256"], cache / source["cache_file"])
        if source["format"] == "variable-ttf":
            fetch(source["license_url"], source["license_sha256"], FONTS / source["license_file"])
            sans = source["name"] == "notosanssc"
            family = "Noto Sans SC" if sans else "Noto Serif SC"
            prefix = "NotoSansSC" if sans else "NotoSerifSC"
            for weight, label in [(400, "Regular"), (700, "Bold")]:
                variable = TTFont(io.BytesIO(data), recalcTimestamp=False)
                font = instantiateVariableFont(variable, {"wght": weight})
                font["head"].created = font["head"].modified = 0
                # Keep the upstream family; these fonts do not use the reserved name Source.
                for name_id, value in [(1, family), (2, label), (4, f"{family} {label}"),
                                       (6, f"{prefix}-{label}"), (16, family), (17, label)]:
                    font["name"].removeNames(nameID=name_id)
                    font["name"].setName(value, name_id, 3, 1, 1033)
                filename = f"{prefix}-{label}.ttf"
                font.save(FONTS / filename)
                faces.append({"file": filename, "family": family,
                              "weight": "bold" if weight == 700 else "normal", "style": "normal",
                              "source": source["name"], "instance_weight": weight})
        else:
            package = deb_files(data)
            (FONTS / source["license_file"]).write_bytes(package.pop("copyright"))
            for filename, binary in sorted(package.items()):
                (FONTS / filename).write_bytes(binary)
                faces.append({"file": filename, "family": "Liberation Sans",
                              "weight": "bold" if "Bold" in filename else "normal",
                              "style": "italic" if "Italic" in filename else "normal",
                              "source": source["name"]})
    for face in faces:
        face["sha256"] = digest((FONTS / face["file"]).read_bytes())
    licenses = [{"file": source["license_file"],
                 "sha256": digest((FONTS / source["license_file"]).read_bytes())}
                for source in recipe["sources"]]
    coverage = {}
    for family in sorted({face["family"] for face in faces}):
        sets = [set(TTFont(FONTS / face["file"]).getBestCmap())
                for face in faces if face["family"] == family]
        codes = sorted(set.intersection(*sets))
        ranges = []
        for code in codes:
            if ranges and code == ranges[-1][1] + 1:
                ranges[-1][1] = code
            else:
                ranges.append([code, code])
        coverage[family] = ranges
    manifest = {"coverage": coverage, "license": "OFL-1.1",
                "fonttools_version": fontTools.__version__,
                "faces": faces, "licenses": licenses}
    (FONTS / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    verify()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--cache", type=Path, default=ROOT / "build/font-sources")
    args = parser.parse_args()
    if args.verify:
        verify()
    else:
        prepare(args.cache)


if __name__ == "__main__":
    main()
