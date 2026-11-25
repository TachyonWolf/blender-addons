# SPDX-License-Identifier: GPL-3.0-or-later
"""Saved viewpoints ("spots"): a list kept per .blend file as JSON text in one scene custom property (user data:
it is saved with the file on purpose). Pure Python (no bpy), tested headless. Each spot is one dict:
{"name", "location" [3], "rotation" [4] (navigation quaternion w x y z), "size" (your size)}."""
import json
import re

NAME_PATTERN = re.compile(r"^Spot (\d+)$")


def _valid(spot):
    def numbers(value, count):
        return isinstance(value, list) and len(value) == count and all(
            isinstance(item, (int, float)) and not isinstance(item, bool) for item in value)
    return (isinstance(spot, dict) and isinstance(spot.get("name"), str) and numbers(spot.get("location"), 3)
            and numbers(spot.get("rotation"), 4) and isinstance(spot.get("size"), (int, float)) and spot["size"] > 0)


def parse(text):
    """The spots in a stored text; broken data gives the good entries only (never raises)."""
    try:
        data = json.loads(text) if text else []
    except (TypeError, ValueError):
        print("Digit's VR: the saved viewpoints could not be read; starting with none")
        return []
    if not isinstance(data, list):
        return []
    return [spot for spot in data if _valid(spot)]


def dump(spots):
    return json.dumps(spots)


def next_name(spots):
    """"Spot N", one more than the highest Spot number in use."""
    numbers = [int(match.group(1)) for match in (NAME_PATTERN.match(spot["name"]) for spot in spots) if match]
    return "Spot %d" % (max(numbers, default=0) + 1)


def add(spots, location, rotation, size):
    """A new list with the spot added at the end."""
    spot = {"name": next_name(spots), "location": [float(value) for value in location],
            "rotation": [float(value) for value in rotation], "size": float(size)}
    return spots + [spot]


def clean_name(name):
    """A name for a spot: spaces trimmed, at most 40 characters; "" when nothing is left."""
    return " ".join(str(name).split())[:40]


def rename(spots, index, name):
    """A new list with spot `index` renamed (out of range or an empty name: unchanged)."""
    name = clean_name(name)
    if not 0 <= index < len(spots) or not name:
        return spots
    return [dict(spot, name=name) if position == index else spot for position, spot in enumerate(spots)]


def delete(spots, index):
    """A new list without spot `index` (out of range: unchanged)."""
    return [spot for position, spot in enumerate(spots) if position != index]
