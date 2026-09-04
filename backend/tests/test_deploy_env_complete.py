"""The deploy template must carry every secret the app cannot work without.

`deploy_backend.yml` REWRITES /etc/encar/backend.env from `templates/backend.env.j2` on every
deploy, so a key missing from the template is silently wiped off the server. That is exactly
how ENCAREUROPE_API_TOKEN disappeared and the mobile.bg bot started getting 503.

Only genuine secrets and identity are listed. Tuning knobs (CARGO_TTL_*, DEPOSIT_*,
TRANSLATE_*) have sane defaults in code and are deliberately absent from the template.
"""
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[2] / "deploy/hetzner/ansible/templates/backend.env.j2"

REQUIRED = [
    "MONGO_URL",
    "DB_NAME",
    "PUBLIC_SITE_URL",
    "CORS_ORIGINS",
    "MEDIA_ROOT",
    "ADMIN_TOKEN",
    "ADMIN_SEED_PASSWORD",
    "TOTP_ENCRYPTION_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "RESEND_API_KEY",
    "SENDER_EMAIL",
    "ADMIN_NOTIFY_EMAIL",
    "OWNER_EMAIL",
    "OWNER_PASSWORD",
    "JSONCARGO_API_KEY",
    "JSONCARGO_SHIPPING_LINE",
    "EDI_INGEST_TOKEN",
    "ENCAREUROPE_API_TOKEN",
    "ENCAR_PROXY_URL",
    "VAPID_PUBLIC_KEY",
    "VAPID_PRIVATE_KEY",
    "VAPID_SUBJECT",
]


def test_every_required_key_is_templated():
    assert TEMPLATE.exists(), f"{TEMPLATE} is missing"
    keys = {
        line.split("=", 1)[0].strip()
        for line in TEMPLATE.read_text().splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    missing = [k for k in REQUIRED if k not in keys]
    assert not missing, (
        "these keys are read by the backend but not written by the deploy template, so a "
        f"deploy would wipe them from the server: {missing}"
    )
