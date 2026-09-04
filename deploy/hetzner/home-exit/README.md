# Home exit for api.encar.com

CloudFront in front of `api.encar.com` answers **407** to datacenter address space — Hetzner,
AWS, the preview host — and **200** to a residential connection (measured from the owner's home).
So Encar calls leave from the owner's Mac mini; everything else (Stripe, Claude, Resend, GitHub,
apt) still leaves through front1.

```
back1 ──wg0──► front1 ──wg0──► Mac mini ──home ISP──► api.encar.com
 (10.99.0.2)   (10.99.0.1)     (10.99.0.3, tinyproxy :8888)
```

* The Mac **dials** front1 (`Endpoint`, `PersistentKeepalive`). Nothing is opened at home, no
  DDNS; a changing home IP is fine. front1 opens `51820/udp` publicly — WireGuard is silent to
  anyone without the right key.
* front1 forwards between its two wg0 peers. back1 has a main-table route to `10.99.0.3`.
* The backend gets `ENCAR_PROXY_URL=http://10.99.0.3:8888`; only `encar.py` uses it. Photos
  come from `ci.encar.com` (CDN, not blocked) straight to the browser, as before.
* tinyproxy accepts connections only from `10.99.0.2` and only to `*.encar.com`
  (`FilterDefaultDeny`). One fixed address, no rotation — within the politeness policy in
  `/app/memory/encar_api.md` §8.

## Setup

On the Mac (needs Homebrew):

```
ssh root@<front1> wg show wg0 public-key          # front1's key
sudo ./setup-mac.sh <front1 public IP> <that key>
```

It prints `home_exit_pubkey: "..."`. Put it in `group_vars/all.yml`, then on your laptop:

```
./run.sh playbooks/deploy_nat.yml                          # peer on front1, route on back1, verify
./run.sh playbooks/deploy_backend.yml --tags config,service # ENCAR_PROXY_URL into backend.env
```

`deploy_nat.yml --tags verify` now asserts that `api.encar.com` answers **200** through the home
exit as the application user.

## If it stops

| Symptom | Look at |
|---|---|
| verify: ping to 10.99.0.3 fails | Mac: `sudo wg show` — no handshake → Mac asleep / offline / front1 key wrong |
| verify: Encar returns not 200 | Mac: `brew services list`, `/opt/homebrew/var/log/tinyproxy/tinyproxy.log` |
| watchdog "Encar не отговаря" push | same two checks; the site keeps serving the cached catalogue meanwhile |
| Mac rebooted | both are LaunchDaemons: `com.encar-europe.wg0` and `sudo brew services list` |

Roll back to direct calls: clear `home_exit_pubkey`, re-run both playbooks.
