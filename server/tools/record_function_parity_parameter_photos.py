"""Fresh OCR, model review and lesson API acceptance of the original T2 photo."""

from tools.record_function_monotonicity_inequality_photos import REPO, main

SOURCES = REPO / 'internal/senior-high/source-images/function-parity-planning-20261110'
# Complete printed A17, retaining the handwritten answer. No answer or authored
# candidate is sent to the OCR, extraction or review services.
CASES = {'a17': (2, [110, 630, 1060, 715])}


if __name__ == '__main__':
    main(cases=CASES, sources=SOURCES, request_prefix='fp-t2-photo', continue_on_error=True)
