"""One phone format, checked at the edge.

The browser normalises what the buyer types (frontend/src/lib/phone.js), but a form is not a
guarantee: an enquiry can be posted straight at the API. Everything stored is E.164
(+359881234567) so the office can dial it without guessing, and a national number is only
completed with a country code when the caller tells us which language they were using.
"""
import re

E164 = re.compile(r"^\+[1-9]\d{7,14}$")
HOME_CODE = {"bg": "359", "ro": "40"}


def clean(raw, lang=""):
    """The number in E.164, or "" when it is not dialable."""
    value = str(raw or "").strip()
    if not value:
        return ""
    plus = value.startswith("+") or value.startswith("00")
    digits = re.sub(r"\D", "", value.removeprefix("00") if value.startswith("00") else value)
    if not digits:
        return ""
    if not plus and digits.startswith("0"):
        code = HOME_CODE.get(lang, "")
        digits = f"{code}{digits.lstrip('0')}" if code else digits
    out = f"+{digits}"
    return out if E164.match(out) else ""


def valid(raw, lang=""):
    return bool(clean(raw, lang))
