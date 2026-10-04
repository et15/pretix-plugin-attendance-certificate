import logging

from django import forms
from django.templatetags.static import static
from django.urls import reverse
from django.template.loader import get_template
from django.contrib.humanize.templatetags.humanize import intcomma
from django.utils.translation import gettext_lazy as _, ngettext

from pretix.plugins.sendmail.views import BaseSenderView
from pretix.plugins.sendmail.forms import BaseMailForm
from django.db.models import Exists, OuterRef
from pretix.base.models import Checkin, OrderPosition, Order

from pretix_attendance_certificate.models import LayoutActivation, available_layouts
from pretix_attendance_certificate.tasks import send_certificate_of_attendance_mails

logger = logging.getLogger(__name__)


class CertificateEmailForm(BaseMailForm):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Optional recipient subgroup, e.g. a "Passed the course" check-in
        # list that is maintained manually or by scanning. Left empty, the
        # certificate goes to every attendee with an admission ticket.
        checkin_lists = self.event.checkin_lists.all()
        if checkin_lists.exists():
            self.fields["checkin_lists"] = forms.ModelMultipleChoiceField(
                queryset=checkin_lists,
                label=_("Restrict to recipients with check-in on list"),
                required=False,
                widget=forms.CheckboxSelectMultiple(
                    attrs={"class": "scrolling-multiple-choice"}
                ),
                help_text=_(
                    "Only attendees who are checked in on at least one of the "
                    "selected lists receive the certificate. Leave empty to "
                    "send to all attendees with an admission ticket."
                ),
            )
        # Only ask which template to use when there actually is a choice -
        # events with a single available template keep working unchanged.
        candidates = available_layouts(self.event)
        if candidates.count() > 1:
            self.fields["layout"] = forms.ModelChoiceField(
                queryset=candidates,
                label=_("Template"),
                required=True,
                help_text=_(
                    "Multiple templates are available for this event - choose "
                    "which one to send out. Templates tied to a check-in list "
                    "only go to attendees checked in on that list."
                ),
            )


class SendCertificateEmailView(BaseSenderView):
    form_class = CertificateEmailForm
    form_fragment_name = (
        "pretix_attendance_certificate/send_form_fragment_attendance_certificate.html"
    )
    context_parameters = ["event", "order", "position_or_address"]
    task = send_certificate_of_attendance_mails

    ACTION_TYPE = "pretix_attendance_certificate.sendmail.sent"
    TITLE = _("Attendance Certificate")
    DESCRIPTION = _("Send out the attendance certificates to attendees.")

    @classmethod
    def get_url(cls, event):
        return reverse(
            "plugins:pretix_attendance_certificate:send",
            kwargs={
                "event": event.slug,
                "organizer": event.organizer.slug,
            },
        )

    def get_object_queryset(self, form):
        event = self.request.event
        qs = OrderPosition.objects.filter(
            canceled=False,
            item__admission=True,
            order__event=event,
            order__status__in=[Order.STATUS_PAID],
        )
        # The chosen template may itself be tied to a check-in list: then only
        # attendees checked in on that list are eligible for it.
        template_list = self._template_checkin_list(form)
        if template_list is not None:
            qs = qs.filter(self._checked_in_on([template_list]))
        # Optional additional restriction picked in the form.
        checkin_lists = form.cleaned_data.get("checkin_lists")
        if checkin_lists:
            qs = qs.filter(self._checked_in_on(checkin_lists))
        return qs.distinct()

    @staticmethod
    def _checked_in_on(checkin_lists):
        return Exists(
            Checkin.all.filter(
                position_id=OuterRef("pk"),
                list__in=checkin_lists,
                successful=True,
            )
        )

    def _template_checkin_list(self, form):
        layout = form.cleaned_data.get("layout")
        if layout is None:
            # No choice was asked for: there is at most one template.
            layout = available_layouts(self.request.event).first()
        if layout is None:
            return None
        activation = (
            LayoutActivation.objects.filter(layout=layout, event=self.request.event)
            .select_related("checkin_list")
            .first()
        )
        return activation.checkin_list if activation else None

    def describe_match_size(self, cnt):
        return ngettext(
            "%(number)s matching ticket",
            "%(number)s matching tickets",
            cnt or 0,
        ) % {
            "number": intcomma(cnt or 0),
        }

    def get_task_kwargs(self, form, objects):
        kwargs = super().get_task_kwargs(form, objects)
        if "layout" in form.cleaned_data:
            kwargs["layout_id"] = form.cleaned_data["layout"].pk
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Lets the "use this template's email text" button in our form
        # fragment fill the subject/message fields client-side, without a
        # round trip - keyed by locale index to match the subject_N/message_N
        # field names the I18nFormField widget renders.
        locales = self.request.event.settings.get("locales")
        ctx["layout_mail_texts"] = {
            layout.pk: {
                "subject": [str(layout.mail_subject.localize(loc)) for loc in locales],
                "message": [str(layout.mail_text.localize(loc)) for loc in locales],
            }
            for layout in available_layouts(self.request.event)
        }
        # Plugin static files are only in pretix's staticfiles manifest after
        # `pretix rebuild`/collectstatic. Don't turn a missing entry into a
        # 500 for the whole send page - the button just stays inactive.
        try:
            ctx["use_template_text_js"] = static(
                "pretix_attendance_certificate/use_template_text.js"
            )
        except ValueError:
            logger.warning(
                "use_template_text.js is missing from the staticfiles manifest; "
                "run `pretix rebuild` to enable the template email text button."
            )
            ctx["use_template_text_js"] = None
        return ctx

    @classmethod
    def show_history_meta_data(cls, logentry, _cache_store):
        if "checkin_list_cache" not in _cache_store:
            _cache_store["checkin_list_cache"] = {
                c.pk: str(c) for c in logentry.event.checkin_lists.all()
            }
        checkin_lists = [
            _cache_store["checkin_list_cache"][c["id"]]
            for c in logentry.parsed_data.get("checkin_lists") or []
            if c.get("id") in _cache_store["checkin_list_cache"]
        ]
        tpl = get_template(
            "pretix_attendance_certificate/history_fragment_attendance_certificate.html"
        )
        return tpl.render(
            {
                "log": logentry,
                "checkin_lists": checkin_lists,
            }
        )
