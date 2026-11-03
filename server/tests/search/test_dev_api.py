import json
import threading
import time
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from shuxueshuo_server.graph_lesson.stage_one.runner import build_image_request
from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.search import dev_api
from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from tests.search.support import authenticated_client
from tests.search.test_identity import public_candidate, reviewed_result

PAGE = Path(__file__).parent / "fixtures/segment-pages/two-column"


@pytest.fixture
def client(tmp_path, monkeypatch):
    recorded = json.loads((PAGE / "ocr.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(dev_api.OcrClient, "observe", lambda self, path: recorded)
    return authenticated_client(tmp_path)


def _upload(client):
    response = client.post("/api/search/pages", content=(PAGE / "page.png").read_bytes(),
                           headers={"Content-Type": "image/png"})
    assert response.status_code == 200, response.text
    return response.json()


def test_upload_returns_question_boxes(client):
    page = _upload(client)
    assert page["mode"] == "numbered"
    assert [r["number"] for r in page["regions"]] == list(range(1, 9))


def test_rejects_non_images(client):
    assert client.post("/api/search/pages", content=b"not an image").status_code == 400


def test_stage_one_is_opt_in(client, monkeypatch):
    monkeypatch.delenv("RUN_LLM_INTEGRATION", raising=False)
    page = _upload(client)
    response = client.post("/api/search/problems", json={"page_id": page["page_id"], "box": page["regions"][0]["box"]})
    assert response.status_code == 503


def test_chosen_box_is_cropped_and_handed_to_stage_one(client, monkeypatch, tmp_path):
    monkeypatch.setenv("RUN_LLM_INTEGRATION", "1")
    received = {}

    def fake_run(png, output, provider, *, problem_id, original_png=None, read_graph_details=False):
        assert read_graph_details
        received["png"] = png
        received["original"] = original_png
        digest = sha256(png).hexdigest()
        (output / dev_api.RESULT_FILE).write_text(json.dumps({
            **reviewed_result(public_candidate()),
            "features": [], "review_findings": [], "question_sha256": digest, "sent_image_sha256": [digest],
            "elapsed_seconds": 1.0}), encoding="utf-8")

    monkeypatch.setattr(dev_api, "run_question_image", fake_run)
    monkeypatch.setattr("shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory",
                        lambda name, **kwargs: (lambda: object()))
    page = _upload(client)
    box = page["regions"][4]["box"]
    started = client.post("/api/search/problems", json={"page_id": page["page_id"], "box": box}).json()

    for _ in range(50):
        status = client.get(f"/api/search/problems/{started['search_id']}").json()
        if status["state"] == "done":
            break
        time.sleep(0.05)
    assert status["outcome"] == "ok" and status["image_check"]["verified"]

    crop = Image.open(BytesIO(received["png"]))
    assert crop.format == "PNG" and crop.mode == "L"
    with Image.open(PAGE / "page.png") as original:
        w, h = original.size
    expected = (round(box[2] * w) - round(box[0] * w), round(box[3] * h) - round(box[1] * h))
    assert crop.size == expected or (max(crop.size) == 1600 and abs(crop.width / crop.height - expected[0] / expected[1]) < 0.02)
    assert status["crop"]["bytes"] == len(received["png"])
    served = client.get(f"/api/search/problems/{started['search_id']}/image").content
    assert served == received["png"]
    original_row = next(r for r in status['figures']['figures'] if r['id'] == 'original')
    assert client.get(original_row['image_url']).content == received['original']
    assert received['original'] != received['png']
    with Image.open(BytesIO(received['original'])) as original:
        assert original.mode == 'RGB' and original.size == expected


def test_preview_is_the_candidate_under_review(client, monkeypatch):
    monkeypatch.setenv("RUN_LLM_INTEGRATION", "1")
    release = threading.Event()
    candidate = {"original_text": "已知函数…\n（1）…\n（2）…",
                 "root": {"children": [{"label": "（1）"}, {"label": "（2）"}]}}
    later = {**candidate, "original_text": "修正后"}

    def ledger(output, *calls):
        (output / "workflow").mkdir(exist_ok=True)
        (output / "workflow/ledger.json").write_text(json.dumps({"identity": {}, "calls": [
            {"stage": stage, "status": "completed", "base_revision": base} for stage, base in calls]}))

    def fake_run(png, output, provider, *, problem_id, original_png=None, read_graph_details=False):
        ledger(output, ("extract", None))
        (output / "workflow/candidate.json").write_text(json.dumps(candidate))
        steps["extracted"].set()
        steps["review"].wait(5)
        ledger(output, ("extract", None), ("review", revision(candidate)))
        steps["reviewing"].set()
        steps["repair"].wait(5)
        (output / "workflow/candidate.json").write_text(json.dumps(later))
        steps["repaired"].set()
        release.wait(5)

    steps = {name: threading.Event() for name in ("extracted", "review", "reviewing", "repair", "repaired")}
    monkeypatch.setattr(dev_api, "run_question_image", fake_run)
    monkeypatch.setattr("shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory",
                        lambda name, **kwargs: (lambda: object()))
    page = _upload(client)
    sid = client.post("/api/search/problems", json={"page_id": page["page_id"], "box": page["regions"][0]["box"]}).json()["search_id"]
    status = lambda: client.get(f"/api/search/problems/{sid}").json()
    try:
        assert steps["extracted"].wait(5)
        assert status()["preview"] is None
        steps["review"].set()
        assert steps["reviewing"].wait(5)
        assert status()["preview"] == {"original_text": candidate["original_text"], "parts": ["（1）", "（2）"],
                                       "root": candidate["root"]}
        steps["repair"].set()
        assert steps["repaired"].wait(5)
        assert status()["preview"] is None
    finally:
        for event in steps.values():
            event.set()
        release.set()


def test_stage_one_request_carries_exactly_the_crop(tmp_path):
    buffer = BytesIO()
    Image.new("RGB", (320, 80), "white").save(buffer, format="PNG")
    png = buffer.getvalue()
    request = build_image_request(png, ExtractionArtifactStore(tmp_path))
    (image,) = request.images
    assert image.content == png
    assert image.artifact.sha256 == sha256(png).hexdigest()
    assert (image.width, image.height) == (320, 80)


def test_stage_one_request_rejects_jpeg(tmp_path):
    buffer = BytesIO()
    Image.new("RGB", (10, 10)).save(buffer, format="JPEG")
    with pytest.raises(ValueError):
        build_image_request(buffer.getvalue(), ExtractionArtifactStore(tmp_path))


@pytest.mark.parametrize("status,unsupported,outcome", [
    ("code_gap", [{"code": "notation.unrecognized_token"}], "unsupported"),
    ("workflow.budget_exhausted", [{"code": "notation.unrecognized_token"}], "unsupported"),
    ("workflow.budget_exhausted", [], "error"),
    ("workflow.internal_error", [{"code": "KeyError"}], "error"),
])
def test_unsupported_mathematics_is_not_a_system_failure(status, unsupported, outcome):
    result = {"status": status, "unsupported_diagnostics": unsupported,
              "question_sha256": "a", "sent_image_sha256": ["a"]}
    assert dev_api._present(result)["outcome"] == outcome


@pytest.mark.parametrize('code,outcome', [
    ('figure.merge_invalid', 'error'),
    ('figure.uncertain_facts', 'unclear'),
    ('missing_figure', 'figure'),
])
def test_merge_contract_failure_is_not_reported_as_a_blurry_photo(code, outcome):
    result = {'status': 'needs_confirmation', 'question_sha256': 'a', 'sent_image_sha256': ['a'],
              'confirmation_diagnostics': [{'code': code, 'message': 'diagnostic'}]}
    assert dev_api._present(result)['outcome'] == outcome
    assert result['status'] == 'needs_confirmation'  # Historic evidence stays intact.


@pytest.mark.parametrize('attempt_status,outcome', [
    ('review.invalid_response', 'error'),
    ('workflow.budget_exhausted', 'error'),
    ('needs_confirmation', 'unclear'),
])
def test_retained_figure_failures_use_the_last_attempt_status(attempt_status, outcome):
    result = {'status': 'needs_confirmation', 'question_sha256': 'a', 'sent_image_sha256': ['a'],
              'figure_attempts': [{'status': 'review.invalid_response'}, {'status': attempt_status}]}
    presented = dev_api._present(result)
    assert presented['outcome'] == outcome
    assert presented['status'] == attempt_status
    assert result['status'] == 'needs_confirmation'
