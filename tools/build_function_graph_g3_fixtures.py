"""Export B09-v2's original pictures, never its next-page analysis.

The right end of D is obscured by the page bend. Preserve those pixels; the
authored facts only use its visible left corner on the x axis to exclude it.
"""
import json
import sys
from hashlib import sha256
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
from shuxueshuo_server.search.figures import (
    MANIFEST,
    image_bytes,
    presentation_identity,
    validate_manifest,
)


def main():
    source = ROOT / 'internal/senior-high/source-images/function-representations-planning-20261030/source-image-07.png'
    output = ROOT / 'site/assets/question-figures/fr-t2-b09-v2'
    crop = (178, 1307, 1264, 1688)
    regions = [(191, 1378, 458, 1656), (481, 1380, 715, 1666),
               (748, 1394, 1064, 1685), (1065, 1385, 1262, 1680)]
    output.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as page:
        page.crop(crop).save(output / 'original.png')
    manifest = {'schema_version': 'question-figures/v1', 'source': {
        'sha256': sha256((output / 'original.png').read_bytes()).hexdigest(),
        'width': crop[2]-crop[0], 'height': crop[3]-crop[1], 'quality': 'original'},
        'figures': [{'id': 'original', 'role': 'source', 'scope_ref': '/root', 'box': [0, 0, 1, 1]}]}
    for label, region in zip('ABCD', regions, strict=True):
        box = [(v-crop[i % 2])/(crop[2+i % 2]-crop[i % 2]) for i, v in enumerate(region)]
        manifest['figures'].append({'id': f'option-{label.lower()}', 'role': 'option', 'scope_ref': '/root',
            'target_ref': '/root/goals/0', 'option_id': f'option-{label.lower()}', 'label': label, 'box': box})
    validate_manifest(manifest, manifest['source'])
    (output / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    for row in manifest['figures'][1:]:
        (output / f"{row['id']}.png").write_bytes(image_bytes(output, row['id']))
    display = {**manifest, 'content_id': presentation_identity(manifest), 'figures': [
        {**row, 'image_url': f"/assets/question-figures/fr-t2-b09-v2/{row['id']}.png"} for row in manifest['figures']]}
    (output / 'display.json').write_text(json.dumps(display, ensure_ascii=False, indent=2)+'\n')
    print('Built original B09-v2 figures; page-bend pixels preserved, no option reconstructed.')


if __name__ == '__main__':
    main()
