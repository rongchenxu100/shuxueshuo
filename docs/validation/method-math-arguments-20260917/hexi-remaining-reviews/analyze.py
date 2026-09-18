"""Audit the other two frozen Hexi samples without requesting model output."""

import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
BASE = HERE.parent


def main():
    source = BASE / "hexi-sample-01-review" / "analyze.py"
    spec = importlib.util.spec_from_file_location("hexi_evidence_audit", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original_samples = module.SAMPLE.parent
    for sample in (2, 3):
        output = BASE / f"hexi-sample-{sample:02d}-review"
        output.mkdir(parents=True, exist_ok=True)
        module.OUT = output
        module.SAMPLE = original_samples / str(sample)
        module.main()
        path = output / "analysis.json"
        data = json.loads(path.read_text())
        data["sample"] = sample
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
