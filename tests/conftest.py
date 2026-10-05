import datetime
import inspect

import pytest
from django.utils import translation
from django.utils.timezone import now
from django_scopes import scopes_disabled

from pretix.base.models import (
    Event,
    Item,
    Order,
    OrderPosition,
    Organizer,
    Team,
    User,
)

from pretix_attendance_certificate.models import AttendanceCertificateLayout


@pytest.hookimpl(hookwrapper=True)
def pytest_fixture_setup(fixturedef, request):
    """Disable django-scopes for all non-yield fixtures.

    Mirrors pretix' own test suite so fixtures can create scoped models
    (Order, OrderPosition, ...) without an active scope.
    """
    if inspect.isgeneratorfunction(fixturedef.func):
        yield
    else:
        with scopes_disabled():
            yield


@pytest.fixture(autouse=True)
def reset_locale():
    translation.activate("en")


@pytest.fixture
def event():
    organizer = Organizer.objects.create(name="Dummy", slug="dummy")
    event = Event.objects.create(
        organizer=organizer,
        name="Dummy",
        slug="dummy",
        date_from=now(),
        live=True,
        plugins="pretix_attendance_certificate",
    )
    return event


@pytest.fixture
def layout(event):
    return AttendanceCertificateLayout.objects.create(event=event, name="Default")


@pytest.fixture
def organizer_layout(event):
    return AttendanceCertificateLayout.objects.create(
        organizer=event.organizer, name="Organizer-wide"
    )


@pytest.fixture
def second_organizer_layout(event):
    return AttendanceCertificateLayout.objects.create(
        organizer=event.organizer, name="Organizer-wide 2"
    )


@pytest.fixture
def item(event):
    return Item.objects.create(
        name="Test item", event=event, default_price=13, admission=True
    )


@pytest.fixture
def order(event):
    return Order.objects.create(
        event=event,
        status=Order.STATUS_PAID,
        expires=now() + datetime.timedelta(hours=1),
        total=13,
        code="DUMMY",
        email="dummy@dummy.test",
        datetime=now(),
        locale="en",
    )


@pytest.fixture
def pos(order, item):
    return OrderPosition.objects.create(
        order=order,
        item=item,
        price=13,
        attendee_name_parts={"_legacy": "Marco Acierno"},
        attendee_email="attendee@dummy.test",
    )


@pytest.fixture
def logged_in_client(client, event):
    user = User.objects.create_user("dummy@dummy.dummy", "dummy")
    team = Team.objects.create(
        organizer=event.organizer,
        can_view_orders=True,
        can_change_orders=True,
        can_change_event_settings=True,
    )
    team.members.add(user)
    team.limit_events.add(event)
    client.force_login(user)
    return client


@pytest.fixture
def organizer_client(client, event):
    user = User.objects.create_user("orgadmin@dummy.dummy", "orgadmin")
    team = Team.objects.create(
        organizer=event.organizer,
        can_change_organizer_settings=True,
        # An organizer admin also manages the events' pages in these tests; pretix
        # 2026 no longer implies event permissions from organizer ones.
        can_view_orders=True,
        can_change_event_settings=True,
        all_events=True,
    )
    team.members.add(user)
    client.force_login(user)
    return client
