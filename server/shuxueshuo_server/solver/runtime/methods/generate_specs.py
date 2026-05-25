"""从 method 代码生成 MethodSpec JSON 文件。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import method_spec_payloads


def default_output_dir() -> Path:
    """定位仓库根目录下的 internal/method-specs。"""
    return Path(__file__).resolve().parents[5] / "internal" / "method-specs"


def write_method_spec_json(output_dir: str | Path | None = None) -> list[Path]:
    """把代码中的 SPEC 刷新为 JSON 文件，并返回写出的路径。"""
    target_dir = Path(output_dir) if output_dir is not None else default_output_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for payload in sorted(method_spec_payloads(), key=lambda item: item["method_id"]):
        filename = payload["method_id"].replace("_", "-") + ".json"
        path = target_dir / filename
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate MethodSpec JSON from method code.")
    parser.add_argument("--output", help="Output directory, defaults to internal/method-specs.")
    args = parser.parse_args(argv)
    for path in write_method_spec_json(args.output):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
