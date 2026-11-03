import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from shuxueshuo_server.search import dev_api
from shuxueshuo_server.search.question_image import question_png
from shuxueshuo_server.search.segmentation import segment
from tests.search.support import authenticated_client


def _turn(image, degrees):
    """Independent pixel oracle: Pillow's transpose names are counterclockwise."""
    return image.copy() if not degrees else image.transpose({
        90: Image.Transpose.ROTATE_270,
        180: Image.Transpose.ROTATE_180,
        270: Image.Transpose.ROTATE_90,
    }[degrees])


def _page():
    image = Image.new("RGB", (320, 200), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 29, 19), fill="red")
    draw.rectangle((280, 0, 319, 29), fill="green")
    draw.rectangle((0, 160, 39, 199), fill="blue")
    draw.rectangle((270, 150, 319, 199), fill="yellow")
    # Different strokes within each OCR region expose a wrongly oriented crop.
    for x in range(35, 145, 11):
        draw.rectangle((x, 35, x + 3, 44 + x % 13), fill="black")
    for x in range(50, 250, 17):
        draw.rectangle((x, 115, x + 6, 135), fill="black")
    return image


def _png(image, *, exif=None):
    buffer = BytesIO()
    image.save(buffer, format="PNG", **({"exif": exif} if exif is not None else {}))
    return buffer.getvalue()


def _orientation(degrees=0, *, status=None, confidence=0.99):
    return {"status": status or ("corrected" if degrees else "upright"),
            "rotation_degrees": degrees, "predicted_degrees": degrees, "confidence": confidence}


def _observed(size, orientation, *, manual=False):
    # OCR may use a smaller image; coordinates still describe the full page.
    observed = {"width": size[0] // 2, "height": size[1] // 2,
                "lines": [{"box": [0.1, 0.15, 0.5, 0.26], "head": "1. Calculate"},
                          {"box": [0.15 if manual else 0.1, 0.55, 0.8, 0.7], "head": "2. Prove"}],
                "layout": [], "latency_ms": {"detect": 1}}
    if orientation is not None:
        observed["orientation"] = orientation
    return observed


def _client(tmp_path, monkeypatch, observe, *, raise_server_exceptions=True):
    monkeypatch.setattr(dev_api.OcrClient, "observe", observe)
    return authenticated_client(tmp_path, raise_server_exceptions=raise_server_exceptions)


def _upload(client, image=None, *, content=None):
    response = client.post("/api/search/pages", content=content or _png(image),
                           headers={"Content-Type": "image/png"})
    assert response.status_code == 200, response.text
    return response.json()


def _assert_image(actual, expected):
    with Image.open(BytesIO(actual) if isinstance(actual, bytes) else actual) as image:
        assert image.size == expected.size
        assert image.convert("RGB").tobytes() == expected.convert("RGB").tobytes()
        assert image.getexif().get(274) is None


def _capture_stage_one(monkeypatch):
    received = {}
    done = threading.Event()

    def run(png, output, provider, *, problem_id, original_png=None, read_graph_details=False):
        received.update(png=png, original_png=original_png, output=output)
        done.set()
        return {"status": "unreadable"}

    monkeypatch.setenv("RUN_LLM_INTEGRATION", "1")
    monkeypatch.setattr(dev_api, "run_question_image", run)
    monkeypatch.setattr("shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory",
                        lambda name, **kwargs: lambda: object())
    return received, done


@pytest.mark.parametrize("degrees", [0, 90, 180, 270])
def test_upload_normalizes_image_and_selected_crop_to_ocr_frame(tmp_path, monkeypatch, degrees):
    canonical = _page()
    source = _turn(canonical, (-degrees) % 360)
    observed = _observed(canonical.size, _orientation(degrees))
    calls = []

    def observe(self, path):
        calls.append(path)
        _assert_image(path, source)
        return observed

    client = _client(tmp_path, monkeypatch, observe)
    received, done = _capture_stage_one(monkeypatch)
    page = _upload(client, source)
    directory = tmp_path / "pages" / page["page_id"]
    assert calls == [directory / "source.png"]
    assert page["orientation"] == _orientation(degrees)
    assert page["rotation_reference"] == "upload_after_exif"
    assert page["rotation_count"] == 0
    assert [page["width"], page["height"]] == list(canonical.size)
    assert page["regions"] == segment(observed).regions
    assert len(page["regions"]) == 2
    _assert_image(directory / "source.png", source)
    _assert_image(directory / "page.png", canonical)
    assert json.loads((directory / "ocr.json").read_text()) == observed
    assert json.loads((directory / "segments.json").read_text()) == page
    served = client.get(page["image_url"])
    assert served.status_code == 200
    _assert_image(served.content, canonical)

    box = page["regions"][0]["box"]
    crop = canonical.crop(tuple(round(value * size) for value, size in zip(box, canonical.size * 2, strict=True)))
    expected = question_png(crop)
    started = client.post("/api/search/problems", json={"page_id": page["page_id"], "box": box})
    assert started.status_code == 200, started.text
    assert done.wait(5)
    assert received["png"] == expected
    assert (received["output"] / "question.png").read_bytes() == expected
    assert client.get(f"/api/search/problems/{started.json()['search_id']}/image").content == expected


def test_exif_is_applied_once_before_orientation_and_removed_from_source(tmp_path, monkeypatch):
    canonical = _page()
    raw = _turn(canonical, 270)
    exif = Image.Exif()
    exif[274] = 6  # Display the stored pixels 90 degrees clockwise.

    def observe(self, path):
        _assert_image(path, canonical)
        return _observed(canonical.size, _orientation())

    client = _client(tmp_path, monkeypatch, observe)
    page = _upload(client, content=_png(raw, exif=exif))
    _assert_image(tmp_path / "pages" / page["page_id"] / "page.png", canonical)
    _assert_image(client.get(page["image_url"]).content, canonical)


def test_uncertain_keeps_source_orientation_and_metadata(tmp_path, monkeypatch):
    source = _turn(_page(), 90)
    orientation = {**_orientation(status="uncertain", confidence=0.51), "predicted_degrees": 270}
    client = _client(tmp_path, monkeypatch, lambda self, path: _observed(source.size, orientation))
    page = _upload(client, source)
    assert page["orientation"] == orientation
    assert [page["width"], page["height"]] == list(source.size)
    _assert_image(client.get(page["image_url"]).content, source)


def test_old_observations_without_orientation_remain_supported(tmp_path, monkeypatch):
    source = _page()
    client = _client(tmp_path, monkeypatch, lambda self, path: _observed(source.size, None))
    page = _upload(client, source)
    assert page["orientation"] == {"status": "upright", "rotation_degrees": 0,
                                    "predicted_degrees": None, "confidence": None}
    _assert_image(client.get(page["image_url"]).content, source)


@pytest.mark.parametrize("degrees", [90, 180, 270])
def test_manual_rotation_uses_current_canonical_image_and_creates_fresh_page(tmp_path, monkeypatch, degrees):
    canonical = _page()
    source = _turn(canonical, 270)
    expected = _turn(canonical, degrees)
    calls = []

    def observe(self, path, *, auto_orient=True):
        calls.append((path, auto_orient))
        if auto_orient:
            _assert_image(path, source)
            return _observed(canonical.size, _orientation(90))
        _assert_image(path, expected)
        return _observed(expected.size, _orientation(status="manual", confidence=None), manual=True)

    client = _client(tmp_path, monkeypatch, observe)
    received, done = _capture_stage_one(monkeypatch)
    old = _upload(client, source)
    old_dir = tmp_path / "pages" / old["page_id"]
    started = client.post("/api/search/problems", json={"page_id": old["page_id"], "box": old["regions"][0]["box"]})
    assert started.status_code == 200
    assert done.wait(5)
    old_files = {path.relative_to(old_dir): path.read_bytes() for path in old_dir.rglob("*") if path.is_file()}

    response = client.post(f"/api/search/pages/{old['page_id']}/rotate", json={"degrees": degrees})
    assert response.status_code == 200, response.text
    page = response.json()
    directory = tmp_path / "pages" / page["page_id"]
    assert page["page_id"] != old["page_id"]
    assert page["parent_page_id"] == old["page_id"]
    assert page["rotation_reference"] == "parent_page"
    assert page["rotation_count"] == 1
    assert page["orientation"] == {"status": "manual", "rotation_degrees": degrees,
                                    "predicted_degrees": None, "confidence": None}
    assert calls == [(old_dir / "source.png", True), (directory / "source.png", False)]
    assert [page["width"], page["height"]] == list(expected.size)
    assert page["regions"] != old["regions"]
    assert not (directory / "problems").exists()
    for name, content in old_files.items():
        assert (old_dir / name).read_bytes() == content
    _assert_image(directory / "source.png", expected)
    _assert_image(directory / "page.png", expected)
    _assert_image(client.get(page["image_url"]).content, expected)
    _assert_image(client.get(old["image_url"]).content, canonical)
    assert client.get(f"/api/search/problems/{started.json()['search_id']}/image").content == received["png"]
    box = page["regions"][0]["box"]
    crop = expected.crop(tuple(round(value * size) for value, size in zip(box, expected.size * 2, strict=True)))
    done.clear()
    selected = client.post("/api/search/problems", json={"page_id": page["page_id"], "box": box})
    assert selected.status_code == 200, selected.text
    assert done.wait(5)
    assert received["png"] == question_png(crop)
    assert (received["output"] / "question.png").read_bytes() == received["png"]


@pytest.mark.parametrize("degrees", [0, -90, 360, 45, 90.0, "90", True, False, None, [], {}])
def test_manual_rotation_rejects_invalid_angles_without_calling_ocr(tmp_path, monkeypatch, degrees):
    def observe(self, path, *, auto_orient=True):
        assert auto_orient
        return _observed(_page().size, _orientation())

    client = _client(tmp_path, monkeypatch, observe)
    page = _upload(client, _page())
    response = client.post(f"/api/search/pages/{page['page_id']}/rotate", json={"degrees": degrees})
    assert response.status_code == 422
    assert len(list((tmp_path / "pages").iterdir())) == 1


@pytest.mark.parametrize("orientation", [
    None, [], {"status": []},
    _orientation(45), _orientation(True), _orientation(90.0),
    _orientation(90, status="upright"), _orientation(90, status="uncertain"),
    _orientation(0, status="corrected"), _orientation(status="manual"),
    _orientation(confidence=1.1), _orientation(confidence=-0.1), _orientation(confidence=True),
    _orientation(confidence="0.99"), _orientation(confidence=float("nan")),
    {**_orientation(), "predicted_degrees": 360}, {**_orientation(), "predicted_degrees": False},
])
def test_invalid_worker_orientation_is_not_published(tmp_path, monkeypatch, orientation):
    observed = {**_observed(_page().size, None), "orientation": orientation}
    client = _client(tmp_path, monkeypatch, lambda self, path: observed)
    response = client.post("/api/search/pages", content=_png(_page()))
    assert response.status_code == 503, response.text
    assert response.json()["detail"] == "ocr.unavailable"
    (directory,) = list((tmp_path / "pages").iterdir())
    assert (directory / "source.png").exists()
    assert not (directory / "ocr.json").exists()
    assert not (directory / "page.png").exists()
    assert not (directory / "segments.json").exists()
    assert client.get(f"/api/search/pages/{directory.name}/image").status_code == 404


@pytest.mark.parametrize("manual", [False, True])
def test_ocr_failure_does_not_publish_or_reuse_regions(tmp_path, monkeypatch, manual):
    def observe(self, path, *, auto_orient=True):
        if manual and auto_orient:
            return _observed(_page().size, _orientation())
        raise dev_api.OcrWorkerError("test.failure")

    client = _client(tmp_path, monkeypatch, observe)
    if manual:
        old = _upload(client, _page())
        old_dir = tmp_path / "pages" / old["page_id"]
        previous = {path.name: path.read_bytes() for path in old_dir.iterdir()}
        response = client.post(f"/api/search/pages/{old['page_id']}/rotate", json={"degrees": 90})
        for name, content in previous.items():
            assert (old_dir / name).read_bytes() == content
    else:
        response = client.post("/api/search/pages", content=_png(_page()))
    assert response.status_code == 503
    assert response.json()["detail"] == "ocr.unavailable"
    failed = [path for path in (tmp_path / "pages").iterdir() if not (path / "page.png").exists()]
    assert len(failed) == 1
    assert (failed[0] / "source.png").exists()
    assert not (failed[0] / "segments.json").exists()


def test_manual_worker_must_not_apply_a_second_rotation(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, lambda self, path, **kwargs:
                     _observed(_page().size, _orientation(90) if kwargs else _orientation()))
    old = _upload(client, _page())
    response = client.post(f"/api/search/pages/{old['page_id']}/rotate", json={"degrees": 90})
    assert response.status_code == 503
    assert response.json()["detail"] == "ocr.unavailable"
    assert len(list(tmp_path.glob("pages/*/page.png"))) == 1


def test_manual_rotation_requires_an_existing_page(tmp_path, monkeypatch):
    def observe(self, path, **kwargs):
        pytest.fail("Missing pages must not call OCR")

    client = _client(tmp_path, monkeypatch, observe)
    assert client.post("/api/search/pages/000000000000/rotate", json={"degrees": 90}).status_code == 404


def test_large_jpeg_has_a_small_preview_but_keeps_full_resolution_crop_pixels(tmp_path, monkeypatch):
    photograph = Image.new("RGB", (4000, 2500), (238, 232, 220))
    draw = ImageDraw.Draw(photograph)
    # Thin, differently spaced strokes survive in the full-resolution crop
    # but would disappear or shift if the preview were used for stage one.
    for x in range(100, 3900, 13):
        draw.line((x, 300, x + 19, 2500), fill=(30, 45, 60), width=1 + x % 3)
    buffer = BytesIO()
    photograph.save(buffer, format="JPEG", quality=95)
    content = buffer.getvalue()
    with Image.open(BytesIO(content)) as decoded:
        canonical = _turn(decoded.convert("RGB"), 90)
    client = _client(tmp_path, monkeypatch,
                     lambda self, path: _observed(canonical.size, _orientation(90)))
    received, done = _capture_stage_one(monkeypatch)
    page = _upload(client, content=content)
    assert [page["width"], page["height"]] == [2500, 4000]
    assert page["preview_url"] != page["image_url"]
    preview = client.get(page["preview_url"])
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/jpeg"
    assert len(preview.content) < 1_000_000
    with Image.open(BytesIO(preview.content)) as image:
        assert image.format == "JPEG"
        assert image.size == (1000, 1600)
    _assert_image(tmp_path / "pages" / page["page_id"] / "page.png", canonical)
    box = [0.12, 0.13, 0.27, 0.29]
    crop = canonical.crop((300, 520, 675, 1160))
    started = client.post("/api/search/problems", json={"page_id": page["page_id"], "box": box})
    assert started.status_code == 200, started.text
    assert done.wait(5)
    assert started.json()["crop_size"] == [375, 640]
    assert received["png"] == question_png(crop)
    assert (received["output"] / "question.png").read_bytes() == received["png"]


@pytest.mark.parametrize("failure", ["page", "preview", "manifest"])
def test_images_without_a_final_manifest_are_never_readable(tmp_path, monkeypatch, failure):
    original_image_save, original_replace = Image.Image.save, dev_api.os.replace

    def save_image(image, output, *args, **kwargs):
        original_image_save(image, output, *args, **kwargs)
        name = str(getattr(output, "name", output))
        if ((failure == "page" and name.endswith("page.png"))
                or (failure == "preview" and kwargs.get("format") == "JPEG")):
            raise OSError("test.incomplete_image_write")

    def replace(source, destination):
        if failure == "manifest" and Path(destination).name == "segments.json":
            raise OSError("test.manifest_publish_failure")
        return original_replace(source, destination)

    monkeypatch.setattr(Image.Image, "save", save_image)
    monkeypatch.setattr(dev_api.os, "replace", replace)
    client = _client(tmp_path, monkeypatch, lambda self, path: _observed(_page().size, _orientation()),
                     raise_server_exceptions=False)
    response = client.post("/api/search/pages", content=_png(_page()))
    assert response.status_code == 503
    (directory,) = list((tmp_path / "pages").iterdir())
    assert (directory / "page.png").is_file(), "even a finished canonical image is not a publication marker"
    assert not (directory / "segments.json").exists()
    assert client.get(f"/api/search/pages/{directory.name}/image").status_code == 404
    assert client.get(f"/api/search/pages/{directory.name}/preview").status_code == 404
    assert client.post(f"/api/search/pages/{directory.name}/rotate", json={"degrees": 90}).status_code == 404
    assert client.post("/api/search/problems", json={"page_id": directory.name, "box": [0, 0, 1, 1]}).status_code == 404


def test_both_images_finish_before_manifest_publication(tmp_path, monkeypatch):
    original_save = dev_api.save
    checked = []

    def save(path, value):
        if path.name == "segments.json":
            assert not path.exists()
            with Image.open(path.parent / "page.png") as full, Image.open(path.parent / "preview.jpg") as preview:
                full.load()
                preview.load()
                assert full.size == (320, 200)
                assert preview.format == "JPEG"
            checked.append(path)
        return original_save(path, value)

    monkeypatch.setattr(dev_api, "save", save)
    client = _client(tmp_path, monkeypatch, lambda self, path: _observed(_page().size, _orientation()))
    page = _upload(client, _page())
    assert checked == [tmp_path / "pages" / page["page_id"] / "segments.json"]


def test_upload_and_manual_image_work_never_run_on_an_event_loop(tmp_path, monkeypatch):
    content = _png(_page())
    calls = []

    def instrument(name, original):
        def invoke(*args, **kwargs):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                on_loop = False
            else:
                on_loop = True
            calls.append((name, on_loop))
            return original(*args, **kwargs)
        return invoke

    for owner, name in [(Image, "open"), (dev_api.ImageOps, "exif_transpose"),
                        (Image.Image, "save"), (Image.Image, "thumbnail"),
                        (dev_api, "rotate_clockwise"), (dev_api, "segment"), (dev_api, "save")]:
        monkeypatch.setattr(owner, name, instrument(name, getattr(owner, name)))

    def observe(self, path, *, auto_orient=True):
        with Image.open(path) as source:
            return _observed(source.size, _orientation(status="upright" if auto_orient else "manual"))

    client = _client(tmp_path, monkeypatch, instrument("observe", observe))
    page = _upload(client, content=content)
    response = client.post(f"/api/search/pages/{page['page_id']}/rotate", json={"degrees": 90})
    assert response.status_code == 200, response.text
    assert {name for name, _ in calls} >= {"open", "exif_transpose", "save", "thumbnail", "rotate_clockwise",
                                        "segment", "observe"}
    assert not any(on_loop for _, on_loop in calls), calls


def test_rotation_depth_limit_is_persistent_and_keeps_existing_problems(tmp_path, monkeypatch):
    calls = []

    def observe(self, path, *, auto_orient=True):
        calls.append(path)
        with Image.open(path) as source:
            return _observed(source.size, _orientation(status="upright" if auto_orient else "manual"))

    client = _client(tmp_path, monkeypatch, observe)
    received, done = _capture_stage_one(monkeypatch)
    first = _upload(client, _page())
    started = client.post("/api/search/problems", json={"page_id": first["page_id"], "box": [0.1, 0.1, 0.8, 0.8]})
    assert started.status_code == 200
    assert done.wait(5)
    first_dir = tmp_path / "pages" / first["page_id"]
    original = {path.relative_to(first_dir): path.read_bytes() for path in first_dir.rglob("*") if path.is_file()}
    page = first
    for count in range(1, 9):
        response = client.post(f"/api/search/pages/{page['page_id']}/rotate", json={"degrees": 90})
        assert response.status_code == 200, response.text
        rotated = response.json()
        assert rotated["rotation_count"] == count
        assert rotated["parent_page_id"] == page["page_id"]
        assert rotated["rotation_reference"] == "parent_page"
        page = rotated
    # A fresh router must enforce the saved count rather than restarting it.
    client = _client(tmp_path, monkeypatch, observe)
    before = set((tmp_path / "pages").iterdir())
    response = client.post(f"/api/search/pages/{page['page_id']}/rotate", json={"degrees": 180})
    assert response.status_code == 409
    assert response.json()["detail"] == "page.rotation_limit"
    assert set((tmp_path / "pages").iterdir()) == before
    assert len(calls) == 9
    for path, content in original.items():
        assert (first_dir / path).read_bytes() == content
    assert client.get(f"/api/search/problems/{started.json()['search_id']}/image").content == received["png"]


def test_unregistered_legacy_page_remains_inaccessible(tmp_path, monkeypatch):
    page_id = "0123456789ab"
    directory = tmp_path / page_id
    directory.mkdir()
    source = _page()
    source.save(directory / "page.png")
    legacy = {"page_id": page_id, "width": source.width, "height": source.height, "regions": []}
    (directory / "segments.json").write_text(json.dumps(legacy))
    calls = []

    def observe(self, path, *, auto_orient=True):
        assert not auto_orient
        calls.append(path)
        return _observed((source.height, source.width), _orientation(status="manual"))

    client = _client(tmp_path, monkeypatch, observe)
    response = client.get(f"/api/search/pages/{page_id}/preview")
    assert response.status_code == 404
    assert not calls
    assert json.loads((directory / "segments.json").read_text()) == legacy
    assert client.get(f"/api/search/pages/{page_id}/image").status_code == 404
    rotated = client.post(f"/api/search/pages/{page_id}/rotate", json={"degrees": 90})
    assert rotated.status_code == 404
    assert not calls


def test_concurrent_unregistered_legacy_preview_requests_are_denied(tmp_path, monkeypatch):
    page_id = "0123456789ab"
    directory = tmp_path / page_id
    directory.mkdir()
    _page().save(directory / "page.png")
    (directory / "segments.json").write_text(json.dumps({"page_id": page_id}))
    barrier = threading.Barrier(2)
    destinations = []
    original_save = Image.Image.save

    def save(image, output, *args, **kwargs):
        if kwargs.get("format") == "JPEG":
            destinations.append(output.name)
            barrier.wait(timeout=5)
        return original_save(image, output, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "save", save)
    client = _client(tmp_path, monkeypatch, lambda self, path: pytest.fail("Preview reads must not run OCR"))
    with ThreadPoolExecutor(max_workers=2) as executor:
        replies = list(executor.map(lambda _: client.get(f"/api/search/pages/{page_id}/preview"), range(2)))
    assert not destinations
    for response in replies:
        assert response.status_code == 404
