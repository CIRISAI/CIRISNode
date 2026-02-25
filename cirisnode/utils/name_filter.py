"""Banned-word filter for user-facing names (agent profiles, display names, etc.).

Checks for whole-word matches against a common blocklist. Case-insensitive.
Catches basic leet-speak substitutions (e.g. @→a, 0→o, 1→i, 3→e, 5→s).
"""

import re

# Common slurs, profanity, and objectionable terms. Whole-word matched so
# legitimate substrings (e.g. "assist", "grape", "password") are not blocked.
_BANNED_WORDS: set[str] = {
    # -- Profanity --
    "fuck", "shit", "ass", "asshole", "bitch", "bastard", "damn", "cunt",
    "dick", "cock", "piss", "crap", "douche", "wanker", "twat", "bollocks",
    # -- Slurs (racial / ethnic / gender / orientation) --
    "nigger", "nigga", "chink", "spic", "kike", "gook", "wetback",
    "beaner", "raghead", "towelhead", "cracker", "honky",
    "faggot", "fag", "dyke", "tranny", "shemale", "retard", "retarded",
    # -- Violent / threatening --
    "kill", "murder", "rape", "molest", "terrorist", "bomb",
    # -- Sexual --
    "porn", "hentai", "dildo", "blowjob", "handjob",
}

# Leet-speak substitution map (character → canonical letter)
_LEET_MAP: dict[str, str] = {
    "@": "a",
    "0": "o",
    "1": "i",
    "3": "e",
    "5": "s",
    "7": "t",
    "$": "s",
    "!": "i",
}

_LEET_TRANS = str.maketrans(_LEET_MAP)


def _normalize(text: str) -> str:
    """Lowercase, apply leet-speak reversal, collapse non-alpha to spaces."""
    text = text.lower().translate(_LEET_TRANS)
    return re.sub(r"[^a-z]+", " ", text)


def check_banned_words(name: str) -> str | None:
    """Return the first banned word found in *name*, or None if clean."""
    words = _normalize(name).split()
    for w in words:
        if w in _BANNED_WORDS:
            return w
    return None
