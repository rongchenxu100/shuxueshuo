"""One semantic call only. A failed gate is retained; never auto-repair/review/retry a run."""

import json
import os
from hashlib import sha256
from pathlib import Path
from time import perf_counter

from .candidate_common import validate_match
from .identity import revision
from .notation_contract import CONTRACT
from .observation import observation_view
from .wire import components


def build_request(fixture, store, registry):
    from PIL import Image

    from shuxueshuo_server.solver.extraction.multimodal_evidence import (
        MultimodalEvidencePack,
        MultimodalImageInput,
    )
    from shuxueshuo_server.solver.extraction.multimodal_provider import (
        MultimodalExtractionPrompt,
        MultimodalProviderImage,
        MultimodalProviderRequest,
    )

    provenance = json.loads((fixture / "provenance.json").read_text())
    contract = provenance.get("output_contract")
    wire_prompt, *_ = components(contract)
    source_path = fixture / provenance.get("image_file", "source.png")
    content = source_path.read_bytes()
    digest = sha256(content).hexdigest()
    for row in provenance["files"]:
        if (
            sha256((fixture / row["file"]).read_bytes()).hexdigest()
            != row["fixture_sha256"]
        ):
            raise ValueError("fixture hash mismatch: " + row["file"])
    if digest != provenance["image_sha256"]:
        raise ValueError("source hash mismatch")
    observation = json.loads((fixture / "observation.json").read_text())
    with Image.open(source_path) as source_image:
        width, height = source_image.size
        media_type, suffix = {
            "PNG": ("image/png", ".png"),
            "JPEG": ("image/jpeg", ".jpg"),
        }[source_image.format]
    image = store.put_bytes(
        kind="understanding_primary",
        content=content,
        media_type=media_type,
        suffix=suffix,
    )
    if (width, height) != (
        observation["pages"][0]["width"],
        observation["pages"][0]["height"],
    ):
        raise ValueError("observation image dimensions mismatch")
    pack = MultimodalEvidencePack(
        schema_version="multimodal-evidence-pack/v1",
        evidence_pack_id="step2",
        base_context_id="step2",
        source_id="step2",
        source_revision_hash=digest,
        selection_id="whole-image",
        observation_hash=observation["observation_hash"],
        images=(
            MultimodalImageInput("primary", "page-1", "primary", image, width, height),
        ),
        printed_text=(),
        recognized_formulas=(),
        unresolved_items=(),
        region_index=(),
    )
    # Save complete evidence and the reversible alias map; only the semantic view goes to the model.
    _, aliases = observation_view(observation)
    observation_artifact = store.put_json(
        kind="understanding_observation_original", payload=observation
    )
    aliases_artifact = store.put_json(
        kind="understanding_observation_aliases", payload=aliases
    )
    store.put_json(
        kind="understanding_observation_view_manifest",
        payload={
            "schema_version": "problem-observation-view-audit/v1",
            "source_sha256": digest,
            "original": observation_artifact.to_payload(),
            "aliases": aliases_artifact.to_payload(),
            "view_sha256": revision(observation_view(observation)[0]),
        },
    )
    payload = wire_prompt.prompt_payload(
        problem_id=provenance.get("case_id", fixture.name),
        source_sha256=digest,
        registry=registry,
        observation=observation,
    )
    request = MultimodalProviderRequest(
        evidence_pack=pack,
        prompt=MultimodalExtractionPrompt(
            wire_prompt.SYSTEM,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            getattr(wire_prompt, "USER_SUFFIX", "请从完整图片输出题意 JSON。"),
        ),
        images=(
            MultimodalProviderImage(
                "primary", "page-1", "primary", image, content, width, height
            ),
        ),
        contract_version=contract,
        contract_schema=payload["response_schema"],
        response_format={"type": "json_object"},
    )
    return request


def run(fixture, output, provider, registry):
    from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore

    output.mkdir(parents=True, exist_ok=True)
    # Exclusive durable reservation, including crashes: resuming this experiment never pays again.
    marker = output / "semantic-call-reserved.json"
    store = ExtractionArtifactStore(output / "artifacts")
    request = provider.prepare_request(build_request(fixture, store, registry))
    wire_prompt, Validator, compare_wire, evaluate_wire, parse_wire, render_wire = (
        components(request.contract_version)
    )
    expected = json.loads((fixture / "gold.json").read_text())
    case_id = json.loads((fixture / "provenance.json").read_text()).get(
        "case_id", fixture.name
    )
    policy_file = fixture / "acceptance-policy.json"
    policy = json.loads(policy_file.read_text()) if policy_file.exists() else None
    evaluate_wire(
        expected, expected, policy
    )  # reject stale/invalid policy before payment
    gold_report = Validator().validate(expected)
    if (
        not gold_report.ok
        or not validate_match(expected, [f["family_id"] for f in registry])["ok"]
    ):
        raise ValueError("gold is not valid; refusing model call")
    frozen = {
        "template_files": {
            str(p.relative_to(wire_prompt.ROOT)): sha256(p.read_bytes()).hexdigest()
            for p in getattr(wire_prompt, "TEMPLATE_FILES", ())
        },
        "implementation_files": {
            p.name: sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(__file__).parent.glob("*.py"))
        },
        "extraction_policy": CONTRACT,
        "authoring_schema_hash": revision(request.contract_schema),
        "system_prompt_hash": sha256(wire_prompt.SYSTEM.encode()).hexdigest(),
        "contracts": {request.contract_version: revision(request.contract_schema)},
        "output_contract": request.contract_version,
        "request_hash": revision(request.redacted_payload()),
        "gold_sha256": sha256((fixture / "gold.json").read_bytes()).hexdigest(),
        "image_sha256": request.images[0].artifact.sha256,
        "semantic_budget": 1,
        "network_budget": 2,
        "sdk_retries": 0,
        "registry_snapshot": revision(registry),
        "case_id": case_id,
        "provenance_sha256": sha256(
            (fixture / "provenance.json").read_bytes()
        ).hexdigest(),
        "observation_sha256": sha256(
            (fixture / "observation.json").read_bytes()
        ).hexdigest(),
        "acceptance_policy": policy,
    }
    with marker.open("x") as f:
        json.dump(frozen, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())

    def save(name, x):
        (output / name).write_text(json.dumps(x, ensure_ascii=False, indent=2) + "\n")

    save("request.json", request.redacted_payload())
    save("frozen.json", frozen)
    started = perf_counter()
    summary = {
        "case_id": case_id,
        "passed": False,
        "candidate_only": True,
        "source_reviewed": False,
        "solver_ready": False,
        "semantic_calls": 1,
        "network_attempts": 0,
    }
    try:
        response = provider.complete(request)
        (output / "raw-response.txt").write_text(response.text)
        save("provider-response.json", response.raw_payload)
        save("call.json", response.metadata_payload())
        summary["network_attempts"] = len(response.provider_attempts)
        parsed = parse_wire(
            response.text,
            problem_id=case_id,
            source_sha256=request.images[0].artifact.sha256,
            registry_snapshot=revision(registry),
            registered_families=[f["family_id"] for f in registry],
            store=store,
        )
        save("parsed.json", parsed)
        # Benchmark success describes extraction only; missing figures still block handoff.
        summary["continuation"] = parsed["continuation"]
        diff = {"ok": False, "reason": "invalid domain"}
        if parsed.get("contract_valid"):
            actual = {**parsed["objects"]["ir"], **parsed["objects"]["match"]}
            diff = compare_wire(expected, actual)
            diff["unmatched"] = actual["match_status"] == "unmatched"
            diff["match_correct"] = all(
                actual[k] == expected[k] for k in ("match_status", "family_id")
            )
            summary["match_status"] = actual["match_status"]
            summary["family_id"] = actual["family_id"]
            summary["match_correct"] = diff["match_correct"]
            acceptance = evaluate_wire(expected, actual, policy)
            save("acceptance.json", acceptance)
            summary["strict_semantics_passed"] = diff["ok"]
            summary["accepted_omissions"] = acceptance["accepted_omissions"]
            summary["passed"] = acceptance["ok"] and diff["match_correct"]
            (output / "candidate.html").write_text(render_wire(actual))
        save("diff.json", diff)
        if (
            response.finish_reason != "stop"
            or not 1 <= summary["network_attempts"] <= 2
        ):
            summary["passed"] = False
            summary["error"] = "truncated/invalid finish reason or network budget"
        summary["contract_valid"] = parsed.get("contract_valid", False)
    except Exception as exc:  # noqa: BLE001 - durably record all isolated experiment failures
        # Do not stringify authenticated SDK/client objects or request headers.
        summary["error_type"] = type(exc).__name__
        summary["error_code"] = getattr(exc, "code", None)
        attempts = getattr(provider, "last_provider_attempts", ())
        summary["network_attempts"] = len(attempts)
        save(
            "failed-attempts.json",
            [{k: v for k, v in a.items() if k != "error_message"} for a in attempts],
        )
    summary["elapsed_seconds"] = round(perf_counter() - started, 3)
    save("summary.json", summary)
    return summary
