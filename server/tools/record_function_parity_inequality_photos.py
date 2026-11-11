"""Fresh OCR, model review and lesson API acceptance of the original FP-T4 photos."""

from tools.record_function_monotonicity_inequality_photos import REPO, main

SOURCES = REPO / 'internal/senior-high/source-images/function-parity-planning-20261110'
# Complete printed questions, including both goals of A05/A11 and handwriting.
# These rectangles only select source pixels; no gold or authored candidate is
# supplied to extraction, review, recognition or the solver.
CASES = {
    'a02': (1, [110, 195, 1140, 280]),
    'a05': (1, [110, 490, 1160, 625]),
    'a11': (1, [110, 1392, 1180, 1515]),
    'a18': (2, [110, 722, 1100, 864]),
    'a19': (2, [118, 903, 1150, 998]),
    'a20': (2, [118, 1060, 1165, 1218]),
}


if __name__ == '__main__':
    main(cases=CASES, sources=SOURCES, request_prefix='fp-t4-photo', continue_on_error=True)
