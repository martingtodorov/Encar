"""Deploy-time probes must not depend on one car still being for sale.

Vehicle 42207598 was hardcoded in three places: the deploy verification, and two curl probes
in the NAT playbook — one of which is wrapped in `assert stdout == '200'`. That car has since
sold, so api.encar.com answers 404 for it, and a perfectly healthy home exit would have failed
the play. Every probe now asks the CATALOGUE for a count, a question with no expiry date.
"""
import os
import re
from urllib.parse import quote

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEPLOY = os.path.join(ROOT, "deploy")


def _files():
    for base, _, names in os.walk(DEPLOY):
        for name in names:
            if name.endswith((".yml", ".yaml", ".sh")):
                yield os.path.join(base, name)


def test_no_deploy_probe_pins_a_vehicle_id():
    offenders = []
    for path in _files():
        with open(path, encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                if re.search(r"readside/vehicle/\d", line) or re.search(
                        r"encar\s+--verify\s+\d", line):
                    offenders.append(f"{os.path.relpath(path, ROOT)}:{n}")
    assert not offenders, ("a probe is pinned to one car, which rots the day it sells: "
                           + ", ".join(offenders))


def test_the_nat_probe_url_is_what_the_client_itself_would_ask():
    """If the probe drifts from the real request, a green play proves nothing."""
    path = os.path.join(DEPLOY, "hetzner/ansible/playbooks/deploy_nat.yml")
    with open(path, encoding="utf-8") as fh:
        plays = yaml.safe_load(fh)
    urls = [p["vars"]["encar_probe_url"].strip() for p in plays
            if isinstance(p, dict) and (p.get("vars") or {}).get("encar_probe_url")]
    assert urls, "the NAT playbook has no encar_probe_url"

    import encar

    expected = ("https://api.encar.com/search/car/list/general?count=true"
                f"&q={quote(encar.BASE_Q)}&sr={quote('|ModifiedDate|0|1')}")
    for url in urls:
        # The probe may narrow the base query (the play uses the shared scope without the
        # sell-type clause), so compare the parts that must not drift.
        assert url.startswith("https://api.encar.com/search/car/list/general?count=true")
        assert "&sr=" in url and quote("|ModifiedDate|") in url
        assert "%28And.Hidden.N._.CarType.A." in url
        assert expected.split("?")[0] == url.split("?")[0]


def test_every_probe_url_survives_a_shell_and_a_url_parser():
    """Single-quoted in the playbook, so `&` and `|` are safe - but `|` must be encoded or
    curl and CloudFront disagree about the request line."""
    path = os.path.join(DEPLOY, "hetzner/ansible/playbooks/deploy_nat.yml")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    url = [p["vars"]["encar_probe_url"].strip()
           for p in yaml.safe_load(text)
           if isinstance(p, dict) and (p.get("vars") or {}).get("encar_probe_url")][0]
    assert "|" not in url and "(" not in url and ")" not in url
    assert " " not in url
    # Both curl tasks use the variable rather than repeating the URL.
    assert text.count("{{ encar_probe_url }}") >= 2
