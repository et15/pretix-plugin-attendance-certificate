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
    assert "Use this template's email text" not in response.rendered_content


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
    content = response.rendered_content
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

    content = logged_in_client.get(_send_url(event)).rendered_content
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
def test_checkin_list_field_hidden_without_lists(
    logged_in_client, event, order, pos, layout
):
    content = logged_in_client.get(_send_url(event)).rendered_content
    assert "checkin_lists" not in content


@pytest.mark.django_db
def test_bulk_send_restricted_to_checkin_list(
    logged_in_client, event, order, pos, pos2, layout, passed_list
):
    with scopes_disabled():
        _check_in(pos, passed_list)

    djmail.outbox = []
    response = logged_in_client.post(
        _send_url(event), _post_data(checkin_lists=[passed_list.pk])
    )
    assert response.status_code == 302
    assert [m.to for m in djmail.outbox] == [["attendee@dummy.test"]]

    with scopes_disabled():
        entry = event.logentry_set.get(
            action_type="pretix_attendance_certificate.sendmail.sent"
        )
        assert [c["id"] for c in entry.parsed_data["checkin_lists"]] == [
            passed_list.pk
        ]


@pytest.mark.django_db
def test_bulk_send_without_checkin_list_goes_to_everyone(
    logged_in_client, event, order, pos, pos2, layout, passed_list
):
    with scopes_disabled():
        _check_in(pos, passed_list)

    djmail.outbox = []
    response = logged_in_client.post(_send_url(event), _post_data())
    assert response.status_code == 302
    assert len(djmail.outbox) == 2


@pytest.mark.django_db
def test_failed_checkin_does_not_count(
    logged_in_client, event, order, pos, pos2, layout, passed_list
):
    with scopes_disabled():
        _check_in(pos, passed_list, successful=False)

    djmail.outbox = []
    response = logged_in_client.post(
        _send_url(event), _post_data(checkin_lists=[passed_list.pk])
    )
    # Nobody matches -> pretix shows an error instead of queueing anything.
    assert response.status_code == 200
    assert len(djmail.outbox) == 0


@pytest.mark.django_db
def test_checkin_list_and_template_combine(
    logged_in_client, event, order, pos, pos2, layout, organizer_layout, passed_list
):
    with scopes_disabled():
        organizer_layout.active_events.add(event)
        _check_in(pos2, passed_list)

    djmail.outbox = []
    response = logged_in_client.post(
        _send_url(event),
        _post_data(layout=organizer_layout.pk, checkin_lists=[passed_list.pk]),
    )
    assert response.status_code == 302
    assert [m.to for m in djmail.outbox] == [["other@dummy.test"]]


@pytest.mark.django_db
def test_history_shows_checkin_list(
    logged_in_client, event, order, pos, layout, passed_list
):
    with scopes_disabled():
        _check_in(pos, passed_list)
    logged_in_client.post(
        _send_url(event), _post_data(checkin_lists=[passed_list.pk])
    )
    response = logged_in_client.get(_send_url(event))
    assert response.status_code == 200
    content = response.rendered_content
    assert "Passed the course" in content
