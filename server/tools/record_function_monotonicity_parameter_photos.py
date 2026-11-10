"""Record fresh T4 source-photo OCR, review, and owned lesson API calls.

These are development source photos, not unseen camera/lighting holdouts.
Crop coordinates identify printed questions; no expected answers enter a request.
"""

from tools.record_function_monotonicity_inequality_photos import main

CASES = {
    'a05': (1, [190, 770, 1130, 865]),
    'a06': (1, [190, 915, 1180, 1008]),
    'a08': (1, [180, 1280, 1240, 1390]),
    'a09': (1, [175, 1460, 1240, 1590]),
    'a10': (2, [105, 165, 1130, 265]),
    'a11': (2, [110, 290, 1150, 360]),
    'a13': (2, [125, 515, 1170, 650]),
    'a17': (2, [140, 1095, 1205, 1260]),
}


if __name__ == '__main__':
    main(cases=CASES, request_prefix='t4-photo')
