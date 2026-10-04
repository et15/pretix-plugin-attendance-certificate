from hmac import compare_digest

from django.http import FileResponse, Http404
from django.views import View

from pretix.base.models import Order

from pretix_attendance_certificate.models import certificate_options
from pretix_attendance_certificate.render import render_certificate

SELF_SERVICE_SETTING = "attendance_certificate_self_service"


def self_service_enabled(event):
    return event.settings.get(SELF_SERVICE_SETTING, as_type=bool, default=False)


def downloadable_options(position):
    """Templates the attendee may download themselves, best ranked first."""
    order = position.order
    if (
        not self_service_enabled(order.event)
        or order.status != Order.STATUS_PAID
        or position.canceled
        or not position.item.admission
    ):
        return []
    return [o for o in certificate_options(position) if o.applicable]


class SelfServiceDownloadView(View):
    """Certificate download for attendees, authorized the same way as the
    order page: by knowing the order secret (or the ticket page's position
    secret)."""

    def get(self, request, *args, **kwargs):
        event = request.event
        order = event.orders.filter(code=kwargs["order"]).first()
        position = (
            order.positions.select_related("item")
            .filter(positionid=kwargs["position"])
            .first()
            if order
            else None
        )
        secret = kwargs["secret"].lower()
        if position is None or not (
            compare_digest(secret, order.secret.lower())
            or compare_digest(secret, position.web_secret.lower())
        ):
            raise Http404()
        option = next(
            (o for o in downloadable_options(position) if o.pk == int(kwargs["layout"])),
            None,
        )
        if option is None:
            raise Http404()
        return FileResponse(
            render_certificate(position=position, event=event, layout=option.layout),
            as_attachment=True,
            filename="certificate-{code}-{pos}.pdf".format(
                code=order.code, pos=position.positionid
            ),
            content_type="application/pdf",
        )
