"""Generate the proxy credential primitives used by static and dynamic nodes."""
import base64
import secrets
import subprocess
import uuid


def credentials():
    private = subprocess.run(
        ['openssl', 'genpkey', '-algorithm', 'X25519', '-outform', 'DER'],
        check=True, capture_output=True,
    ).stdout
    public = subprocess.run(
        ['openssl', 'pkey', '-inform', 'DER', '-pubout', '-outform', 'DER'],
        input=private, check=True, capture_output=True,
    ).stdout
    # RFC 8410 wrappers; fail rather than truncate a changed OpenSSL format.
    if (len(private) != 48 or private[:16].hex() != '302e020100300506032b656e04220420'
            or len(public) != 44 or public[:12].hex() != '302a300506032b656e032100'):
        raise ValueError('Unexpected OpenSSL X25519 format')
    encode = lambda key: base64.urlsafe_b64encode(key).decode().rstrip('=')
    return {
        'naive_username': 'vpn', 'naive_password': secrets.token_urlsafe(32),
        'vless_uuid': str(uuid.uuid4()), 'reality_private_key': encode(private[-32:]),
        'reality_public_key': encode(public[-32:]), 'reality_short_id': secrets.token_hex(8),
    }
