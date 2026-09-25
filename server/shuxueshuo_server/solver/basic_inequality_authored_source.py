"""Explicit source-transcription admission, separate from real extraction replay."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

from shuxueshuo_server.problem_understanding.basic_inequality_problem_ir import (
    convert_notation,
)

from .basic_inequality_stage4a import build_authoring_bundle
from .extraction.source_identity import freeze_json, stable_hash


def load_transcribed_authoring_bundle(notation_path, problem_ir_path):
    notation_path = Path(notation_path)
    manifest = json.loads((notation_path.parent / "source.json").read_text())
    image = notation_path.parent / manifest["image"]
    if hashlib.sha256(image.read_bytes()).hexdigest() != manifest["image_sha256"]:
        raise ValueError("transcribed source image changed")
    if (
        hashlib.sha256(notation_path.read_bytes()).hexdigest()
        != manifest["notation_sha256"]
    ):
        raise ValueError("transcribed notation changed")
    source = convert_notation(
        json.loads(notation_path.read_text()), problem_id=manifest["problem_id"]
    )
    source["original_text"]["source"] = "source_image_transcription"
    artifact = {
        "schema_version": "basic-inequality-authored-input/v1",
        "input": source,
        "provenance": manifest,
    }
    if json.loads(Path(problem_ir_path).read_text()) != artifact:
        raise ValueError("transcribed ProblemIR differs from source projection")
    bundle = build_authoring_bundle(source)
    return replace(
        bundle,
        provenance=freeze_json(manifest),
        source_artifact_ids=(manifest["image_sha256"], manifest["notation_sha256"]),
        admission_evidence=freeze_json(
            {
                "kind": "source_image_transcription",
                "source_hash": stable_hash(source),
                "provenance_hash": stable_hash(manifest),
            }
        ),
    )
