#!/bin/bash
# Installer: wget -O - <this-file-url> | tee install-zapret2.sh && chmod +x install-zapret2.sh && sudo ./install-zapret2.sh
set -Eeuo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin

REPO_OWNER="${REPO_OWNER:-slimulv1}"
REPO_NAME="${REPO_NAME:-zapret2-void}"
REPO_URL="https://github.com/${REPO_OWNER}/${REPO_NAME}/releases/latest/download"
AUTO_SCRIPT=/usr/local/sbin/zapret2-pkg-autoupdate
CRON_FILE=/etc/cron.d/zapret2-autoupdate

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
die() { printf '\033[31mLOI: %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die 'phai chay bang root'
[ "$(uname -m)" = x86_64 ] || die 'chi ho tro x86_64'
command -v xbps-install >/dev/null 2>&1 || die 'khong tim thay xbps-install'
command -v sv >/dev/null 2>&1 || die 'khong tim thay sv (runit)'

say '1/5  Dang ky repo'
mkdir -p /etc/xbps.d
printf 'repository=%s\n' "$REPO_URL" > /etc/xbps.d/99-repository-zapret2.conf
chmod 0644 /etc/xbps.d/99-repository-zapret2.conf

say '2/5  Sync repo (nhan y khi duoc hoi fingerprint)'
xbps-install -S

say '3/5  Cai zapret2'
xbps-install -y zapret2

say '4/5  Bat service runit'
sv enable zapret2 2>/dev/null || ln -sfn /etc/sv/zapret2 /var/service/zapret2
for i in $(seq 1 20); do
    nft list table inet void_filter >/dev/null 2>&1 && break
    sleep 1
done
sv up zapret2 2>/dev/null || true

say '5/5  Cai cron tu cap nhat + script kiem tra'
cat > "$AUTO_SCRIPT" <<'AUTOEOF'
#!/bin/bash
set -Eeuo pipefail
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
LOCK_FILE=/run/lock/zapret2-autoupdate.lock
LOG_FILE=/var/log/zapret2-autoupdate.log
exec 9>"$LOCK_FILE"
flock -n 9 || exit 0
log() { printf '[zapret2-autoupdate] %s\n' "$*" | tee -a "$LOG_FILE"; }
installed_ver() { xbps-query -l 2>/dev/null | awk '$2 ~ /^zapret2-/ {print $2; exit}'; }
before="$(installed_ver || true)"
if ! xbps-install -S >/dev/null 2>&1; then log 'sync repo that bai'; exit 0; fi
if [ -z "$(xbps-query -Rs zapret2 2>/dev/null)" ]; then log 'khong tim thay zapret2'; exit 0; fi
if ! xbps-install -y -u zapret2 >/dev/null 2>&1; then log 'update that bai'; exit 0; fi
after="$(installed_ver || true)"
if [ "$before" = "$after" ]; then log "da ban moi nhat (${after:-chua cai})"; exit 0; fi
log "da nang $before -> $after"
if ! ip route get 1.1.1.1 >/dev/null 2>&1; then log 'khong co route mac dinh; bo qua restart'; exit 0; fi
if ! sv restart zapret2 >/dev/null 2>&1; then log 'restart that bai'; exit 0; fi
sleep 3
log "version: $(/opt/zapret2/nfq2/nfqws2 --version 2>&1 | head -1 || true)"
nft list table inet zapret2 >/dev/null 2>&1 && log 'bang nft inet zapret2: OK' || log 'CANH BAO: bang nft chua co'
AUTOEOF
chmod 0755 "$AUTO_SCRIPT"

cat > "$CRON_FILE" <<'CRONEOF'
SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
MAILTO=""
LC_ALL=C
20 3 * * * root /usr/local/sbin/zapret2-pkg-autoupdate >> /var/log/zapret2-autoupdate.log 2>&1
CRONEOF
chmod 0644 "$CRON_FILE"

say 'Hoan tat. Kiem tra:'
echo '  sv status zapret2'
echo '  /opt/zapret2/nfq2/nfqws2 --version'
echo '  nft list table inet zapret2'
echo '  tail -f /var/log/zapret2-autoupdate.log'
