from django.urls import reverse

from pretix.base.models import Event
from pretix.control.views.event import (
    EventSettingsFormView,
    EventSettingsViewMixin,
)

from pretix_attendance_certificate.forms import CertificateMailSettingsForm


class CertificateMailSettingsView(EventSettingsViewMixin, EventSettingsFormView):
    model = Event
    form_class = CertificateMailSettingsForm
    template_name = "pretix_attendance_certificate/mail_settings.html"
    permission = "can_change_event_settings"

    def get_success_url(self) -> str:
        return reverse(
            "plugins:pretix_attendance_certificate:mail_settings",
            kwargs={
                "organizer": self.request.event.organizer.slug,
                "event": self.request.event.slug,
            },
        )
