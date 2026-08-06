"""requirements.txt must be installable on a plain server, not just inside this pod.

The deploy on the owner's Hetzner box died with

    ERROR: No matching distribution found for emergentintegrations==0.2.0

because `pip freeze` had captured two things that only exist on the Emergent platform: the
`emergentintegrations` wrapper (private index) and a `litellm` wheel pinned to an
emergentagent.com URL. Neither is imported by the app — the wrapper is a last-resort fallback
for the shared universal key, which never fires while ANTHROPIC_API_KEY is set.

Run with: cd /app/backend && python -m pytest tests/test_requirements_portable.py -q
"""
import os
import re

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQ = os.path.join(BACKEND, "requirements.txt")

# Only ever installable from the platform's own index or asset host.
PLATFORM_ONLY = ("emergentintegrations", "litellm")
# Installed here to check the Ansible playbooks; it has no business on the app server.
TOOLING_ONLY = ("ansible-core", "ansible", "resolvelib")


def _lines():
    with open(REQ) as fh:
        return [l.strip() for l in fh if l.strip() and not l.startswith("#")]


def _name(line):
    return re.split(r"[=<>!~\[ @]", line, 1)[0].strip().lower()


def test_nothing_points_at_a_url_or_a_local_path():
    """A pinned URL or a file:// path cannot be resolved from another machine."""
    offenders = [l for l in _lines()
                 if " @ " in l or "file://" in l or l.endswith(".whl") or "://" in l]
    assert offenders == [], (
        "these lines are not installable off this machine:\n  " + "\n  ".join(offenders))


def test_no_platform_only_packages():
    names = {_name(l) for l in _lines()}
    found = sorted(names & set(PLATFORM_ONLY))
    assert found == [], (
        f"{found} only exist on the Emergent platform — the Hetzner deploy will fail. "
        "They are not imported by the app; the universal-key fallback is dead code there.")


def test_no_agent_tooling_leaked_in():
    names = {_name(l) for l in _lines()}
    found = sorted(names & set(TOOLING_ONLY))
    assert found == [], f"{found} got in through `pip freeze`; the app server does not need it"


def test_every_line_is_pinned():
    """An unpinned dependency means the box you deploy tomorrow gets different code."""
    loose = [l for l in _lines() if "==" not in l]
    assert loose == [], f"unpinned: {loose}"


def test_the_packages_the_app_actually_imports_are_listed():
    names = {_name(l) for l in _lines()}
    # Ones that have bitten us: they were installed in the pod but missing from the file, so a
    # fresh server would have failed at import time, after a successful pip run.
    for pkg in ("python-docx", "pyotp", "qrcode", "pywebpush", "py-vapid", "http-ece", "lxml",
                "anthropic", "motor", "stripe", "resend", "fastapi", "uvicorn"):
        assert pkg in names or pkg.replace("-", "_") in names, f"{pkg} is imported but not pinned"
