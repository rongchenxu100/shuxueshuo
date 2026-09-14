"""Offline gates for the scoped few-shot protocol used by all live cases."""
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from _functional_opt_in_support import _assert_v2_few_shot
from shuxueshuo_server.solver.runtime.scoped_functional_few_shots import (
    default_scoped_functional_few_shot_dir, _plan_capability_ids,
)


def payload():
    path = next(default_scoped_functional_few_shot_dir().glob('*.functional-few-shot.json'))
    asset = json.loads(path.read_text())
    return {
        'functional_few_shot_selection': {
            'mode': 'v2_capability_subset', 'example_id': asset['example_id'],
            'asset_sha256': sha256(path.read_bytes()).hexdigest(),
        },
        'few_shot_examples': [{k: v for k, v in asset.items() if k != 'example_id'}],
        'functional_capability_catalog': {'capabilities': [
            {'capability_id': key} for key in _plan_capability_ids(asset['plan'])
        ]},
    }


def test_registered_scoped_mechanism_passes_without_legacy_source_metadata():
    _assert_v2_few_shot(payload())


@pytest.mark.parametrize('mutation', ['hash', 'example', 'capabilities', 'mode'])
def test_gate_rejects_drift_and_unavailable_capabilities(mutation):
    value = deepcopy(payload())
    if mutation == 'hash':
        value['functional_few_shot_selection']['asset_sha256'] = 'wrong'
    elif mutation == 'example':
        value['few_shot_examples'][0]['source_problem_id'] = 'target-problem'
    elif mutation == 'capabilities':
        value['functional_capability_catalog']['capabilities'] = []
    else:
        value['functional_few_shot_selection']['mode'] = 'strict_test'
    with pytest.raises(AssertionError):
        _assert_v2_few_shot(value)
