"""Fresh OCR, model review and lesson API acceptance of the original FP-T3 photos."""

from tools.record_function_monotonicity_inequality_photos import REPO, main

SOURCES = REPO / 'internal/senior-high/source-images/function-parity-planning-20261110'
# Complete printed questions, retaining handwriting. Only original pixels enter
# extraction/review; mathematical gold and authored candidates are not inputs.
# A05 and A11 also ask T4 inequalities, so they are not complete T3 cases.
CASES = {
    'a03': (1, [110, 280, 1140, 370]),
    'a04': (1, [110, 374, 1160, 490]),
    'a06': (1, [110, 630, 1185, 744]),
    'a07': (1, [110, 750, 1140, 846]),
    'a08': (1, [110, 852, 1140, 933]),
    'a09': (1, [110, 935, 1140, 1075]),
    'a12': (2, [110, 99, 1090, 190]),
    'a13': (2, [110, 192, 970, 270]),
    'a15': (2, [110, 445, 1060, 523]),
}


if __name__ == '__main__':
    main(cases=CASES, sources=SOURCES, request_prefix='fp-t3-photo', continue_on_error=True)
