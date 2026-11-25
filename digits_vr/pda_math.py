# SPDX-License-Identifier: GPL-3.0-or-later
"""The PDA's layout data without bpy (DESIGN "Personal PDA"): tabs of slots, each slot a LINK (a desk widget id, "" =
blank). Plain tuples, so equal layouts compare equal and the settings JSON stores them as lists. Every change returns a
new layout; a bad request returns the layout unchanged. Tested headless."""
SLOTS_PER_TAB = 10
MAX_TABS = 40
NAME_LENGTH = 16
DEFAULT_NAME = "Tab"
EMPTY = ()                       # no tabs: the PDA starts blank


def valid(value):
    """The settings check: a list of [name, [link, ...]] (any number of tabs up to MAX_TABS)."""
    return isinstance(value, list) and len(value) <= MAX_TABS and all(
        isinstance(tab, list) and len(tab) == 2 and isinstance(tab[0], str) and len(tab[0]) <= NAME_LENGTH
        and isinstance(tab[1], list) and len(tab[1]) == SLOTS_PER_TAB and all(isinstance(link, str) for link in tab[1])
        for tab in value)


def from_settings(value):
    return tuple((name, tuple(links)) for name, links in value) if valid(value) else EMPTY


def to_settings(tabs):
    return [[name, list(links)] for name, links in tabs]


def blank_tab(name):
    return (name, ("",) * SLOTS_PER_TAB)


def clean_name(text, fallback):
    return text.strip()[:NAME_LENGTH] or fallback


def new_name(tabs):
    """"Tab 1", "Tab 2", ...: the first not in use."""
    used = {name for name, _links in tabs}
    return next(name for name in (f"{DEFAULT_NAME} {number}" for number in range(1, MAX_TABS + 2)) if name not in used)


def add_tab(tabs):
    return tabs + (blank_tab(new_name(tabs)),) if len(tabs) < MAX_TABS else tabs


def rename_tab(tabs, index, text):
    if not 0 <= index < len(tabs):
        return tabs
    name, links = tabs[index]
    return tabs[:index] + ((clean_name(text, name), links),) + tabs[index + 1:]


def delete_tab(tabs, index):
    return tabs[:index] + tabs[index + 1:] if 0 <= index < len(tabs) else tabs


def set_slot(tabs, index, slot, link):
    if not (0 <= index < len(tabs) and 0 <= slot < SLOTS_PER_TAB):
        return tabs
    name, links = tabs[index]
    return tabs[:index] + ((name, links[:slot] + (link,) + links[slot + 1:]),) + tabs[index + 1:]


def clear_slot(tabs, index, slot):
    return set_slot(tabs, index, slot, "")


def move_slot(tabs, index, slot, step):
    """Swap a slot with its neighbour `step` (-1 earlier, +1 later) in the same tab; returns (tabs, the slot's new place)."""
    target = slot + step
    if not (0 <= index < len(tabs) and 0 <= slot < SLOTS_PER_TAB and 0 <= target < SLOTS_PER_TAB):
        return tabs, slot
    name, links = tabs[index]
    swapped = list(links)
    swapped[slot], swapped[target] = swapped[target], swapped[slot]
    return tabs[:index] + ((name, tuple(swapped)),) + tabs[index + 1:], target


def step_tab(count, current, step):
    """The tab `step` away, wrapping round; 0 when there are none."""
    return (current + step) % count if count else 0


def mapped_pixel_x(slot, target, pixel_x, padding=22):
    """A slider pressed at `pixel_x` on the PDA's slider `slot`: the same place along the track of the desk's `target`."""
    fraction = (pixel_x - slot.x - padding) / max(1.0, slot.w - 2 * padding)
    return target.x + padding + min(1.0, max(0.0, fraction)) * (target.w - 2 * padding)
