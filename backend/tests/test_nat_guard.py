"""Renders and exercises the NAT guard scripts against a stubbed `ip`/`wg`/`systemctl`.

Run: python3 /app/backend/tests/test_nat_guard.py
The scripts are what stands between back1 and a week of silence, so the branches are tested
here rather than on the box: rules missing, table default missing, no egress with a stale
handshake, and the healthy case doing nothing at all.
"""
import os
import re
import subprocess
import tempfile
from pathlib import Path

from jinja2 import Environment

ROOT = Path("/app/deploy/hetzner/ansible")
VARS = {
    "app_name": "encar", "nat_table": 100, "nat_rule_priority": 1000,
    "backend_service_user": "www-data", "wg_front_ip": "10.99.0.1",
    "wg_back_ip": "10.99.0.2", "private_cidr": "10.0.0.0/16",
    "nat_route_management": True, "home_exit_pubkey": "abc=", "home_exit_ip": "10.99.0.3",
    "nat_guard_interval": 60, "public_iface": "eth0",
}


def render(name, state):
    # `| bool` is an Ansible filter, not a Jinja one; the guard templates use it the same way
    # the wg0 templates do, so the test has to speak the same dialect.
    env = Environment(keep_trailing_newline=True)
    env.filters["bool"] = lambda v: str(v).lower() in ("true", "yes", "1", "on")
    text = env.from_string((ROOT / "templates" / name).read_text()).render(
        **{**VARS, "nat_guard_state": state})
    path = Path(tempfile.mkdtemp()) / "guard"
    path.write_text(text)
    path.chmod(0o755)
    return path


def stubs(folder, *, rules, table_default, egress, handshake):
    """A fake `ip`/`wg`/`runuser`/`systemctl` that records what the guard did."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "calls.log").write_text("")
    rules_txt = "\n".join(rules)
    table_txt = ("default via 10.99.0.1 dev wg0 src 10.99.0.2" if table_default else "")
    (folder / "ip").write_text(f"""#!/bin/bash
echo "ip $*" >> {folder}/calls.log
case "$*" in
  "rule show") cat <<'EOF'
0:\tfrom all lookup local
{rules_txt}
32766:\tfrom all lookup main
EOF
  ;;
  "route show table 100") echo "{table_txt}" ;;
  "route show 10.99.0.3/32") echo "10.99.0.3 via 10.99.0.1 dev wg0" ;;
  "-br link") echo "wg0 UNKNOWN" ;;
esac
exit 0
""")
    (folder / "wg").write_text(f"""#!/bin/bash
echo "wg $*" >> {folder}/calls.log
if [ "$*" = "show wg0 latest-handshakes" ]; then echo -e "KEY\\t{handshake}"; fi
exit 0
""")
    (folder / "runuser").write_text(f"""#!/bin/bash
echo "egress-probe" >> {folder}/calls.log
exit {0 if egress else 1}
""")
    for name in ("systemctl", "logger", "sysctl", "iptables", "date_unused"):
        (folder / name).write_text(f'#!/bin/bash\necho "{name} $*" >> {folder}/calls.log\nexit 0\n')
    for f in folder.iterdir():
        if f.name != "calls.log":
            f.chmod(0o755)
    return folder


def run(script, bin_dir, state):
    env = dict(os.environ, PATH=f"{bin_dir}:/usr/bin:/bin")
    p = subprocess.run(["/bin/bash", str(script)], env=env, capture_output=True, text=True,
                       timeout=60)
    calls = (Path(bin_dir) / "calls.log").read_text()
    return p, calls, Path(state).read_text() if Path(state).exists() else ""


def main():
    now = int(subprocess.run(["date", "+%s"], capture_output=True, text=True).stdout)
    uid = subprocess.run(["id", "-u", "www-data"], capture_output=True, text=True).stdout.strip()
    good_rules = [f"1000:\tfrom all uidrange {uid}-{uid} lookup encar",
                  "1010:\tfrom all lookup encar"]
    failures = []

    # 1. The incident: both rules deleted, everything else healthy.
    state = tempfile.mktemp()
    script = render("nat-guard-back.sh.j2", state)
    bins = stubs(tempfile.mkdtemp(), rules=[], table_default=True, egress=True,
                 handshake=now - 30)
    p, calls, written = run(script, bins, state)
    if "rule add uidrange" not in calls:
        failures.append(f"1: the app rule was not restored\n{calls}")
    if "rule add from all lookup 100 priority 1010" not in calls:
        failures.append(f"1: the root rule was not restored\n{calls}")
    if "restart wg-quick@wg0" in calls:
        failures.append("1: restarted the tunnel although the handshake was 30s old")
    if "try-restart encar-backend" not in calls:
        failures.append("1: the backend was not restarted after a repair (stuck pools)")
    if '"egress_ok":true' not in written.replace(" ", ""):
        failures.append(f"1: state not written: {written}")
    print("1 rules deleted:", "ok" if not failures else "FAIL")

    # 2. Healthy host: the guard must touch nothing.
    state2 = tempfile.mktemp()
    bins2 = stubs(tempfile.mkdtemp(), rules=good_rules, table_default=True, egress=True,
                  handshake=now - 20)
    p2, calls2, written2 = run(script, bins2, state2)
    noisy = [ln for ln in calls2.splitlines()
             if "add" in ln or "replace" in ln or "restart" in ln]
    if noisy:
        failures.append(f"2: changed something on a healthy host: {noisy}")
    print("2 healthy host:", "ok" if not noisy else "FAIL")

    # 3. Table flushed as well as the rules.
    state3 = tempfile.mktemp()
    bins3 = stubs(tempfile.mkdtemp(), rules=good_rules, table_default=False, egress=True,
                  handshake=now - 20)
    p3, calls3, _ = run(script, bins3, state3)
    if "route replace default via 10.99.0.1 dev wg0 src 10.99.0.2 table 100" not in calls3:
        failures.append(f"3: the table default was not restored\n{calls3}")
    print("3 table flushed:", "ok" if "src 10.99.0.2 table 100" in calls3 else "FAIL")

    # 4. No egress and a dead handshake: only now may it restart the tunnel.
    state4 = tempfile.mktemp()
    # Its own rendered copy: the state path is baked into the script, so reusing case 1's
    # would have it write case 1's file and the assertion below would read an empty string.
    script4 = render("nat-guard-back.sh.j2", state4)
    bins4 = stubs(tempfile.mkdtemp(), rules=good_rules, table_default=True, egress=False,
                  handshake=now - 4000)
    p4, calls4, written4 = run(script4, bins4, state4)
    if "restart wg-quick@wg0" not in calls4:
        failures.append(f"4: the tunnel was not restarted\n{calls4}")
    if "try-restart encar-backend" in calls4:
        failures.append("4: restarted the backend while egress was still broken")
    if '"egress_ok":false' not in written4.replace(" ", ""):
        failures.append(f"4: state should say egress_ok false: {written4}")
    print("4 dead tunnel:", "ok" if "restart wg-quick@wg0" in calls4 else "FAIL")

    # 5. front1: forwarding and MASQUERADE.
    fstate = tempfile.mktemp()
    fscript = render("nat-guard-front.sh.j2", fstate)
    fbins = Path(tempfile.mkdtemp())
    stubs(fbins, rules=[], table_default=True, egress=True, handshake=now)
    (fbins / "sysctl").write_text(
        f'#!/bin/bash\necho "sysctl $*" >> {fbins}/calls.log\n'
        '[ "$1" = "-n" ] && echo 0\nexit 0\n')
    (fbins / "iptables").write_text(f'#!/bin/bash\necho "iptables $*" >> {fbins}/calls.log\n'
                                    '[ "$2" = "nat" ] && [ "$3" = "-C" ] && exit 1\nexit 0\n')
    for n in ("sysctl", "iptables"):
        (fbins / n).chmod(0o755)
    p5, calls5, _ = run(fscript, fbins, fstate)
    if "sysctl -q -w net.ipv4.ip_forward=1" not in calls5:
        failures.append(f"5: forwarding was not turned back on\n{calls5}")
    if "-A POSTROUTING -s 10.99.0.2/32 -o eth0 -j MASQUERADE" not in calls5:
        failures.append(f"5: MASQUERADE was not restored\n{calls5}")
    print("5 front1 guard:", "ok" if "MASQUERADE" in calls5 else "FAIL")

    # 6. Both scripts must be valid bash.
    for name in ("nat-guard-back.sh.j2", "nat-guard-front.sh.j2"):
        s = render(name, tempfile.mktemp())
        r = subprocess.run(["bash", "-n", str(s)], capture_output=True, text=True)
        if r.returncode != 0:
            failures.append(f"6: {name} is not valid bash: {r.stderr}")
    print("6 bash syntax:", "ok" if not any("6:" in f for f in failures) else "FAIL")

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(" -", re.sub(r"\n+", " | ", f))
        raise SystemExit(1)
    print("\nall nat-guard cases pass")


if __name__ == "__main__":
    main()
