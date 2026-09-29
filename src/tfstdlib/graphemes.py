"""Extended grapheme cluster segmentation (Unicode UAX #29, no Indic conjunct rule).

Terraform counts and slices strings by grapheme cluster in ``length``,
``substr`` and ``strrev``. Python has no segmenter, so this module implements
the UAX #29 rules from ``unicodedata`` categories plus small range tables for
the properties that ``unicodedata`` does not expose (Extended_Pictographic,
Prepend, Hangul syllable types). It follows Unicode 13-era rules as used by
cty's ``textseg``; characters added to those properties after that version may
segment differently.
"""

from __future__ import annotations

import unicodedata
from bisect import bisect_right

# Extended_Pictographic ranges (approximate, from emoji-data.txt)
_EXT_PICT = [
    (0x00A9, 0x00A9), (0x00AE, 0x00AE), (0x203C, 0x203C), (0x2049, 0x2049), (0x2122, 0x2122), (0x2139, 0x2139),
    (0x2194, 0x2199), (0x21A9, 0x21AA), (0x231A, 0x231B), (0x2328, 0x2328), (0x2388, 0x2388), (0x23CF, 0x23CF),
    (0x23E9, 0x23F3), (0x23F8, 0x23FA), (0x24C2, 0x24C2), (0x25AA, 0x25AB), (0x25B6, 0x25B6), (0x25C0, 0x25C0),
    (0x25FB, 0x25FE), (0x2600, 0x2605), (0x2607, 0x2612), (0x2614, 0x2685), (0x2690, 0x2705), (0x2708, 0x2712),
    (0x2714, 0x2714), (0x2716, 0x2716), (0x271D, 0x271D), (0x2721, 0x2721), (0x2728, 0x2728), (0x2733, 0x2734),
    (0x2744, 0x2744), (0x2747, 0x2747), (0x274C, 0x274C), (0x274E, 0x274E), (0x2753, 0x2755), (0x2757, 0x2757),
    (0x2763, 0x2767), (0x2795, 0x2797), (0x27A1, 0x27A1), (0x27B0, 0x27B0), (0x27BF, 0x27BF), (0x2934, 0x2935),
    (0x2B05, 0x2B07), (0x2B1B, 0x2B1C), (0x2B50, 0x2B50), (0x2B55, 0x2B55), (0x3030, 0x3030), (0x303D, 0x303D),
    (0x3297, 0x3297), (0x3299, 0x3299), (0x1F000, 0x1F0FF), (0x1F10D, 0x1F10F), (0x1F12F, 0x1F12F),
    (0x1F16C, 0x1F171), (0x1F17E, 0x1F17F), (0x1F18E, 0x1F18E), (0x1F191, 0x1F19A), (0x1F1AD, 0x1F1E5),
    (0x1F201, 0x1F20F), (0x1F21A, 0x1F21A), (0x1F22F, 0x1F22F), (0x1F232, 0x1F23A), (0x1F23C, 0x1F23F),
    (0x1F249, 0x1F3FA), (0x1F400, 0x1F53D), (0x1F546, 0x1F64F), (0x1F680, 0x1F6FF), (0x1F774, 0x1F77F),
    (0x1F7D5, 0x1F7FF), (0x1F80C, 0x1F80F), (0x1F848, 0x1F84F), (0x1F85A, 0x1F85F), (0x1F888, 0x1F88F),
    (0x1F8AE, 0x1F8FF), (0x1F90C, 0x1F93A), (0x1F93C, 0x1F945), (0x1F947, 0x1FAFF), (0x1FC00, 0x1FFFD),
]
_EXT_PICT_STARTS = [a for a, _ in _EXT_PICT]

_PREPEND = {0x0600, 0x0601, 0x0602, 0x0603, 0x0604, 0x0605, 0x06DD, 0x070F, 0x08E2, 0x0D4E, 0x110BD, 0x110CD, 0x111C2, 0x111C3}

# GCB values
CR, LF, CONTROL, EXTEND, ZWJ, RI, PREPEND, SPACING, L, V, T, LV, LVT, EXTPICT, OTHER = range(15)


def _in_ext_pict(cp: int) -> bool:
    i = bisect_right(_EXT_PICT_STARTS, cp) - 1
    return i >= 0 and cp <= _EXT_PICT[i][1]


def _gcb(ch: str) -> int:
    cp = ord(ch)
    if cp == 0x0D:
        return CR
    if cp == 0x0A:
        return LF
    if cp == 0x200D:
        return ZWJ
    if cp == 0x200C:
        return EXTEND
    if 0x1F1E6 <= cp <= 0x1F1FF:
        return RI
    if cp in _PREPEND:
        return PREPEND
    if 0x1F3FB <= cp <= 0x1F3FF:
        return EXTEND
    if 0xE0020 <= cp <= 0xE007F:
        return EXTEND
    if 0x1100 <= cp <= 0x115F or 0xA960 <= cp <= 0xA97C:
        return L
    if 0x1160 <= cp <= 0x11A7 or 0xD7B0 <= cp <= 0xD7C6:
        return V
    if 0x11A8 <= cp <= 0x11FF or 0xD7CB <= cp <= 0xD7FB:
        return T
    if 0xAC00 <= cp <= 0xD7A3:
        return LV if (cp - 0xAC00) % 28 == 0 else LVT
    cat = unicodedata.category(ch)
    if cat in ("Mn", "Me"):
        return EXTEND
    if cat == "Mc":
        return SPACING
    if cat in ("Cc", "Zl", "Zp") or (cat == "Cf" and cp not in (0x200C, 0x200D)):
        return CONTROL
    if _in_ext_pict(cp):
        return EXTPICT
    return OTHER


def split_graphemes(s: str) -> list[str]:
    """Split ``s`` into extended grapheme clusters."""
    if not s:
        return []
    out: list[str] = []
    start = 0
    n = len(s)
    prev = _gcb(s[0])
    ri_run = 1 if prev == RI else 0
    for i in range(1, n):
        cur = _gcb(s[i])
        brk = True
        if prev == CR and cur == LF:
            brk = False
        elif prev in (CONTROL, CR, LF) or cur in (CONTROL, CR, LF):
            brk = True
        elif prev == L and cur in (L, V, LV, LVT):
            brk = False
        elif prev in (LV, V) and cur in (V, T):
            brk = False
        elif prev in (LVT, T) and cur == T:
            brk = False
        elif cur in (EXTEND, ZWJ):
            brk = False
        elif cur == SPACING:
            brk = False
        elif prev == PREPEND:
            brk = False
        elif prev == ZWJ and cur == EXTPICT and pict_seq_before_zwj(s, i, start):
            brk = False
        elif prev == RI and cur == RI and ri_run % 2 == 1:
            brk = False
        if brk:
            out.append(s[start:i])
            start = i
        ri_run = ri_run + 1 if cur == RI else 0
        prev = cur
    out.append(s[start:])
    return out


def pict_seq_before_zwj(s: str, i: int, start: int) -> bool:
    """GB11: the ZWJ at ``i-1`` is preceded by ExtPict Extend* within this cluster."""
    j = i - 2
    while j >= start and _gcb(s[j]) == EXTEND:
        j -= 1
    return j >= start and _gcb(s[j]) == EXTPICT


def grapheme_count(s: str) -> int:
    return len(split_graphemes(s))
