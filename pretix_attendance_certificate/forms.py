from django import forms
from django.utils.translation import gettext_lazy as _

from pretix_attendance_certificate.models import AttendanceCertificateLayout


class OrganizerLayoutForm(forms.ModelForm):
    class Meta:
        model = AttendanceCertificateLayout
        fields = ["name", "mail_subject", "mail_text"]
        help_texts = {
            "mail_subject": _("Available placeholder: {event}"),
            "mail_text": _("Available placeholder: {event}"),
        }

    def __init__(self, *args, **kwargs):
        locales = kwargs.pop("locales", None)
        super().__init__(*args, **kwargs)
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
                    help_text=field.help_text,
                )
