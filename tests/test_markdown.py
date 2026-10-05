import json
from io import BytesIO

import pytest
from django_scopes import scopes_disabled

from pretix_attendance_certificate.markdown_text import to_markers, to_markup
from pretix_attendance_certificate.render import render_certificate


def convert(text):
    return str(to_markup(to_markers(text)))


@pytest.mark.parametrize(
    "source, expected",
    [
        ("**bold**", "<b>bold</b>"),
        ("__bold__", "<b>bold</b>"),
        ("*italic*", "<i>italic</i>"),
        ("_italic_", "<i>italic</i>"),
        ("***both***", "<b><i>both</i></b>"),
        ("~~gone~~", "<strike>gone</strike>"),
        ("++under++", "<u>under</u>"),
        ("**bold *it* more**", "<b>bold <i>it</i> more</b>"),
        ("a **b** c *d* e", "a <b>b</b> c <i>d</i> e"),
        # not formatting
        ("2 * 3 * 4", "2 * 3 * 4"),
        ("snake_case_word", "snake_case_word"),
        ("**open", "**open"),
        ("** spaced **", "** spaced **"),
        # placeholders contain underscores and must survive untouched
        ("_{name_for_salutation}_ {question_COURSE}", "<i>{name_for_salutation}</i> {question_COURSE}"),
        # escaping
        (r"\*literal\* \_x\_ \\", r"*literal* _x_ \\".replace("\\\\", "\\")),
        # plain text is still escaped
        ("a < b & c", "a &lt; b &amp; c"),
        ("<b>raw</b>", "&lt;b&gt;raw&lt;/b&gt;"),
        # overlapping markers: no formatting rather than broken markup
        ("*a **b* c**", "a b c"),
    ],
)
def test_conversion(source, expected):
    assert convert(source) == expected


def test_markers_in_attendee_data_cannot_unbalance_the_markup():
    from pretix_attendance_certificate import markdown_text as m

    # An attendee name carrying the private marker characters themselves.
    assert "<" not in str(to_markup("x" + m.B_ON + "y")).replace("</", "").replace("<b", "")  # noqa
    assert str(to_markup("x" + m.B_ON + "y")) == "xy"
    assert str(to_markup(m.B_OFF + "y")) == "y"


def _element(content, text="", **extra):
    element = {
        "type": "textarea", "left": "20", "bottom": "200", "fontsize": "14",
        "color": [0, 0, 0, 1], "fontfamily": "Open Sans", "bold": False,
        "italic": False, "width": "150", "content": content, "text": text,
        "align": "left",
    }
    element.update(extra)
    return element


def _render(event, pos, layout, elements):
    layout.layout = json.dumps(elements)
    layout.save()
    with scopes_disabled():
        return render_certificate(position=pos, event=event, layout=layout).read()


def _fonts(pdf):
    """Names of the embedded fonts, e.g. {"OpenSans", "OpenSans-Bold"}."""
    pypdf = pytest.importorskip("pypdf")
    page = pypdf.PdfReader(BytesIO(pdf)).pages[0]
    fonts = page["/Resources"]["/Font"]
    names = (str(fonts[n].get_object()["/BaseFont"]).lstrip("/") for n in fonts)
    return {name.split("+")[-1] for name in names}


def _text(pdf):
    pypdf = pytest.importorskip("pypdf")
    return pypdf.PdfReader(BytesIO(pdf)).pages[0].extract_text()


@pytest.mark.django_db
def test_inline_formatting_uses_the_matching_fonts(event, pos, layout):
    pdf = _render(event, pos, layout, [
        _element("other", "plain **bold** *italic* ***both***"),
    ])
    assert {"OpenSans", "OpenSans-Bold", "OpenSans-Italic", "OpenSans-BoldItalic"} <= _fonts(pdf)
    assert "bold" in _text(pdf) and "**" not in _text(pdf)


@pytest.mark.django_db
def test_inline_italic_inside_a_bold_field(event, pos, layout):
    pdf = _render(event, pos, layout, [_element("other", "x *it*", bold=True)])
    assert "OpenSans-BoldItalic" in _fonts(pdf)


@pytest.mark.django_db
def test_i18n_text_is_formatted_too(event, pos, layout):
    pdf = _render(event, pos, layout, [
        _element("other_i18n", "", text_i18n={"en": "hello **world**"}),
    ])
    assert "OpenSans-Bold" in _fonts(pdf)


@pytest.mark.django_db
def test_attendee_data_is_never_interpreted(event, order, pos, layout):
    pos.attendee_name_parts = {"_legacy": '**Eve** <b>x</b> <img src="http://127.0.0.1/a.png"/>'}
    pos.save()
    pdf = _render(event, pos, layout, [
        _element("other", "Name: {attendee_name} and **real bold**", bottom="220"),
    ])
    text = _text(pdf)
    assert "**Eve**" in text
    assert "<b>x</b>" in text
    assert "<img" in text
    assert _fonts(pdf) == {"Helvetica", "OpenSans", "OpenSans-Bold"}  # bold only from the template


@pytest.mark.django_db
def test_marker_characters_in_attendee_data_do_not_break_rendering(event, pos, layout):
    pos.attendee_name_parts = {"_legacy": "Eve \ue010 \ue011\ue011 Smith"}
    pos.save()
    pdf = _render(event, pos, layout, [_element("other", "{attendee_name} **x**")])
    assert "Eve" in _text(pdf) and "Smith" in _text(pdf)


@pytest.mark.django_db
def test_placeholder_only_fields_are_unchanged(event, pos, layout):
    pos.attendee_name_parts = {"_legacy": "*Not italic*"}
    pos.save()
    pdf = _render(event, pos, layout, [_element("attendee_name")])
    assert "*Not italic*" in _text(pdf)
    assert "OpenSans-Italic" not in _fonts(pdf)
