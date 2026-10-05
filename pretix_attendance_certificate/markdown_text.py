"""Inline Markdown (bold, italic, ...) for the text fields of a certificate.

pretix escapes the whole text of a field before drawing it, so there's no
formatting at all. The templates are written by organizers, but the text also
contains placeholders that get replaced by attendee-supplied data (names, ...).
Formatting must therefore only ever come from the *template* text: it is turned
into private-use marker characters *before* pretix substitutes the
placeholders, and into reportlab tags only after everything else has been
escaped. An attendee called "**x** <b>y</b>" is printed literally.

Supported (single line, like Markdown requires the markers to touch the text):
    **bold**  __bold__  *italic*  _italic_  ***both***  ~~strike~~  ++underline++
A backslash escapes a marker: \\* \\_ \\~ \\+ \\\\
"""

import re

from django.utils.html import conditional_escape
from django.utils.safestring import mark_safe

B_ON, B_OFF = "", ""
I_ON, I_OFF = "", ""
S_ON, S_OFF = "", ""
U_ON, U_OFF = "", ""
_HOLD_ON, _HOLD_OFF = "", ""

_TAGS = {
    B_ON: ("<b>", B_OFF),
    I_ON: ("<i>", I_OFF),
    S_ON: ("<strike>", S_OFF),
    U_ON: ("<u>", U_OFF),
}
_CLOSE = {B_OFF: "</b>", I_OFF: "</i>", S_OFF: "</strike>", U_OFF: "</u>"}
_ALL_MARKERS = "".join(_TAGS) + "".join(_CLOSE)

_PLACEHOLDER = re.compile(r"\{[-a-zA-Z0-9:_]+\}")
_ESCAPE = re.compile(r"\\([*_~+\\])")


def _pair(marker, on, off):
    m = re.escape(marker)
    return re.compile(r"{0}(?=\S)(.+?)(?<=\S){0}".format(m)), on, off


# Longest markers first, so that ***x*** isn't read as ** + *.
_RULES = [
    (re.compile(r"\*\*\*(?=\S)(.+?)(?<=\S)\*\*\*"), B_ON + I_ON, I_OFF + B_OFF),
    _pair("**", B_ON, B_OFF),
    (re.compile(r"(?<!\w)__(?=\S)(.+?)(?<=\S)__(?!\w)"), B_ON, B_OFF),
    _pair("~~", S_ON, S_OFF),
    _pair("++", U_ON, U_OFF),
    (re.compile(r"(?<![*\w])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![*\w])"), I_ON, I_OFF),
    (re.compile(r"(?<![\w])_(?=\S)(.+?)(?<=\S)_(?![\w])"), I_ON, I_OFF),
]


def to_markers(template_text):
    """Template text with Markdown -> text with marker characters instead."""
    held = []

    def hold(match):
        held.append(match.group(1) if match.re is _ESCAPE else match.group(0))
        return "{}{}{}".format(_HOLD_ON, len(held) - 1, _HOLD_OFF)

    # Placeholders (they contain underscores) and escaped markers are kept
    # out of the way while the formatting is parsed.
    text = _ESCAPE.sub(hold, _PLACEHOLDER.sub(hold, template_text))
    for pattern, on, off in _RULES:
        text = pattern.sub(lambda m: on + m.group(1) + off, text)
    return re.sub(
        "{}(\\d+){}".format(_HOLD_ON, _HOLD_OFF), lambda m: held[int(m.group(1))], text
    )


def to_markup(text):
    """Text that may contain markers (and attendee data) -> safe reportlab
    markup. Everything is escaped; only well-nested markers become tags,
    otherwise the text is shown without any formatting."""
    escaped = str(conditional_escape(text))
    out, stack = [], []
    for char in escaped:
        if char in _TAGS:
            tag, closer = _TAGS[char]
            out.append(tag)
            stack.append(closer)
        elif char in _CLOSE:
            if not stack or stack.pop() != char:
                return mark_safe(_strip(escaped))
            out.append(_CLOSE[char])
        else:
            out.append(char)
    if stack:
        return mark_safe(_strip(escaped))
    return mark_safe("".join(out))


def _strip(text):
    return "".join(c for c in text if c not in _ALL_MARKERS)


def convert_element(o):
    """Copy of a layout element whose free text carries markers."""
    o = dict(o)
    if o.get("content") == "other" and isinstance(o.get("text"), str):
        o["text"] = to_markers(o["text"])
    elif o.get("content") == "other_i18n":
        value = o.get("text_i18n", {})
        if isinstance(value, dict):
            o["text_i18n"] = {
                k: to_markers(v) if isinstance(v, str) else v for k, v in value.items()
            }
        elif isinstance(value, str):
            o["text_i18n"] = to_markers(value)
    return o
