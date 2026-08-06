# Making the Auto&Bid tooling deploy THIS app

Three files were shared: `inventory.ini`, `deploy_backend.yml`, `deploy_frontend.yml`,
`deploy_nginx.yml` and a `bootstrap.yml` that only calls a `common` role. The roles themselves
were not shared, so the exact env template on the box could not be read — but the reason the
backend would not start is visible from the playbooks alone.

## 1. Why MEDIA_ROOT was missing (the actual failure)

`deploy_backend.yml` is a **code-only** redeploy: snapshot → git → rsync → pip → restart →
health. It never writes `/etc/autobids/backend.env`. That file was written ONCE, by a role
built for Auto&Bid, whose media variable is `upload_dir` / `UPLOAD_DIR` — this app reads
`MEDIA_ROOT`, and reads it at import time in `archive.py`, so uvicorn dies before it binds a
port and the deploy reports only "connection refused".

Fix it properly by writing the env file on every deploy — drift then becomes impossible.
Add this to `deploy_backend.yml` **before** "Restart backend" (`backend.env.j2` in this folder):

```yaml
    - name: Environment file
      ansible.builtin.template:
        src: "{{ playbook_dir }}/../templates/backend.env.j2"
        dest: "{{ secrets_dir }}/backend.env"
        owner: root
        group: "{{ service_group }}"
        mode: "0640"

    - name: Media directory (archived photos of purchased cars — persistent)
      ansible.builtin.file:
        path: "{{ media_dir | default('/var/lib/encar/media') }}"
        state: directory
        owner: "{{ service_user }}"
        group: "{{ service_group }}"
        mode: "0755"
```

The three variables that stop the boot: `MONGO_URL`, `DB_NAME`, `MEDIA_ROOT`. `server.py` now
checks all three up front and names every missing one at once instead of dying on the first.

## 2. One uvicorn worker, not two

The journal shows `SpawnProcess-2`, so the unit runs more than one worker. The catalogue sync,
the FX watchdog, the price-drop watch and the saved-search watch all schedule **in-process** —
two workers means two crawls of Encar and two copies of every alert email.

In the role's unit template: `--workers 1`, then `daemon-reload` and restart. Also worth having:

```ini
KillSignal=SIGINT
TimeoutStopSec=45          # the shutdown hook records an interrupted crawl
ReadWritePaths={{ media_dir }}   # required if the unit has ProtectSystem=strict
```

## 3. `deploy_frontend.yml` will fail on a check that does not apply

Around lines 104-110 it aborts unless the nginx config contains `alias /opt/autobids/uploads`,
and around line 190 it probes `/uploads/…` expecting 404. That is the Auto&Bid CDN
architecture. This app has no `/uploads/`: archived photos are served by the backend itself,
mounted at **`/api/media`** (`server.py`, `app.mount("/api/media", StaticFiles(...))`), so they
travel through the existing `/api/` proxy and need no alias and no CDN vhost.

Either drop those two checks or point them at `/api/media/`. Keeping them means a healthy
deploy fails on a rule about a different application.

## 4. `frontend.env.production` must leave the backend URL empty

`REACT_APP_BACKEND_URL` is baked in by CRA at build time. Empty means "same origin", which is
what makes one build answer on every brand domain through nginx's `/api/`. A value pointing at
a single domain breaks the other two.

## 5. `/api/media/` in nginx

Nothing extra is required — it goes through the `/api/` proxy. If you want it cached at the
edge instead of asking the backend every time, a dedicated block helps, because those files
never change once written:

```nginx
location /api/media/ {
    proxy_pass http://ab-back1:8001;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header Connection "";
    add_header Cache-Control "public, max-age=2592000";
}
```

Keep `proxy_buffering off` on the main `/api/` block: the dealer-description translation is
streamed, and buffering it holds the whole answer back until it is finished.
