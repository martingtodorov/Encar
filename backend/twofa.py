"""Second factor (TOTP) and the device labels the session list shows.

The TOTP secret has to be recoverable to verify a code, so it is ENCRYPTED (Fernet,
`TOTP_ENCRYPTION_KEY`) rather than hashed. Recovery codes are the opposite: they are only
ever compared, so they are Argon2-hashed like a password and the plaintext is shown once.
"""
import os
import re
import secrets

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet

ph = PasswordHasher()
RECOVERY_CODES = 10


def _fernet():
    key = os.environ.get("TOTP_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("TOTP_ENCRYPTION_KEY is not configured")
    return Fernet(key.encode())


def new_secret():
    return pyotp.random_base32()


def encrypt(secret):
    return _fernet().encrypt(secret.encode()).decode()


def decrypt(ciphertext):
    return _fernet().decrypt(ciphertext.encode()).decode()


def provisioning_uri(secret, email, issuer="Encar"):
    return pyotp.TOTP(secret, digits=6, interval=30).provisioning_uri(
        name=email, issuer_name=issuer)


def qr_data_url(uri):
    """The provisioning URI as an inline PNG, so the browser needs no QR library."""
    import base64
    import io

    import qrcode

    buf = io.BytesIO()
    qrcode.make(uri).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def counter(secret):
    """The 30-second window a code belongs to, so an accepted code cannot be replayed."""
    return pyotp.TOTP(secret, digits=6, interval=30).timecode(
        __import__("datetime").datetime.now(__import__("datetime").timezone.utc))


def valid_code(secret, code):
    """One adjacent window of tolerance for a phone with a drifting clock, no more."""
    code = re.sub(r"\D", "", str(code or ""))
    if len(code) != 6:
        return False
    return pyotp.TOTP(secret, digits=6, interval=30).verify(code, valid_window=1)


def new_recovery_codes(n=RECOVERY_CODES):
    plain = ["-".join(re.findall("....", secrets.token_hex(6))) for _ in range(n)]
    return plain, [{"hash": ph.hash(c), "used": False, "used_at": None} for c in plain]


def match_recovery(code, entries):
    """Index of the unused recovery code that matches, else None."""
    code = (code or "").strip().lower()
    if not code:
        return None
    for i, entry in enumerate(entries or []):
        if entry.get("used"):
            continue
        try:
            if ph.verify(entry["hash"], code):
                return i
        except (VerifyMismatchError, VerificationError):
            continue
    return None


# ── device labels for the session list ───────────────────────────────────────
BROWSERS = [("Edg/", "Edge"), ("OPR/", "Opera"), ("Chrome/", "Chrome"),
            ("CriOS/", "Chrome"), ("Firefox/", "Firefox"), ("FxiOS/", "Firefox"),
            ("Safari/", "Safari")]
SYSTEMS = [("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"),
           ("Mac OS X", "macOS"), ("Windows NT", "Windows"), ("Linux", "Linux")]


def device(user_agent):
    """A phrase a person recognises ("Safari on macOS"), read off the UA string.

    Deliberately crude: this is a label in a list, not a security decision, and a UA
    parsing dependency would be a lot of surface for one line of text.
    """
    ua = user_agent or ""
    browser = next((name for token, name in BROWSERS if token in ua), "")
    system = next((name for token, name in SYSTEMS if token in ua), "")
    # Chrome on iOS also says Safari; the CriOS check above already won, so only fix Safari.
    if browser == "Safari" and "Chrome/" in ua:
        browser = "Chrome"
    label = " on ".join([p for p in (browser, system) if p]) or "Unknown device"
    return {"browser": browser or "Unknown", "os": system or "Unknown", "label": label}
