"""Fresh OCR, model review and lesson API acceptance of the five FP-T6 photos."""

from tools.record_function_monotonicity_inequality_photos import REPO, main

SOURCES = REPO / 'internal/senior-high/source-images'
SOURCE_FILES = {
    1: SOURCES / 'function-parity-planning-20261110/source-image-02.jpg',
    2: SOURCES / 'function-parity-t6-planning-20261112/source-page-01.png',
}
# Original pixels only. Textbook labels and nearby solutions are not instructions;
# neither authored candidates nor gold answers are sent to extraction/review.
CASES = {
    'a16': (1, [110, 545, 1110, 625]),
    'b01': (2, [100, 103, 1020, 218]),
    'b02': (2, [108, 482, 1070, 574]),
    'b03': (2, [105, 901, 1155, 986]),
    'b04': (2, [104, 1384, 1242, 1516]),
}


if __name__ == '__main__':
    main(cases=CASES, source_files=SOURCE_FILES, request_prefix='fp-t6-photo', continue_on_error=True)
