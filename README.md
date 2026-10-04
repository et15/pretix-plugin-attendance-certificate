# pretix-plugin-attendance-certificate

Plugin to create and send the certificate of attendance to attendees.

Used by https://pycon.it

## Digital signature

Organizers can sign all certificates of attendance with a certificate of their
organization (PAdES signature, added with [pyHanko](https://github.com/MatthiasValvekens/pyHanko)).
Open *Certificate templates* in the organizer settings and choose
*Digital signature*; there you can create a self-signed certificate or import a
`.p12`/`.pfx` file.

With a self-signed certificate, PDF readers show the signer as unknown until the
public certificate (downloadable on the same page) is added to their trusted
certificates. Publish it together with its SHA-256 fingerprint, e.g. on your
website. Later modifications of a signed PDF are detected regardless.

The private key is stored unencrypted in the pretix database.
