from django import forms
from django.utils.translation import gettext_lazy as _
from i18nfield.forms import I18nFormField, I18nTextarea, I18nTextInput

from pretix.base.forms import SettingsForm

from pretix_attendance_certificate.models import AttendanceCertificateLayout


class OrganizerLayoutForm(forms.ModelForm):
    class Meta:
        model = AttendanceCertificateLayout
        fields = ["name"]


class CertificateMailSettingsForm(SettingsForm):
    pretix_attendance_certificate_mail_subject = I18nFormField(
        label=_("Email subject"),
        widget=I18nTextInput,
        required=True,
    )
    pretix_attendance_certificate_mail_text = I18nFormField(
        label=_("Email text"),
        widget=I18nTextarea,
        required=True,
        help_text=_("Available placeholder: {event}"),
    )
