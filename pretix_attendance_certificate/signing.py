"""Digital signatures (PAdES) for rendered certificates of attendance.

The organizer stores one certificate + private key. Every PDF produced by
render_certificate() is signed with it, so a PDF reader can show that the file
really comes from the organizer and was not modified afterwards.

With a self-signed certificate readers will say "identity unknown" until the
public certificate (downloadable on the signing settings page) is added to the
reader's trusted certificates - that's expected and the integrity check
("document has not been modified since it was signed") works regardless.
"""

import datetime
from dataclasses import dataclass
from io import BytesIO

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from pyhanko.keys import load_certs_from_pemder_data, load_private_key_from_pemder_data
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import fields, signers
from pyhanko_certvalidator.registry import SimpleCertificateStore

from pretix_attendance_certificate.models import OrganizerSigningCertificate


class InvalidCertificate(ValueError):
    pass


@dataclass
class CertificateInfo:
    subject: str
    not_before: datetime.datetime
    not_after: datetime.datetime
    fingerprint: str

    @property
    def expired(self):
        return self.not_after < datetime.datetime.now(datetime.timezone.utc)


def _pem_private_key(key):
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def _pem_certificate(cert):
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def generate_self_signed(common_name, organization="", valid_days=5 * 365):
    """Returns (certificate_pem, private_key_pem) of a new self-signed
    certificate that is usable for document signing."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    attributes = [x509.NameAttribute(NameOID.COMMON_NAME, common_name)]
    if organization:
        attributes.append(x509.NameAttribute(NameOID.ORGANIZATION_NAME, organization))
    name = x509.Name(attributes)
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=valid_days))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=True,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    return _pem_certificate(cert), _pem_private_key(key)


def load_pkcs12(data, password=None):
    """Returns (certificate_pem, private_key_pem) from a .p12/.pfx file."""
    try:
        key, cert, _extra = pkcs12.load_key_and_certificates(
            data, password.encode() if password else None
        )
    except (ValueError, TypeError) as e:
        raise InvalidCertificate(str(e))
    if key is None or cert is None:
        raise InvalidCertificate("The file does not contain a key and a certificate.")
    return _pem_certificate(cert), _pem_private_key(key)


def certificate_info(certificate_pem):
    cert = x509.load_pem_x509_certificate(certificate_pem.encode())
    return CertificateInfo(
        subject=cert.subject.rfc4514_string(),
        not_before=cert.not_valid_before_utc,
        not_after=cert.not_valid_after_utc,
        fingerprint=cert.fingerprint(hashes.SHA256()).hex(":").upper(),
    )


def check_pair(certificate_pem, private_key_pem):
    """Raises InvalidCertificate unless key and certificate belong together
    and the pair can sign."""
    try:
        cert = x509.load_pem_x509_certificate(certificate_pem.encode())
        key = serialization.load_pem_private_key(private_key_pem.encode(), None)
    except (ValueError, TypeError) as e:
        raise InvalidCertificate(str(e))
    public = serialization.PublicFormat.SubjectPublicKeyInfo
    encoding = serialization.Encoding.DER
    if cert.public_key().public_bytes(encoding, public) != key.public_key().public_bytes(
        encoding, public
    ):
        raise InvalidCertificate("The private key does not match the certificate.")


def _signer(signing: OrganizerSigningCertificate):
    return signers.SimpleSigner(
        signing_cert=next(
            iter(load_certs_from_pemder_data(signing.certificate_pem.encode()))
        ),
        signing_key=load_private_key_from_pemder_data(
            signing.private_key_pem.encode(), passphrase=None
        ),
        cert_registry=SimpleCertificateStore(),
    )


def sign_pdf(pdf: bytes, signing: OrganizerSigningCertificate) -> bytes:
    """Returns pdf with an invisible PAdES signature added."""
    writer = IncrementalPdfFileWriter(BytesIO(pdf))
    metadata = signers.PdfSignatureMetadata(
        field_name="Signature1",
        reason=signing.reason or None,
        subfilter=fields.SigSeedSubFilter.PADES,
    )
    out = signers.PdfSigner(metadata, signer=_signer(signing)).sign_pdf(writer)
    return out.read()


def signing_for(organizer):
    """The organizer's active signing configuration, or None."""
    return OrganizerSigningCertificate.objects.filter(
        organizer=organizer, enabled=True
    ).first()
