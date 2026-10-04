import pytest
from django.core import mail as djmail
from django.urls import reverse
from django_scopes import scopes_disabled


def _send_url(event):
    return reverse(
        "plugins:pretix_attendance_certificate:send",
        kwargs={"organizer": event.organizer.slug, "event": event.slug},
    )


def _post_data(action="send", **extra):
    data = {
        "subject_0": "Your certificate",
        "message_0": "Here you go.",
        "action": action,
    }
    data.update(extra)
    return data


@pytest.mark.django_db
def test_bulk_send_without_layout_field_when_single_candidate(
    logged_in_client, event, order, pos, layout
):
    djmail.outbox = []
    response = logged_in_client.post(_send_url(event), _post_data())
    assert response.status_code == 302
    assert len(djmail.outbox) == 1


@pytest.mark.django_db
def test_bulk_send_form_requires_layout_choice_with_multiple_candidates(
    logged_in_client, event, order, pos, layout, organizer_layout
):
    with scopes_disabled():
        organizer_layout.active_events.add(event)

    djmail.outbox = []
    response = logged_in_client.post(_send_url(event), _post_data())
    # Missing required "layout" field -> form invalid, nothing sent.
    assert len(djmail.outbox) == 0
    assert response.status_code == 200


@pytest.mark.django_db
def test_bulk_send_with_explicit_layout_choice(
    logged_in_client, event, order, pos, layout, organizer_layout
):
    with scopes_disabled():
        organizer_layout.active_events.add(event)

    djmail.outbox = []
    response = logged_in_client.post(
        _send_url(event), _post_data(layout=organizer_layout.pk)
    )
    assert response.status_code == 302
    assert len(djmail.outbox) == 1


@pytest.mark.django_db
def test_use_template_button_hidden_with_single_candidate(
    logged_in_client, event, order, pos, layout
):
    response = logged_in_client.get(_send_url(event))
    assert "Use this template's email text" not in response.content.decode()


@pytest.mark.django_db
def test_use_template_button_and_data_shown_with_multiple_candidates(
    logged_in_client, event, order, pos, layout, organizer_layout
):
    with scopes_disabled():
        organizer_layout.active_events.add(event)
        organizer_layout.mail_subject = "Org subject"
        organizer_layout.mail_text = "Org body"
        organizer_layout.save()

    response = logged_in_client.get(_send_url(event))
    content = response.content.decode()
    assert "Use this template's email text" in content
    assert "Org subject" in content
    assert "Org body" in content


@pytest.mark.django_db
def test_use_template_button_script_is_not_inline(
    logged_in_client, event, order, pos, layout, organizer_layout
):
    # pretix's CSP blocks inline scripts, so the click handler has to be a
    # static file or the button silently does nothing.
    with scopes_disabled():
        organizer_layout.active_events.add(event)

    content = logged_in_client.get(_send_url(event)).content.decode()
    assert "use_template_text.js" in content
    assert "addEventListener" not in content


@pytest.fixture
def passed_list(event):
    from pretix.base.models import CheckinList

    return CheckinList.objects.create(event=event, name="Passed the course")


@pytest.fixture
def pos2(order, item):
    from pretix.base.models import OrderPosition

    return OrderPosition.objects.create(
        order=order,
        item=item,
        price=13,
        attendee_name_parts={"_legacy": "Other Person"},
        attendee_email="other@dummy.test",
    )


def _check_in(pos, checkin_list, successful=True):
    from pretix.base.models import Checkin
    from django.utils.timezone import now

    Checkin.objects.create(
        position=pos, list=checkin_list, datetime=now(), successful=successful
    )


@pytest.mark.django_db
def test_form_has_no_checkin_list_selector(
    logged_in_client, event, order, pos, layout, passed_list
):
    # The check-in list is bound to the template, so the send form must not
    # offer a second, competing way to pick it.
    content = logged_in_client.get(_send_url(event)).content.decode()
    assert "checkin_lists" not in content
    assert "Restrict to recipients with check-in on list" not in content


@pytest.mark.django_db
def test_posted_checkin_lists_are_ignored(
    logged_in_client, event, order, pos, pos2, layout, passed_list
):
    with scopes_disabled():
        _check_in(pos, passed_list)

    djmail.outbox = []
    response = logged_in_client.post(
        _send_url(event), _post_data(checkin_lists=[passed_list.pk])
    )
    assert response.status_code == 302
    assert len(djmail.outbox) == 2


@pytest.mark.django_db
def test_history_shows_checkin_list_of_older_entries(
    logged_in_client, event, order, pos, layout, passed_list
):
    # Entries written before the selector was removed still carry the lists.
    with scopes_disabled():
        event.log_action(
            "pretix_attendance_certificate.sendmail.sent",
            data={
                "subject": {"en": "S"},
                "message": {"en": "M"},
                "checkin_lists": [{"id": passed_list.pk, "name": "x"}],
            },
        )
    # The history lives on pretix' own "Email history" page, not on the send form.
    response = logged_in_client.get(
        reverse(
            "plugins:sendmail:history",
            kwargs={"organizer": event.organizer.slug, "event": event.slug},
        )
    )
    assert response.status_code == 200
    assert "Passed the course" in response.content.decode()
