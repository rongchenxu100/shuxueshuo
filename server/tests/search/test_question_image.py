from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from shuxueshuo_server.search import question_image
from shuxueshuo_server.search.figures import pixel_box
from shuxueshuo_server.search.question_image import question_png

PAGE = Path(__file__).parent / "fixtures/segment-pages/photo-skew/page.png"


def _shaded_question(width=2400, height=500):
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for x in range(width):
        tone = 235 - round(70 * x / width)
        draw.line([(x, 0), (x, height)], fill=(tone, tone - 6, tone - 18))
    draw.text((80, 160), "1. Find a so that x^2 - 2ax + 3 >= 0", fill=(30, 30, 30),
              font=ImageFont.load_default(size=120))
    return image


def test_shaded_paper_becomes_white_and_ink_stays_dark():
    out = Image.open(BytesIO(question_png(_shaded_question())))
    assert out.mode == "L" and out.size == (1600, 333)
    assert out.getpixel((5, 5)) == 255 and out.getpixel((1595, 5)) == 255
    assert out.getextrema()[0] < 60


def test_much_smaller_than_plain_png_and_deterministic():
    with Image.open(PAGE) as page:
        crop = page.convert("RGB").crop((0, 0, page.width, page.height // 3))
    plain = BytesIO()
    crop.save(plain, format="PNG")
    first = question_png(crop)
    assert len(first) < len(plain.getvalue()) / 3
    assert question_png(crop) == first


def test_small_crops_are_not_upscaled():
    assert Image.open(BytesIO(question_png(_shaded_question(600, 120)))).size == (600, 120)


@pytest.mark.parametrize('size', [(640, 320), (2400, 1201)])
def test_normalized_regions_keep_the_same_landmarks_after_preprocessing(size):
    original = Image.new('RGB', size, 'white')
    draw = ImageDraw.Draw(original)
    centers = [(.1, .2), (.5, .6), (.9, .8)]
    for x, y in centers:
        cx, cy = round(x * original.width), round(y * original.height)
        draw.ellipse((cx - 4, cy - 4, cx + 4, cy + 4), fill='black')
    with Image.open(BytesIO(question_png(original))) as processed:
        scale = min(1, 1600 / max(size))
        assert processed.size == tuple(round(v * scale) for v in size)
        for x, y in centers:
            box = [x - .01, y - .01, x + .01, y + .01]
            for picture in (original.convert('L'), processed):
                crop = picture.crop(pixel_box(box, picture.size))
                assert crop.getextrema()[0] < 80


def test_preprocessing_rejects_an_accidental_geometry_change(monkeypatch):
    background = question_image._background
    monkeypatch.setattr(question_image, '_background', lambda image: background(image).crop(
        (0, 0, image.width - 10, image.height - 10)))
    with pytest.raises(ValueError, match='image_input.geometry_mismatch'):
        question_png(Image.new('RGB', (400, 200), 'white'))
