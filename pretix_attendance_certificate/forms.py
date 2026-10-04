from django import forms
from django.utils.translation import gettext_lazy as _

from pretix.base.email import get_available_placeholders
from pretix.base.forms import PlaceholderValidator

from pretix_attendance_certificate.models import AttendanceCertificateLayout


ORGANIZER_PLACEHOLDER_HELP = _(
    "Placeholders: {event} (event name), {name} (attendee's full name), "
    "{name_for_salutation} (name as used in a salutation, e.g. \"Mr Doe\"), "
    "{code} (order code), {url} (link to the order page). Heads-up: "
    "{name_given_name} (first name) and {name_family_name} (last name) only exist "
    "for events that collect the name in parts. For any other event they are sent "
    "as literal text, so use {name} if the template is shared between events. "
    "Which further placeholders exist (e.g. event meta data) depends on the event."
)

QUESTIONS_NOTE = _(
    "Answers to registration questions are not available here - put them on the "
    "certificate itself in the layout editor."
)


def event_placeholders(event):
    """Placeholder names usable in this event's certificate emails - the same
    set the "Send out certificates" page offers."""
    return sorted(
        get_available_placeholders(event, ["event", "order", "position_or_address"])
    )


def placeholder_help(event=None):
    """Help text listing what can be used in a template's subject and text.

    For an event this is the very list the "Send out certificates" page shows
    (everything pretix and other plugins offer for this event, so event meta
    data and the event's name parts are included). Organizer-wide templates
    have no single event to ask, so they get a general note.
    """
    if event is None:
        return "%s %s" % (ORGANIZER_PLACEHOLDER_HELP, QUESTIONS_NOTE)

    keys = event_placeholders(event)
    text = _("Available placeholders: {list}").format(
        list=", ".join("{%s}" % key for key in keys)
    )
    if "name_given_name" in keys:
        hint = _(
            "{name} is the attendee's full name, {name_given_name} their first name."
        )
    else:
        hint = _(
            "{name} is the attendee's full name. This event only collects a full "
            "name, so {name_given_name} (first name) is not available - it would "
            "be sent as literal text."
        )
    return "%s %s %s" % (text, hint, QUESTIONS_NOTE)


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
            if event is not None:
                # Same check as on the "Send out certificates" page: an unknown
                # placeholder (a typo, or {name_given_name} on an event that
                # only collects a full name) would otherwise reach attendees
                # as literal text. Organizer-wide templates have no single
                # event to validate against.
                self.fields[fname].validators.append(
                    PlaceholderValidator(
                        ["{%s}" % key for key in event_placeholders(event)]
                    )
                )
