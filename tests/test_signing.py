from io import BytesIO

import pytest
from django_scopes import scopes_disabled

from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign.validation import validate_pdf_signature
from pyhanko.keys import load_certs_from_pemder_data
from pyhanko_certvalidator import ValidationContext

from pretix_attendance_certificate import signing
from pretix_attendance_certificate.models import OrganizerSigningCertificate
from pretix_attendance_certificate.render import render_certificate


@pytest.fixture(scope="module")
def keypair():
    return signing.generate_self_signed("Test Org", "Test e.V.", valid_days=30)


@pytest.fixture
def signing_cfg(event, keypair):
    with scopes_disabled():
        return OrganizerSigningCertificate.objects.create(
            organizer=event.organizer,
            certificate_pem=keypair[0],
            private_key_pem=keypair[1],
        )


def _validate(pdf_bytes, certificate_pem):
    reader = PdfFileReader(BytesIO(pdf_bytes))
    assert len(reader.embedded_signatures) == 1
    sig = reader.embedded_signatures[0]
    trust = ValidationContext(
        trust_roots=list(load_certs_from_pemder_data(certificate_pem.encode()))
    )
    return validate_pdf_signature(sig, trust)


@pytest.mark.django_db
def test_certificate_is_unsigned_without_configuration(event, pos, layout):
    with scopes_disabled():
        pdf = render_certificate(position=pos, event=event, layout=layout).read()
    assert PdfFileReader(BytesIO(pdf)).embedded_signatures == []


@pytest.mark.django_db
def test_certificate_is_signed_and_valid(event, pos, layout, signing_cfg, keypair):
    with scopes_disabled():
        pdf = render_certificate(position=pos, event=event, layout=layout).read()
    status = _validate(pdf, keypair[0])
    assert status.intact and status.valid and status.trusted


@pytest.mark.django_db
def test_modified_pdf_fails_validation(event, pos, layout, signing_cfg, keypair):
    with scopes_disabled():
        pdf = render_certificate(position=pos, event=event, layout=layout).read()
    # Change a byte inside the signed range without breaking the structure.
    marker = b"/Producer"
    assert marker in pdf
    tampered = pdf.replace(marker, b"/Producar", 1)
    status = _validate(tampered, keypair[0])
    assert not status.intact


@pytest.mark.django_db
def test_disabled_signing_is_skipped(event, pos, layout, signing_cfg):
    signing_cfg.enabled = False
    signing_cfg.save()
    with scopes_disabled():
        pdf = render_certificate(position=pos, event=event, layout=layout).read()
    assert PdfFileReader(BytesIO(pdf)).embedded_signatures == []


def test_pkcs12_roundtrip(keypair):
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.serialization import pkcs12

    cert = x509.load_pem_x509_certificate(keypair[0].encode())
    key = serialization.load_pem_private_key(keypair[1].encode(), None)
    data = pkcs12.serialize_key_and_certificates(
        b"x", key, cert, None, serialization.BestAvailableEncryption(b"secret")
    )
    cert_pem, key_pem = signing.load_pkcs12(data, "secret")
    signing.check_pair(cert_pem, key_pem)
    with pytest.raises(signing.InvalidCertificate):
        signing.load_pkcs12(data, "wrong")


def test_mismatching_pair_is_rejected(keypair):
    other = signing.generate_self_signed("Other")
    with pytest.raises(signing.InvalidCertificate):
        signing.check_pair(keypair[0], other[1])


def _url(event, name="organizer.signing"):
    from django.urls import reverse

    return reverse(
        "plugins:pretix_attendance_certificate:" + name,
        kwargs={"organizer": event.organizer.slug},
    )


@pytest.mark.django_db
def test_generate_via_ui_then_certificates_are_signed(
    organizer_client, event, pos, layout
):
    response = organizer_client.post(
        _url(event),
        {
            "action": "generate",
            "generate-common_name": "Test e.V.",
            "generate-organization": "",
            "generate-valid_years": "2",
        },
    )
    assert response.status_code == 302
    with scopes_disabled():
        cfg = OrganizerSigningCertificate.objects.get(organizer=event.organizer)
        assert cfg.enabled
        pdf = render_certificate(position=pos, event=event, layout=layout).read()
    assert _validate(pdf, cfg.certificate_pem).valid
    assert "Test e.V." in organizer_client.get(_url(event)).content.decode()


@pytest.mark.django_db
def test_public_certificate_download_never_contains_the_key(
    organizer_client, event, signing_cfg
):
    response = organizer_client.get(_url(event, "organizer.signing.certificate"))
    body = response.content.decode()
    assert response.status_code == 200
    assert "BEGIN CERTIFICATE" in body and "PRIVATE KEY" not in body


@pytest.mark.django_db
def test_import_via_ui(organizer_client, event, keypair):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.serialization import pkcs12

    p12 = pkcs12.serialize_key_and_certificates(
        b"x",
        serialization.load_pem_private_key(keypair[1].encode(), None),
        x509.load_pem_x509_certificate(keypair[0].encode()),
        None,
        serialization.BestAvailableEncryption(b"secret"),
    )
    bad = organizer_client.post(
        _url(event),
        {"action": "import", "import-pkcs12": SimpleUploadedFile("a.p12", p12),
         "import-password": "wrong"},
    )
    assert bad.status_code == 200
    with scopes_disabled():
        assert not OrganizerSigningCertificate.objects.exists()
    good = organizer_client.post(
        _url(event),
        {"action": "import", "import-pkcs12": SimpleUploadedFile("a.p12", p12),
         "import-password": "secret"},
    )
    assert good.status_code == 302
    with scopes_disabled():
        assert OrganizerSigningCertificate.objects.get().certificate_pem == keypair[0]


@pytest.mark.django_db
def test_delete_stops_signing(organizer_client, event, signing_cfg):
    organizer_client.post(_url(event), {"action": "delete"})
    with scopes_disabled():
        assert not OrganizerSigningCertificate.objects.exists()


@pytest.mark.django_db
def test_signing_page_requires_organizer_permission(client, event):
    from pretix.base.models import Team, User

    with scopes_disabled():
        user = User.objects.create_user("noperm@dummy.dummy", "noperm")
        Team.objects.create(organizer=event.organizer).members.add(user)
    client.force_login(user)
    assert client.get(_url(event)).status_code != 200
    assert client.post(_url(event), {"action": "delete"}).status_code != 200
