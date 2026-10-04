from django import forms
from django.utils.translation import gettext_lazy as _

from pretix.base.email import get_available_placeholders

from pretix_attendance_certificate.models import AttendanceCertificateLayout


def placeholder_help(event=None):
    """Help text listing what can be used in a template's subject and text.

    With an event the name-part placeholders are the ones its name scheme
    really offers (pretix generates them, e.g. {name_given_name}); without one
    (organizer-wide templates) the common scheme is given as an example.
    """
    text = _(
        "Placeholders: {event} (event name), {name} (attendee's full name), "
        "{name_for_salutation} (name as used in a salutation, e.g. \"Mr Doe\"), "
        "{code} (order code), {url} (link to the order page)."
    )
    if event is None:
        parts = _(
            " Heads-up: {name_given_name} (first name) and {name_family_name} "
            "(last name) only exist for events that collect the name in parts. "
            "For any other event they are sent as literal text, so use {name} "
            "if the template is shared between events."
        )
    else:
        labels = {
            "{name_given_name}": _("first name"),
            "{name_family_name}": _("last name"),
            "{name_title}": _("title"),
        }
        names = sorted(
            "{%s}" % key
            for key in get_available_placeholders(
                event, ["event", "order", "position_or_address"]
            )
            if key.startswith("name_") and key != "name_for_salutation"
        )
        if names:
            parts = _(" Name parts of this event: {names}.").format(
                names=", ".join(
                    "%s (%s)" % (n, labels[n]) if n in labels else n for n in names
                )
            )
        else:
            parts = _(
                " Heads-up: this event only collects a full name, so "
                "{name_given_name} (first name) is not available here - it would "
                "be sent as literal text. Use {name}."
            )
    note = _(
        " Answers to registration questions are not available here - put them "
        "on the certificate itself in the layout editor."
    )
    return text + parts + note


class OrganizerLayoutForm(forms.ModelForm):
    class Meta:
        model = AttendanceCertificateLayout
        fields = ["name", "mail_subject", "mail_text"]

    def __init__(self, *args, **kwargs):
        locales = kwargs.pop("locales", None)
        event = kwargs.pop("event", None)
        super().__init__(*args, **kwargs)
        help_text = placeholder_help(event)
        # I18nCharField/I18nTextField build one sub-field per locale in
        # settings.LANGUAGES by default (dozens) unless told otherwise - a
        # plain ModelForm has no event/organizer to infer that from, so the
        # view passes the right locale list in explicitly.
        if locales:
            for fname in ("mail_subject", "mail_text"):
                field = self.fields[fname]
                self.fields[fname] = field.__class__(
                    locales=locales,
                    widget=field.widget.__class__,
                    label=field.label,
                    required=field.required,
                )
        for fname in ("mail_subject", "mail_text"):
            self.fields[fname].help_text = help_text
