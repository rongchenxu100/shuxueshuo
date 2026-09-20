"""Explicit wire-version dispatch; never infer a contract from a model response."""

from .notation_contract import CONTRACT


def components(contract):
    if contract == CONTRACT:
        from . import notation_contract as prompt
        from .notation_compile import NotationValidator as Validator
        from .notation_semantics import compare, evaluate
        from .notation_service import parse_candidate, render
    else:
        raise ValueError("unsupported extraction contract: " + str(contract))
    return prompt, Validator, compare, evaluate, parse_candidate, render
