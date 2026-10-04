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
            " First and last name are available when an event collects the name "
            "in parts, e.g. {name_given_name} and {name_family_name}."
        )
    else:
        names = sorted(
            "{%s}" % key
            for key in get_available_placeholders(
                event, ["event", "order", "position_or_address"]
            )
            if key.startswith("name_") and key != "name_for_salutation"
        )
        if names:
            parts = _(" This event's name parts (e.g. first and last name): {names}.").format(
                names=", ".join(names)
            )
        else:
            parts = _(" This event only collects a full name, so only {name} is available.")
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
