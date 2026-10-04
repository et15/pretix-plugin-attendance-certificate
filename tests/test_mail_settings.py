import pytest
from django.core import mail as djmail
from django.test import RequestFactory
from django.urls import reverse
from django_scopes import scopes_disabled

from pretix.base.models import Team, User

from pretix_attendance_certificate.signals import control_nav_event_settings


def _settings_url(event):
    return reverse(
        "plugins:pretix_attendance_certificate:mail_settings",
        kwargs={"organizer": event.organizer.slug, "event": event.slug},
    )


def _send_url(event, position):
    return reverse(
        "plugins:pretix_attendance_certificate:position.send",
        kwargs={
            "organizer": event.organizer.slug,
            "event": event.slug,
            "position": position.pk,
        },
    )


def _nav_request(event, user):
    from django.contrib.sessions.backends.db import SessionStore

    rf = RequestFactory()
    request = rf.get(_settings_url(event))
    request.user = user
    request.organizer = event.organizer
    request.event = event
    request.session = SessionStore()
    return request


@pytest.mark.django_db
def test_nav_settings_entry_hidden_without_permission(event):
    with scopes_disabled():
        user = User.objects.create_user("noperm@dummy.dummy", "noperm")
        team = Team.objects.create(organizer=event.organizer, can_view_orders=True)
        team.members.add(user)
        team.limit_events.add(event)
    entries = control_nav_event_settings(None, request=_nav_request(event, user))
    assert entries == []


@pytest.mark.django_db
def test_nav_settings_entry_shown_with_permission(logged_in_client, event):
    with scopes_disabled():
        user = User.objects.get(email="dummy@dummy.dummy")
    entries = control_nav_event_settings(None, request=_nav_request(event, user))
    assert len(entries) == 1
    assert entries[0]["label"] == "Certificate of Attendance"


@pytest.mark.django_db
def test_mail_settings_page_shows_defaults(logged_in_client, event):
    response = logged_in_client.get(_settings_url(event))
    assert response.status_code == 200
    assert "Your certificate of attendance" in response.rendered_content


@pytest.mark.django_db
def test_mail_settings_can_be_customized_and_are_used_on_send(
    logged_in_client, event, order, pos, layout
):
    response = logged_in_client.post(
        _settings_url(event),
        {
            "pretix_attendance_certificate_mail_subject_0": "Custom subject",
            "pretix_attendance_certificate_mail_text_0": "Custom body text",
        },
    )
    assert response.status_code == 302

    with scopes_disabled():
        event.settings.flush()
        assert str(event.settings.pretix_attendance_certificate_mail_subject) == (
            "Custom subject"
        )

    djmail.outbox = []
    response = logged_in_client.post(_send_url(event, pos))
    assert response.status_code == 302
    assert len(djmail.outbox) == 1
    assert djmail.outbox[0].subject == "Custom subject"
    assert "Custom body text" in djmail.outbox[0].body
