#!/usr/bin/env python3
"""Validate a Xiaohongshu carousel folder without third-party dependencies."""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        if handle.read(8) != PNG_SIGNATURE:
            raise ValueError("not a PNG file")
        length = struct.unpack(">I", handle.read(4))[0]
        chunk_type = handle.read(4)
        if chunk_type != b"IHDR" or length < 8:
            raise ValueError("missing PNG IHDR chunk")
        width, height = struct.unpack(">II", handle.read(8))
    return width, height


def validate_svg(path: Path, width: int, height: int) -> list[str]:
    errors: list[str] = []
    try:
        source = path.read_text(encoding="utf-8")
        root = ET.fromstring(source)
    except (OSError, UnicodeError, ET.ParseError) as exc:
        return [f"{path.name}: invalid SVG: {exc}"]

    if root.tag.rsplit("}", 1)[-1] != "svg":
        errors.append(f"{path.name}: root element is not svg")
    view_box = root.attrib.get("viewBox", "")
    try:
        values = [float(value) for value in re.split(r"[\s,]+", view_box.strip())]
    except ValueError:
        values = []
    if values != [0.0, 0.0, float(width), float(height)]:
        errors.append(
            f'{path.name}: expected viewBox="0 0 {width} {height}", found {view_box!r}'
        )
    forbidden_tex = sorted(set(re.findall(r"\\(?:frac|sqrt|Rightarrow|Leftarrow|mathbb|begin|end)\b", source)))
    if forbidden_tex:
        errors.append(f"{path.name}: visible SVG may contain raw TeX commands: {', '.join(forbidden_tex)}")
    if re.search(r"<(?:script|foreignObject)\b", source, re.IGNORECASE):
        errors.append(f"{path.name}: script and foreignObject are not allowed")
    if re.search(r"(?:href|xlink:href)\s*=\s*[\"']https?://", source, re.IGNORECASE):
        errors.append(f"{path.name}: external raster or font references are not reproducible")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument("--count", type=int, default=7)
    parser.add_argument("--width", type=int, default=1080)
    parser.add_argument("--height", type=int, default=1440)
    parser.add_argument(
        "--require-manifest",
        action="store_true",
        help="require source/slide-manifest.json and validate SVG/hybrid sources",
    )
    args = parser.parse_args()

    errors: list[str] = []
    folder = args.folder
    if not folder.is_dir():
        print(f"ERROR: folder does not exist: {folder}", file=sys.stderr)
        return 1

    images = sorted(folder.glob("[0-9][0-9]-*.png"))
    expected_prefixes = [f"{number:02d}-" for number in range(1, args.count + 1)]
    actual_prefixes = {path.name[:3] for path in images}
    for prefix in expected_prefixes:
        if prefix not in actual_prefixes:
            errors.append(f"missing slide with prefix {prefix}")

    if len(images) != args.count:
        errors.append(f"expected {args.count} PNG slides, found {len(images)}")

    for path in images:
        try:
            width, height = png_size(path)
        except (OSError, ValueError) as exc:
            errors.append(f"{path.name}: {exc}")
            continue
        if (width, height) != (args.width, args.height):
            errors.append(
                f"{path.name}: expected {args.width}x{args.height}, found {width}x{height}"
            )
        else:
            print(f"OK {path.name}: {width}x{height}")

    manifest_path = folder / "source" / "slide-manifest.json"
    if args.require_manifest and not manifest_path.is_file():
        errors.append("missing source/slide-manifest.json")
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"source/slide-manifest.json: {exc}")
            manifest = None
        if manifest is not None:
            valid_post_types = {"知识点型", "解题方法型", "题型型"}
            if manifest.get("postType") not in valid_post_types:
                errors.append("source/slide-manifest.json: postType must be 知识点型、解题方法型 or 题型型")
            slides = manifest.get("slides")
            if not isinstance(slides, list) or len(slides) != args.count:
                errors.append(f"source/slide-manifest.json: expected {args.count} slide entries")
            else:
                manifest_pngs: list[str] = []
                referenced_svgs: set[Path] = set()
                for index, slide in enumerate(slides):
                    if not isinstance(slide, dict):
                        errors.append(f"source/slide-manifest.json: slides[{index}] must be an object")
                        continue
                    png_name = slide.get("png")
                    mode = slide.get("mode")
                    if not isinstance(png_name, str) or Path(png_name).name != png_name or not png_name.endswith(".png"):
                        errors.append(f"source/slide-manifest.json: slides[{index}].png must name a root-level PNG")
                    else:
                        manifest_pngs.append(png_name)
                    if mode not in {"svg", "hybrid", "imagegen"}:
                        errors.append(f"source/slide-manifest.json: slides[{index}].mode is invalid")
                        continue
                    if mode in {"svg", "hybrid"}:
                        source_name = slide.get("source")
                        if not isinstance(source_name, str) or Path(source_name).name != source_name or not source_name.endswith(".svg"):
                            errors.append(f"source/slide-manifest.json: {png_name or index} requires a direct SVG source")
                            continue
                        source_path = manifest_path.parent / source_name
                        referenced_svgs.add(source_path)
                        if not source_path.is_file():
                            errors.append(f"missing SVG source for {png_name}: source/{source_name}")
                        else:
                            errors.extend(validate_svg(source_path, args.width, args.height))
                            print(f"OK source/{source_name}: SVG source for {png_name}")
                actual_names = sorted(path.name for path in images)
                if sorted(manifest_pngs) != actual_names:
                    errors.append("source/slide-manifest.json PNG entries do not match the carousel PNG files")
                unreferenced = sorted(
                    path.name for path in manifest_path.parent.glob("*.svg") if path not in referenced_svgs
                )
                if unreferenced:
                    errors.append(f"unreferenced SVG sources: {', '.join(unreferenced)}")

    copy_path = folder / "post-copy.md"
    if not copy_path.is_file():
        errors.append("missing post-copy.md")
    else:
        copy = copy_path.read_text(encoding="utf-8")
        if "shuxueshuo.com" not in copy:
            errors.append("post-copy.md does not contain shuxueshuo.com")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"Validated {args.count} slides and post-copy.md in {folder}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
