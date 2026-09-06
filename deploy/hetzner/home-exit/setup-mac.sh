#!/usr/bin/env bash
# Turn this Mac into the home exit for api.encar.com (see README.md).
#
#   sudo ./setup-mac.sh <front1 public IP> <front1 wg0 public key> [wg port] [proxy port]
#
# front1's key:   ssh root@<front1> wg show wg0 public-key
#
# What it does, all idempotent:
#   * WireGuard key pair in $(brew --prefix)/etc/wireguard (private key never leaves the Mac)
#   * wg0.conf that DIALS front1 (this Mac sits behind home NAT — nothing to open at home)
#   * tinyproxy on the tunnel, reachable only from back1, allowed to talk only to *.encar.com
#   * a LaunchDaemon so the tunnel comes back after a reboot; tinyproxy via brew services
#   * prints the public key you paste into group_vars/all.yml as home_exit_pubkey
set -euo pipefail

FRONT_IP="${1:?front1 public IP}"
FRONT_PUB="${2:?front1 wg0 public key}"
WG_PORT="${3:-51820}"
PROXY_PORT="${4:-8888}"
HOME_IP="10.99.0.3"        # home_exit_ip in group_vars
BACK_IP="10.99.0.2"        # wg_back_ip
FRONT_TUN_IP="10.99.0.1"   # wg_front_ip
LABEL="com.encar-europe.wg0"

if [ "$(id -u)" -ne 0 ]; then echo "run with sudo" >&2; exit 2; fi
# brew refuses to run as root; find the invoking user's brew.
OWNER="${SUDO_USER:-$(stat -f %Su /dev/console)}"
BREW="$(sudo -u "$OWNER" bash -lc 'command -v brew')"
PREFIX="$(sudo -u "$OWNER" "$BREW" --prefix)"

for f in wireguard-tools wireguard-go tinyproxy; do
  sudo -u "$OWNER" "$BREW" list "$f" >/dev/null 2>&1 || sudo -u "$OWNER" "$BREW" install "$f"
done

WG_DIR="$PREFIX/etc/wireguard"
install -d -m 700 "$WG_DIR"
if [ ! -f "$WG_DIR/wg0.key" ]; then
  (umask 077 && "$PREFIX/bin/wg" genkey > "$WG_DIR/wg0.key")
fi
PUB="$("$PREFIX/bin/wg" pubkey < "$WG_DIR/wg0.key")"

cat > "$WG_DIR/wg0.conf" <<EOF
# Written by setup-mac.sh. Home exit for api.encar.com; dials front1, never listens.
[Interface]
Address = $HOME_IP/32
PostUp = $PREFIX/bin/wg set %i private-key $WG_DIR/wg0.key

[Peer]
# front1
PublicKey = $FRONT_PUB
Endpoint = $FRONT_IP:$WG_PORT
# Only the tunnel subnet: nothing else on this Mac is routed anywhere near Hetzner.
AllowedIPs = $FRONT_TUN_IP/32, $BACK_IP/32
# Keeps the home NAT mapping alive so front1 can always reach us.
PersistentKeepalive = 25
EOF
chmod 600 "$WG_DIR/wg0.conf"

TP_DIR="$PREFIX/etc/tinyproxy"
install -d "$TP_DIR" "$PREFIX/var/log/tinyproxy" "$PREFIX/var/run/tinyproxy"
printf 'encar\\.com\n' > "$TP_DIR/filter"
cat > "$TP_DIR/tinyproxy.conf" <<EOF
# Written by setup-mac.sh. Reachable only from back1 over the tunnel, only to *.encar.com.
Port $PROXY_PORT
Listen 0.0.0.0
Timeout 60
MaxClients 20
LogFile "$PREFIX/var/log/tinyproxy/tinyproxy.log"
LogLevel Info
PidFile "$PREFIX/var/run/tinyproxy/tinyproxy.pid"
DisableViaHeader Yes
Allow 127.0.0.1
Allow $BACK_IP
ConnectPort 443
ConnectPort 80
Filter "$TP_DIR/filter"
FilterDefaultDeny Yes
EOF

cat > "/Library/LaunchDaemons/$LABEL.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$PREFIX/bin/wg-quick</string><string>up</string><string>wg0</string></array>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>$PREFIX/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>/var/log/$LABEL.log</string>
  <key>StandardErrorPath</key><string>/var/log/$LABEL.log</string>
</dict></plist>
EOF
chmod 644 "/Library/LaunchDaemons/$LABEL.plist"

"$PREFIX/bin/wg-quick" down wg0 2>/dev/null || true
launchctl bootout system "/Library/LaunchDaemons/$LABEL.plist" 2>/dev/null || true
launchctl bootstrap system "/Library/LaunchDaemons/$LABEL.plist"

# As root on purpose: `sudo brew services` installs a LaunchDaemon, so the proxy runs at boot
# with nobody logged in. (Without sudo it would be a per-user login item.)
"$BREW" services restart tinyproxy >/dev/null

# A home exit that sleeps is no exit.
pmset -a sleep 0 disksleep 0 autorestart 1 womp 1 >/dev/null 2>&1 || true

sleep 2
echo
echo "home_exit_pubkey: \"$PUB\""
echo
echo "1. Put that line in group_vars/all.yml, then on your laptop:"
echo "     ./run.sh playbooks/deploy_nat.yml"
echo "     ./run.sh playbooks/deploy_backend.yml --tags config,service"
echo "2. Check here once front1 knows the key:   sudo $PREFIX/bin/wg show"
echo "   A 'latest handshake' line means the tunnel is up."
echo "3. Local proof the proxy only serves Encar:"
echo "     curl -sx http://127.0.0.1:$PROXY_PORT -o /dev/null -w '%{http_code}\\n' 'https://api.encar.com/search/car/list/general?count=true&q=%28And.Hidden.N._.CarType.A.%29&sr=%7CModifiedDate%7C0%7C1'   # 200"
echo "     curl -sx http://127.0.0.1:$PROXY_PORT -o /dev/null -w '%{http_code}\\n' https://example.com/                                # 403"
