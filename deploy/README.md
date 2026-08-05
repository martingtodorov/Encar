# Running Europe Encar on your own Hetzner box

Two things live here: **Ansible**, which sets up the server and keeps it up to date, and the
**Docker images** it runs. You only ever touch Ansible.

## 1. Once, on your laptop

```bash
pip install ansible
ansible-galaxy collection install community.docker community.general

cd deploy/ansible
cp inventory.ini.example inventory.ini            # the server's IP
cp group_vars/all.yml.example group_vars/all.yml  # domain + every secret
ansible-vault encrypt group_vars/all.yml          # keep secrets encrypted
```

Point your domain's A record at the server first: Caddy asks Let's Encrypt for the
certificate on the first run, and that only works once DNS resolves.

## 2. Deploy (and every release after that)

```bash
ansible-playbook -i inventory.ini deploy.yml --ask-vault-pass
```

What it does: installs Docker, closes every port except 22/80/443, checks out the repo into
`/opt/europe-encar`, writes `deploy/.env` from your vars, builds and starts Mongo + backend +
nginx + Caddy, waits for `https://<domain>/api/health`, and installs a nightly `mongodump`
into `/var/backups` (kept a fortnight). Re-running is safe; use `--tags run` to restart
without touching the system packages.

## 3. Bring your data across

The catalogue can be re-crawled, but the translations are already paid for and the merges and
customers are yours. On the OLD machine:

```bash
python3 deploy/export_data.py --out /tmp/encar-dump
# add --with-listings if you would rather copy the catalogue than re-crawl it
```

Copy the folder over, then on the NEW machine:

```bash
python3 deploy/import_data.py --dir /tmp/encar-dump \
  --uri mongodb://localhost:27017 --db encar
```

It writes by `_id`, so running it twice changes nothing. What comes across: `translations`,
`taxonomy`, `taxonomy_overrides` (your renames and merges), `model_years`, `settings`,
`sync_state`, `facets`, plus `users`, `purchases`, `shipments`, `enquiries`, passkeys and 2FA
secrets. Without `--with-listings` the first catalogue sync fills the cars back in.

Archived photos of purchased cars are files, not database rows. Copy the `media` volume too:

```bash
docker compose -f deploy/docker-compose.yml cp ./media-backup/. backend:/data/media/
```

## 4. Things that will bite you if you skip them

* **HTTPS is not optional.** Sessions and passkeys use `Secure` cookies; on plain http nobody
  can sign in. Caddy handles it, but if you put your own proxy in front it MUST pass
  `X-Forwarded-Proto`.
* **One backend process.** The catalogue sync and the price watcher schedule themselves inside
  the process, so a second worker crawls twice and sends every price email twice. The image
  runs `--workers 1` on purpose.
* **`PUBLIC_SITE_URL`** is the address in email logos and share previews. Ansible sets it from
  `site_domain`; nothing else to do.
* **`ADMIN_TOKEN` has no default in the code.** Leave it empty and the admin API refuses the
  header route outright — which is safe, but you will wonder why it 401s.
* **Your own LLM keys.** Translations use `ANTHROPIC_API_KEY` (and `GEMINI_API_KEY`) directly;
  the Emergent universal key only worked inside Emergent.
* **Stripe webhook** must be re-pointed at `https://<domain>/api/deposits/webhook`, and the
  new signing secret put in `stripe_webhook_secret`.

## 5. Without Ansible

The same stack starts by hand from the repo root:

```bash
cp deploy/.env.example deploy/.env && $EDITOR deploy/.env
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build
```
