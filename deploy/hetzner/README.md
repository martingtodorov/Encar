# Europe Encar on Hetzner — same shape as the Auto&Bid deploy

systemd + venv on the host, no Docker. Two boxes: the frontend one is public and runs nginx,
the backend one only answers on the private network.

```
ssh -i ~/.ssh/autoandbid_root -o IdentitiesOnly=yes root@178.105.37.1                  # front1
ssh -i ~/.ssh/id_ed25519 -o IdentitiesOnly=yes -J root@178.105.37.1 deploy@10.0.0.3    # back1
```

## First run

```bash
cd deploy/hetzner/ansible
cp inventory.ini.example inventory.ini              # your two hosts + key paths
cp group_vars/all.yml.example group_vars/all.yml    # domains + every secret
ansible-vault encrypt group_vars/all.yml
ansible-galaxy collection install community.general ansible.posix
```

Put the Cloudflare Origin certificate on front1 by hand — Ansible never writes secrets:

```bash
scp cert.pem key.pem root@178.105.37.1:/etc/ssl/encar/   # chmod 600
```

## Deploy

```bash
ansible-playbook -i inventory.ini playbooks/deploy_nat.yml                      # once
ansible-playbook -i inventory.ini playbooks/deploy_backend.yml  -e "ref=main"
ansible-playbook -i inventory.ini playbooks/deploy_frontend.yml -e "ref=main"
ansible-playbook -i inventory.ini playbooks/deploy_nginx.yml    -e "ref=main"
```

`playbooks/site.yml` runs all four in that order. `ref` is any branch, tag or commit.
Tags: `base`, `mongo`, `code`, `build`, `config`, `service`, `publish`, `firewall`, `backup`,
`gateway`, `client`, `verify`.

## The way out (deploy_nat.yml)

back1 has no public IPv4, so the backend's own outbound connections — the catalogue crawl,
Claude, Stripe, Resend, web push — leave through front1 and the world sees front1's address.

**Do NOT point back1's default route at `10.0.0.2`.** Hetzner's private network gives each
server a **/32** address, so the only directly connected neighbour is Hetzner's router
`10.0.0.1`. Measured on these boxes:

```
ip route replace default via 10.0.0.2            # Error: Nexthop has invalid gateway.
ip route replace default via 10.0.0.2 ... onlink # accepted, but:
ip neigh show                                    # 10.0.0.2 dev enp7s0 FAILED  -> nothing flows
```

So the private network is fine as **transport** but useless as an L2 next hop. The playbook
therefore runs a WireGuard point-to-point link over it:

```
back1 10.0.0.3 ──(WireGuard over the Hetzner private network)── front1 10.0.0.2 / 178.105.37.1
   wg0 10.99.0.2 ─────────────────────────────────────────────► wg0 10.99.0.1 ──► internet
                                                     MASQUERADE only for 10.99.0.2/32
```

- **front1**: `net.ipv4.ip_forward=1`, `DEFAULT_FORWARD_POLICY="ACCEPT"`, `wg-quick@wg0`
  listening on `51820/udp` — opened **only** from `backend_private_ip` to
  `frontend_private_ip`, never on the public interface — and a `MASQUERADE` rule for
  `10.99.0.2/32` (the old `10.0.0.0/16` rule is removed by the same blockinfile marker). The
  rule lives in **`/etc/ufw/before.rules`**: ufw rewrites the nat table on every `ufw reload`,
  so a hand-added iptables rule silently vanishes.
- **back1**: `Table = off` in `wg0.conf`, so Hetzner's `default via 10.0.0.1` stays in the
  main table. Policy routing instead: `iptables -t mangle OUTPUT --uid-owner www-data` marks
  the backend's packets `0x1`, `ip rule fwmark 0x1 lookup 100` sends them to table 100, whose
  default is `via 10.99.0.1 dev wg0`. `throw` routes in table 100 for `10.0.0.0/16`,
  `169.254.0.0/16` (metadata), `172.16.0.0/12` and `192.168.0.0/16` make even marked traffic
  fall back to the main table. `rp_filter=2` (loose) is required — replies arrive on `wg0`
  while the route to their source is the main default.
  **SSH, Ansible, apt and private-network traffic never touch the tunnel**, so a dead tunnel
  cannot lock you out of back1.
- The obsolete `/etc/netplan/99-encar-nat.yaml` (which put the invalid `via 10.0.0.2` route
  back on every reboot) is deleted by the playbook.
- Private keys are generated **on each host** with `wg genkey` and applied by `PostUp`
  (`wg set wg0 private-key /etc/wireguard/wg0.key`); only the public halves pass through
  Ansible, so `wg0.conf` holds no secret.
- Then it proves it: `wg show` must have a handshake, the main default route must NOT point at
  front1, `curl ifconfig.me` **as www-data** must print front1's public address (asserted),
  the same call unmarked shows the management path, and HEAD requests to Stripe, Anthropic,
  Resend and Encar go through the tunnel.

Run it **before** `deploy_backend.yml` on a fresh box. If you ever give back1 its own public
IPv4, drop the tunnel and the policy rule and nothing else changes.

Handy on back1: `wg show`, `ip rule show`, `ip route show table encar`,
`runuser -u www-data -- curl -sS https://ifconfig.me`.

## Layout on the hosts

| Path | What |
|---|---|
| `/opt/encar/releases/<ref>-<stamp>` | one checkout per deploy, last 5 kept |
| `/opt/encar/current` → release | what systemd runs; `previous` is the one before |
| `/opt/encar/venv` | Python venv (system python3) |
| `/etc/encar/backend.env` | 0640 root:www-data, written from `group_vars` |
| `/var/lib/encar/media` | archived photos of purchased cars — **persistent, never wipe** |
| `/var/www/encar/build` → release | what nginx serves; `build.previous` is the one before |
| `/etc/ssl/encar/{cert,key}.pem` | Cloudflare Origin cert, dropped by hand |
| `/var/backups/encar` | nightly `mongodump`, 14 days |

## Rollback

```bash
# backend
ssh deploy@back1 'sudo ln -sfn "$(readlink /opt/encar/previous)" /opt/encar/current \
  && sudo systemctl restart encar-backend'
# frontend
ssh root@front1 'ln -sfn "$(readlink /var/www/encar/build.previous)" /var/www/encar/build'
```

## Logs

```bash
journalctl -fu encar-backend
journalctl -fu nginx      # or /var/log/nginx/error.log
```

## Things about THIS app that will bite if changed

- **One uvicorn worker, always.** The catalogue sync, the FX watchdog, the price-drop watch
  and the saved-search watch all schedule in-process. Two workers means two crawls and two
  copies of every alert. The unit file says so too.
- **`REACT_APP_BACKEND_URL` is empty at build time.** CRA bakes it in, and empty means "same
  origin", so one build answers on every brand domain through nginx's `/api`.
- **`/var/lib/encar/media` must survive a deploy.** Photos of cars people have paid a deposit
  on live there and are served from `/api/media`.
- **`requirements.txt` must stay installable off this platform.** The first deploy died on
  `No matching distribution found for emergentintegrations==0.2.0` — `pip freeze` in the
  Emergent pod captures that private wrapper and a `litellm` wheel pinned to an
  emergentagent.com URL. Neither is imported by the app (the universal-key fallback only fires
  when there is no Anthropic key), so both were removed.
  `backend/tests/test_requirements_portable.py` now fails if a URL pin, a platform-only package
  or agent tooling ever creeps back in — run it before a deploy.
- **nginx's HTTP/2 syntax depends on the version.** `http2 on;` only exists from **1.25.1**;
  on older builds (front1 runs one) it is an *unknown directive* and `nginx -t` fails with
  `emerg`, so the deploy stops. `deploy_nginx.yml` reads `nginx -v` into `nginx_version` and
  the template picks `listen 443 ssl http2;` or `listen 443 ssl;` + `http2 on;` accordingly.
  The `protocol options redefined for 0.0.0.0:443` lines are only warnings — they come from the
  other site on this host (`sites-enabled/autoandbid`) declaring different listen options for
  the same port.
- **A fresh Mongo is empty.** Either restore a dump or run the catalogue sync from
  Admin → Catalogue sync (a full crawl takes hours). Worth carrying over from the old box:
  `translations` (already paid for), `taxonomy_overrides` (your merges), `users`, `purchases`,
  `deposits`, `shipments`, `shipment_events`. `export_data.py` / `import_data.py` in the
  parent folder move them as gzipped JSON.
- **HTTPS is not optional.** Sessions and passkeys are Secure-cookie only, and the passkey
  relying-party id comes from the request origin — so the domain you sign in on is the domain
  the passkey belongs to.
- **Email still cannot deliver** until `admin_notify_email` is set and a domain is verified in
  Resend; the shared `onboarding@resend.dev` sender only reaches the Resend account owner.
- **Maersk's public tracker stays off** (`maersk_public_track: 0`): Akamai refuses datacenter
  IPs, so it costs 30s and a Chromium to fail. Nothing else needs Playwright, which is why no
  browser is installed.

## Your ssh access

Nothing here touches `sshd_config`, your keys or `authorized_keys`. The only thing that could
shut you out is the firewall, so the port is a variable: set `ssh_port` in `group_vars/all.yml`
if your sshd is not on 22. The private network (`private_cidr`) is trusted on both boxes, which
is also what lets back1 reach out through front1.
