"""The shared graph plots each lesson's expression and preserves excluded values."""

import html
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("lesson,index", [("q01", 0), ("q09", 0), ("q09", 1)])
def test_quadratic_graph_matches_lesson_expression_and_domain(lesson, index):
    page = (ROOT / f"site/1/{lesson}/index.html").read_text()
    configs = re.findall(r'data-quadratic-graph="([^"]+)"', page)
    config = json.loads(html.unescape(configs[index]))
    config.update(uid="test-graph", variable="a")
    script = """
      global.window = {};
      require(process.argv[1]);
      console.log(window.PracticeComponents.quadraticGraph(JSON.parse(process.argv[2])));
    """
    svg = ET.fromstring(
        subprocess.check_output(
            [
                "node",
                "-e",
                script,
                str(ROOT / "site/assets/practice/components.js"),
                json.dumps(config),
            ],
            text=True,
        )
    )
    curve = svg.find('.//path[@class="quadratic-curve"]')
    xmin, xmax, ymin, ymax = config["bounds"]
    points = []
    for px, py in re.findall(r"[ML]([\d.-]+) ([\d.-]+)", curve.attrib["d"]):
        x = xmin + (float(px) - 48) / 270 * (xmax - xmin)
        y = ymin + (222 - float(py)) / 174 * (ymax - ymin)
        expected = (
            2 * x - x * x
            if lesson == "q01"
            else (x / 3 - 2 * x * x / 3 if index == 0 else x / 2 - 1.5 * x * x)
        )
        assert y == pytest.approx(expected, abs=2e-5)
        points.append(x)
    if lesson == "q01":
        assert points[0] == pytest.approx(0, abs=1e-5)
        assert points[-1] == pytest.approx(2, abs=1e-5)
    else:
        assert points[0] < 0
        assert points[-1] > config["excluded"][-1]
    holes = svg.findall('.//circle[@class="quadratic-excluded"]')
    assert len(holes) == 2
    for hole, excluded in zip(holes, config["excluded"], strict=True):
        x = xmin + (float(hole.attrib["cx"]) - 48) / 270 * (xmax - xmin)
        assert x == pytest.approx(excluded)
    assert svg.find('.//circle[@class="quadratic-vertex"]') is not None
    assert svg.attrib["aria-labelledby"] == "test-graph-title test-graph-description"
