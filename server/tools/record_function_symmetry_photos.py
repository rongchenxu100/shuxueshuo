"""Fresh OCR, model review and lesson API acceptance of the original FP-T5 photos."""

from tools.record_function_monotonicity_inequality_photos import REPO, main

SOURCES = REPO / 'internal/senior-high/source-images/function-parity-planning-20261110'
# Complete printed questions, retaining handwriting and both goals of A10.
# Only original pixels enter extraction/review; gold and authored candidates
# are reserved for assertions after the actual model response.
CASES = {
    'a10': (1, [110, 1090, 1140, 1240]),
    'a14': (2, [110, 275, 1040, 424]),
}


if __name__ == '__main__':
    main(cases=CASES, sources=SOURCES, request_prefix='fp-t5-photo', continue_on_error=True)
