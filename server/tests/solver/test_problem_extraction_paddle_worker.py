from __future__ import annotations

from shuxueshuo_server.solver.extraction.paddle_worker import (
    formula_confidence_from_paddle,
    formula_text_from_paddle,
    layout_items_from_paddle,
    text_items_from_paddle,
)


def test_layout_vendor_payload_is_normalized_without_paddle() -> None:
    items = layout_items_from_paddle(
        {
            "res": {
                "boxes": [
                    {
                        "label": "text",
                        "score": 0.9,
                        "coordinate": [1, 2, 11, 22],
                    }
                ]
            }
        }
    )
    assert items == (
        {
            "label": "text",
            "confidence": 0.9,
            "polygon": [[1.0, 2.0], [11.0, 2.0], [11.0, 22.0], [1.0, 22.0]],
        },
    )


def test_text_vendor_payload_uses_recognized_polygons() -> None:
    items = text_items_from_paddle(
        {
            "res": {
                "dt_polys": [[[0, 0], [3, 0], [3, 3], [0, 3]]],
                "rec_polys": [[[1, 1], [4, 1], [4, 4], [1, 4]]],
                "rec_texts": ["25. y=x^2"],
                "rec_scores": [0.8],
            }
        }
    )
    assert items[0]["polygon"][0] == [1, 1]
    assert items[0]["text"] == "25. y=x^2"


def test_formula_vendor_payload_is_unwrapped() -> None:
    assert formula_text_from_paddle({"res": {"rec_formula": " x ^ 2 "}}) == "x ^ 2"
    assert formula_confidence_from_paddle({"res": {"rec_score": 0.87}}) == 0.87
    assert formula_confidence_from_paddle({"res": {"rec_formula": "x"}}) == 0.5
