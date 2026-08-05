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
ansible-playbook -i inventory.ini playbooks/deploy_backend.yml  -e "ref=main"
ansible-playbook -i inventory.ini playbooks/deploy_frontend.yml -e "ref=main"
ansible-playbook -i inventory.ini playbooks/deploy_nginx.yml    -e "ref=main"
```

`playbooks/site.yml` runs all three in that order. `ref` is any branch, tag or commit.
Tags: `base`, `mongo`, `code`, `build`, `config`, `service`, `publish`, `firewall`, `backup`.

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
