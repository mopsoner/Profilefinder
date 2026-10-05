import math
import re

def grid_points(lat, lng, radius, rings=1):
    points = [(lat, lng)]
    step = max(300, min(radius * .8, 1500))
    for ring in range(1, rings + 1):
        distance = step * ring
        for bearing in range(0, 360, 45):
            angle = math.radians(bearing)
            points.append((lat + distance * math.cos(angle) / 111320,
                lng + distance * math.sin(angle) / (111320 * max(math.cos(math.radians(lat)), .1))))
    return points

def normalize_phone(raw):
    digits = re.sub(r"\D", "", raw or "")
    if raw and raw.strip().startswith("+") and 8 <= len(digits) <= 15:
        return digits
    if len(digits) == 10 and digits.startswith("0"):
        return "33" + digits[1:]
    return digits if 8 <= len(digits) <= 15 else None

def score(reviews, website, phone):
    reviews=max(0,reviews or 0)
    # Commercial priority: an established business with social proof but no
    # website is a stronger website prospect than a business with no reviews.
    review_points=min(5,reviews // 10)
    return (10 if not website else 0) + review_points + (1 if phone else 0)
