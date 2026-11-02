"""Explicit topic input from a source-checked transcription, without OCR claims."""

from copy import deepcopy

from ...problem_understanding.identity import revision
from .contracts import RESULT_CONTRACT
from .extraction import validate_candidate
from .features import extract_features


def prepare_authored(candidate, *, run_id, sources, reviewer):
    """The author supplies provenance; all mathematical features are recomputed."""
    checked = validate_candidate(candidate)
    features = extract_features(candidate)
    if not checked['contract_valid'] or not features['ok']:
        raise ValueError('authored.invalid_candidate')
    provenance = {'kind': 'authored_topic', 'candidate_sha256': revision(candidate),
                  'sources': deepcopy(sources), 'reviewer': reviewer}
    result = {'contract': RESULT_CONTRACT, 'run_id': run_id, 'candidate': deepcopy(candidate),
              'features': features['features'], 'provenance': provenance,
              'statuses': {'admission': 'authored_topic', 'extraction': 'authored_candidate',
                           'author_reviewed': True, 'features': True, 'source_reviewed': False}}
    # Use the same admission checks when importing and when replaying a course.
    from ..stage_two.contracts import validate_input
    validation = validate_input(result, admission='authored_topic')
    if not validation['ok']:
        raise ValueError(f'authored.invalid_provenance: {validation["diagnostics"]}')
    return result
