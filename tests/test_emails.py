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
    assert "pretix_attendance_certificate/use_template_text.js" in content
    assert "addEventListener" not in content
