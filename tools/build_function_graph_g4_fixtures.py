"""Crop the given schematic and four original choices; omit printed analysis."""
import json
import sys
from hashlib import sha256
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'server'))
from shuxueshuo_server.search.figures import image_bytes, presentation_identity, validate_manifest


def main():
    source = ROOT/'internal/senior-high/source-images/function-representations-planning-20261030/source-image-08.png'
    output = ROOT/'site/assets/question-figures/fr-t2-b09-v3'
    output.mkdir(parents=True, exist_ok=True)
    crop = (125, 350, 1160, 805)
    regions = [('given-graph', (525, 417, 759, 575)),
               ('option-a', (157, 593, 390, 799)), ('option-b', (412, 587, 632, 799)),
               ('option-c', (667, 580, 906, 796)), ('option-d', (922, 571, 1140, 793))]
    with Image.open(source) as page:
        page.crop(crop).save(output/'original.png')
    manifest = {'schema_version': 'question-figures/v1', 'source': {
        'sha256': sha256((output/'original.png').read_bytes()).hexdigest(), 'width': crop[2]-crop[0],
        'height': crop[3]-crop[1], 'quality': 'original'}, 'figures': [
        {'id': 'original', 'role': 'source', 'scope_ref': '/root', 'box': [0, 0, 1, 1]}]}
    for name, region in regions:
        row = {'id': name, 'role': 'statement' if name == 'given-graph' else 'option',
               'scope_ref': '/root', 'target_ref': '/root/goals/0',
               'box': [(v-crop[i % 2])/(crop[2+i % 2]-crop[i % 2]) for i, v in enumerate(region)]}
        if row['role'] == 'option':
            row.update(option_id=name, label=name[-1].upper())
        manifest['figures'].append(row)
    validate_manifest(manifest, manifest['source'])
    (output/'question-figures.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    for row in manifest['figures'][1:]:
        (output/f'{row["id"]}.png').write_bytes(image_bytes(output, row['id']))
    display = {**manifest, 'content_id': presentation_identity(manifest), 'figures': [
        {**row, 'image_url': f'/assets/question-figures/fr-t2-b09-v3/{row["id"]}.png'} for row in manifest['figures']]}
    (output/'display.json').write_text(json.dumps(display, ensure_ascii=False, indent=2)+'\n')
    record = json.loads((ROOT/'internal/senior-high/authored-courses/function-graph-g4-20261102/b09-v3.json').read_text())
    course = {'schemaVersion': 1, 'problemId': record['problem_id'], 'title': '图像变换法 · 例 9 变式 3',
              'page': '/topics/function-representations/q09d/', 'topicHref': '/topics/function-representations/',
              'targetRef': '/root/goals/0', 'statement': record['candidate']['original_text'],
              'evidence': 'site/data/graph-walk/function-representations-b09-v3.evidence.json', 'figures': display}
    (ROOT/'site/data/graph-walk/function-representations-b09-v3.source.json').write_text(json.dumps(course, ensure_ascii=False, indent=2)+'\n')
    print('Built B09-v3 original schematic and choices; no replacement function or analysis crop.')


if __name__ == '__main__':
    main()
