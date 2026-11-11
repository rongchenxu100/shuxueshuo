"""Fresh OCR, model review and lesson API acceptance of the original T1 photo."""

from tools.record_function_monotonicity_inequality_photos import REPO, main

SOURCES = REPO / 'internal/senior-high/source-images/function-parity-planning-20261110'
# The entire printed question, including both subquestions and handwritten marks.
# Only source pixels are sent; expected parity and authored candidates are not inputs.
CASES = {'a01': (1, [110, 103, 1065, 180])}


if __name__ == '__main__':
    main(cases=CASES, sources=SOURCES, request_prefix='fp-t1-photo', continue_on_error=True)
