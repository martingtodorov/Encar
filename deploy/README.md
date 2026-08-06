# Deploying Europe Encar from a Mac with Ansible

Everything needed to put this app on two Hetzner boxes. systemd + venv on the host, **no
Docker**. Written to be followed literally: the "hard rules" section exists because each item
in it has already broken a deploy at least once.

- **Domain**: `encareurope.com` (add more in `site_domains`; the first is canonical)
- **Stack**: React (CRA) + FastAPI + MongoDB 7, Claude for all translations
- **Repo layout**: `backend/` (FastAPI), `frontend/` (CRA), `deploy/hetzner/ansible/`

---

## 1. Topology

| Host | Address | Runs |
|---|---|---|
| `front1` | `178.105.37.1` public, `10.0.0.2` private | nginx, the static build, TLS, NAT gateway |
| `back1` | `10.0.0.3` private only | FastAPI on `:8001`, MongoDB on `127.0.0.1:27017` |

`back1` has **no public IPv4**, so it reaches the internet through `front1` (see `deploy_nat.yml`).
Everything public is behind Cloudflare (Full Strict) with an Origin certificate on `front1`.

```bash
ssh -i ~/.ssh/autoandbid_root -o IdentitiesOnly=yes root@178.105.37.1                  # front1
ssh -i ~/.ssh/id_ed25519 -o IdentitiesOnly=yes -J root@178.105.37.1 deploy@10.0.0.3    # back1
```

Nothing in this repo touches `sshd_config`, your keys or `authorized_keys`. The only lockout
risk is the firewall, so the ssh port is the variable `ssh_port` (default 22) — set it before
the first run if your sshd is not on 22.

## 2. Files

```
deploy/hetzner/ansible/
├── ansible.cfg
├── inventory.ini.example              → copy to inventory.ini      (gitignored)
├── group_vars/all.yml.example         → copy to all.yml + vault     (gitignored)
├── playbooks/
│   ├── deploy_nat.yml                 front1 becomes back1's way out (run once, first)
│   ├── deploy_backend.yml             Mongo, venv, env, systemd unit, health gate
│   ├── deploy_frontend.yml            Node 20, yarn build, atomic symlink swap
│   ├── deploy_nginx.yml               site config, TLS, firewall
│   └── site.yml                       all four, in the only order that works
└── templates/
    ├── backend.env.j2
    ├── encar-backend.service.j2
    └── nginx-encar.conf.j2
```

## 3. First time

```bash
cd deploy/hetzner/ansible
ansible-galaxy collection install community.general ansible.posix   # ufw, sysctl
cp inventory.ini.example inventory.ini                              # hosts + key paths
cp group_vars/all.yml.example group_vars/all.yml                    # domains + secrets
ansible-vault encrypt group_vars/all.yml
```

The Cloudflare Origin certificate goes on `front1` **by hand** — Ansible never writes secrets:

```bash
scp cert.pem key.pem root@178.105.37.1:/etc/ssl/encar/    # then chmod 600
```

Cloudflare dashboard → SSL/TLS → Origin Server → Create Certificate, covering
`encareurope.com` and `*.encareurope.com`. It is valid 15 years; no certbot, no renewal cron.
`deploy_nginx.yml` refuses to run without both files and says so.

## 4. Deploy

```bash
ansible-playbook -i inventory.ini playbooks/deploy_nat.yml                     # once
ansible-playbook -i inventory.ini playbooks/deploy_backend.yml  -e "ref=main"
ansible-playbook -i inventory.ini playbooks/deploy_frontend.yml -e "ref=main"
ansible-playbook -i inventory.ini playbooks/deploy_nginx.yml    -e "ref=main"
```

`site.yml` runs all four. `ref` is any branch, tag or commit — the playbooks clone from
`repo_url`, so **push first**; nothing is copied from a laptop.

Tags: `base`, `mongo`, `code`, `build`, `config`, `service`, `publish`, `firewall`, `backup`,
`gateway`, `client`, `verify`. Example: `--tags config,service` to push an env change and restart.

## 5. Environment variables

Written to `/etc/encar/backend.env` (0640 root:www-data) from `group_vars` by
`templates/backend.env.j2`. **systemd reads `EnvironmentFile` when the process starts**, so a
restart picks up changes; `reload` does not.

### These three stop the boot

Read at import time. A missing one kills uvicorn before it binds port 8001 and the deploy fails
with nothing but `connection refused`.

| Key | Value |
|---|---|
| `MONGO_URL` | `mongodb://localhost:27017` |
| `DB_NAME` | `encar` |
| `MEDIA_ROOT` | `/var/lib/encar/media` — must exist and be writable by `www-data` |

`server.py` checks all three up front and names every missing one at once.

### These break a feature, silently, later

| Key | Without it |
|---|---|
| `ANTHROPIC_API_KEY` (+ `ANTHROPIC_MODEL`, `ANTHROPIC_FAST_MODEL`) | no translations at all |
| `ADMIN_TOKEN` | no admin panel |
| `ADMIN_SEED_PASSWORD` | no first admin account |
| `TOTP_ENCRYPTION_KEY` | 2FA cannot be enrolled |
| `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_MODE` | no deposits |
| `RESEND_API_KEY`, `SENDER_EMAIL`, `ADMIN_NOTIFY_EMAIL` | no email leaves the box |
| `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` | no push notifications |
| `JSONCARGO_API_KEY`, `JSONCARGO_SHIPPING_LINE`, `EDI_INGEST_TOKEN` | no shipment tracking |
| `PUBLIC_SITE_URL`, `CORS_ORIGINS` | wrong links in emails, browser blocks the API |
| `MAERSK_PUBLIC_TRACK` | leave at `0` (see hard rules) |

Your **own** Anthropic key is required. The Emergent universal key only works on that platform.

## 6. On the hosts

| Path | What |
|---|---|
| `/opt/encar/releases/<ref>-<stamp>` | one checkout per deploy, last 5 kept |
| `/opt/encar/current` → release | what systemd runs; `previous` is the one before |
| `/opt/encar/venv` | Python venv (system `python3`, 3.12 on Noble) |
| `/etc/encar/backend.env` | the environment file |
| `/var/lib/encar/media` | archived photos of purchased cars — **persistent, never wipe** |
| `/var/www/encar/build` → release | what nginx serves; `build.previous` is the one before |
| `/etc/ssl/encar/{cert,key}.pem` | Cloudflare Origin cert |
| `/var/backups/encar` | nightly `mongodump`, 14 days |

## 7. Hard rules

1. **One uvicorn worker. Always.** The catalogue sync, the FX watchdog, the price-drop watch and
   the saved-search watch all schedule **in-process**. Two workers = two crawls of Encar and two
   copies of every alert email. `--workers 1` in the unit; the shipped unit already says so.
2. **`/var/lib/encar/media` must survive a deploy.** Photos of cars people have paid a deposit on
   live there and are served by the backend at `/api/media`. If the unit has
   `ProtectSystem=strict` it also needs `ReadWritePaths=/var/lib/encar/media`.
3. **`REACT_APP_BACKEND_URL` must be EMPTY at build time.** CRA bakes it in; empty means "same
   origin", which is what lets one build answer on every brand domain through nginx's `/api/`.
   A value pointing at one domain breaks the others. `yarn build` also runs `prebuild`
   (`scripts/gen-seo-files.js`), which reads `REACT_APP_SITE_URL` for `sitemap.xml` and
   `robots.txt` — pass `https://encareurope.com`.
4. **`proxy_buffering off` on `/api/`.** The dealer-description translation is streamed (SSE);
   buffering holds the whole answer back and the visitor watches a spinner.
5. **HTTPS is not optional.** Sessions and passkeys are Secure-cookie only, and the passkey
   relying-party id comes from the request origin — the domain you sign in on is the domain the
   passkey belongs to.
6. **`requirements.txt` must stay installable off-platform.** `pip freeze` inside the Emergent
   pod captures `emergentintegrations` (private index) and a `litellm` wheel pinned to an
   emergentagent.com URL; both were removed and neither is imported.
   `python -m pytest backend/tests/test_requirements_portable.py -q` fails if a URL pin, an
   unpinned line or agent tooling creeps back in. **Run it before every deploy.**
7. **Leave `MAERSK_PUBLIC_TRACK=0`.** Akamai refuses datacenter IPs, so reading Maersk's public
   page costs 30 seconds and a Chromium to fail. Nothing else needs Playwright, which is why no
   browser is installed.
8. **Email cannot deliver** until `ADMIN_NOTIFY_EMAIL` is set and a domain is verified in Resend.
   The shared `onboarding@resend.dev` sender only reaches the Resend account owner.

## 8. First run: the database is empty

The catalogue can be re-crawled from Admin → Catalogue sync, but a full crawl takes hours and
some collections are worth carrying over from the old box — `translations` (already paid for),
`taxonomy_overrides` (model merges and renames), `users`, `purchases`, `deposits`, `shipments`,
`shipment_events`, `settings`.

```bash
python deploy/export_data.py            # writes gzipped JSON
python deploy/import_data.py <dir>      # on the new box
```

Then create the first admin: `ADMIN_SEED_PASSWORD` must be set, and run
`/opt/encar/venv/bin/python /opt/encar/current/backend/seed_admin.py`.

## 9. Verify after a deploy

```bash
# on back1
curl -s localhost:8001/api/health                       # {"ok":true,...}
systemctl show -p MainPID --value encar-backend         # non-zero
pgrep -fc 'uvicorn server:app'                          # must be 1, not 2
curl -sS https://ifconfig.me                            # front1's public IP -> NAT works

# from anywhere
curl -sI https://encareurope.com | head -1              # 200
curl -s https://encareurope.com/api/health              # through nginx
curl -s https://encareurope.com/api/fx                  # rates present -> Mongo + FX alive
```

## 10. Rollback

```bash
# backend
sudo ln -sfn "$(readlink /opt/encar/previous)" /opt/encar/current && sudo systemctl restart encar-backend
# frontend
ln -sfn "$(readlink /var/www/encar/build.previous)" /var/www/encar/build
```

Logs: `journalctl -fu encar-backend`, `journalctl -fu nginx`, `/var/log/nginx/error.log`.

## 11. Failures already seen, and the cause

| Symptom | Cause |
|---|---|
| `No matching distribution found for emergentintegrations==0.2.0` | platform-only package in `requirements.txt` — removed; rule 6 |
| `KeyError: 'MEDIA_ROOT'`, then `connection refused` on `:8001` | the env file lacked `MEDIA_ROOT`; the code-only playbook never wrote the env file |
| `SpawnProcess-2` in the journal | more than one uvicorn worker — rule 1 |
| Health check retries forever | the process is dying at import; read `journalctl -u encar-backend -n 60 --no-pager`, never guess |
| Integrations all fail on `back1` | no route out — run `deploy_nat.yml` |
| `Read-only file system` writing media | `ProtectSystem=strict` without `ReadWritePaths` |

## 12. If you reuse the Auto&Bid playbooks instead

They work, with three changes — details and a ready template in
`deploy/hetzner/autobid-tooling/`:

1. Their `deploy_backend.yml` is **code-only** and never writes the env file, so `MEDIA_ROOT`
   never arrives. Add the env template step (provided, using their variable names).
2. Set `--workers 1` in their unit template.
3. Their `deploy_frontend.yml` aborts unless nginx contains `alias /opt/autobids/uploads` and
   probes `/uploads/` for a 404. That is the other app's CDN design; this app serves archived
   photos from the backend at `/api/media`. Drop those two checks or point them at `/api/media/`.
