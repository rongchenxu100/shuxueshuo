"""Build the reviewed B09 picture-display sample; never publish student uploads.

Run with server/.venv/bin/python tools/build_function_graph_g0_fixtures.py.
Coordinates below were checked against the archived teaching-material page.
Only the question and its four original options are exported, not its solution.
"""
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
from shuxueshuo_server.search.figures import (
    MANIFEST,
    image_bytes,
    manifest_for,
    presentation_identity,
    validate_manifest,
)

SOURCE = ROOT / 'internal/senior-high/source-images/function-representations-planning-20261030/source-image-06.png'
OUTPUT = ROOT / 'site/assets/question-figures/fr-t2-b09'
CROP = (95, 914, 1160, 1222)
OPTIONS = [(145, 974, 385, 1219), (432, 974, 658, 1210), (672, 973, 895, 1203), (925, 965, 1145, 1190)]


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with Image.open(SOURCE) as page:
        page.crop(CROP).save(OUTPUT / 'original.png')
    # Build without trusting a previous generated manifest, so edits are reproducible.
    from hashlib import sha256
    manifest = {'schema_version': 'question-figures/v1', 'source': {
        'sha256': sha256((OUTPUT / 'original.png').read_bytes()).hexdigest(),
        'width': CROP[2] - CROP[0], 'height': CROP[3] - CROP[1], 'quality': 'original'},
        'figures': [{'id': 'original', 'role': 'source', 'scope_ref': '/root', 'box': [0, 0, 1, 1]}]}
    for label, region in zip('ABCD', OPTIONS, strict=True):
        box = [(value - CROP[i % 2]) / (CROP[2 + i % 2] - CROP[i % 2]) for i, value in enumerate(region)]
        manifest['figures'].append({'id': f'option-{label.lower()}', 'role': 'option',
            'scope_ref': '/root', 'target_ref': '/root/goals/0', 'option_id': f'option-{label.lower()}', 'label': label, 'box': box})
    validate_manifest(manifest, manifest['source'])
    (OUTPUT / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    assert manifest_for(OUTPUT) == manifest
    for row in manifest['figures'][1:]:
        (OUTPUT / f"{row['id']}.png").write_bytes(image_bytes(OUTPUT, row['id']))
    transport = {**manifest, 'content_id': presentation_identity(manifest), 'figures': [
        {**row, 'image_url': f"/assets/question-figures/fr-t2-b09/{row['id']}.png"} for row in manifest['figures']]}
    (OUTPUT / 'display.json').write_text(json.dumps(transport, ensure_ascii=False, indent=2) + '\n')
    print('Built B09 original crop and four options; no solution or answer metadata exported.')


if __name__ == '__main__':
    main()
