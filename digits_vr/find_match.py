# SPDX-License-Identifier: GPL-3.0-or-later
"""Find: which items match a typed name (pure Python, no bpy; tested headless and in plain Python).
Every word of the query must appear in the name (any order, any case). Better matches come first: a whole name, then a
name that starts with the word, then a word inside the name, then any part of it. Items come in three groups, always in
this order: objects, bones, collections. The result is ONE flat list with a header row before each group that has items."""
from dataclasses import dataclass

OBJECT, BONE, COLLECTION, HEADER = 'O', 'B', 'C', 'H'
GROUP_ORDER = (OBJECT, BONE, COLLECTION)
GROUP_TITLES = {OBJECT: "Objects", BONE: "Bones of the active armature", COLLECTION: "Collections"}
MAX_PER_GROUP = 60          # more matches than this are never shown (type more letters)
WORD_BREAKS = " _-.:"


@dataclass(frozen=True)
class Item:
    kind: str               # OBJECT, BONE or COLLECTION (HEADER only in a result)
    key: str                # object / collection name_full, or the bone name
    label: str              # what the row shows
    icon: str = ""
    owner: str = ""         # a bone: name_full of its armature object


def words_of(query):
    return query.lower().split()


def _word_rank(word, name, lower):
    """0 whole name, 1 starts with it, 2 starts a word of the name, 3 inside the name, None absent."""
    position = lower.find(word)
    if position < 0:
        return None
    if lower == word:
        return 0
    if position == 0:
        return 1
    while position >= 0:
        if name[position - 1] in WORD_BREAKS or (name[position - 1].islower() and name[position].isupper()):
            return 2
        position = lower.find(word, position + 1)
    return 3


def score(words, name):
    """(rank sum, name length) of `name` for the query `words`, or None when a word is missing. Lower is better."""
    lower, total = name.lower(), 0
    for word in words:
        rank = _word_rank(word, name, lower)
        if rank is None:
            return None
        total += rank
    return total, len(name)


def search(query, items, per_group=MAX_PER_GROUP):
    """The matching items, best first, with a HEADER item before each non-empty group. Empty query: nothing."""
    words = words_of(query)
    if not words:
        return []
    found = {kind: [] for kind in GROUP_ORDER}
    for item in items:
        rank = score(words, item.label)
        if rank is not None and item.kind in found:
            found[item.kind].append((rank, item.label.lower(), item))
    result = []
    for kind in GROUP_ORDER:
        group = sorted(found[kind], key=lambda entry: entry[:2])[:per_group]
        if group:
            result.append(Item(HEADER, kind, GROUP_TITLES[kind] + ("" if len(found[kind]) == len(group)
                                                                    else " (first %d)" % len(group))))
            result.extend(entry[2] for entry in group)
    return result


def counts(matches):
    """How many real items (no headers) a result holds."""
    return sum(item.kind != HEADER for item in matches)
