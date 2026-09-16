"""Exact revision preserves original order and spelling; semantics uses compiled IR."""

import json
from hashlib import sha256


def encoded(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def revision(value):
    return sha256(encoded(value)).hexdigest()
