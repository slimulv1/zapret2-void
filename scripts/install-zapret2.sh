#!/bin/bash
# Installer: wget -O - <this-file-url> | tee install-zapret2.sh && chmod +x install-zapret2.sh && sudo ./install-zapret2.sh
set -Eeuo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin

REPO_OWNER="${REPO_OWNER:-slimulv1}"
REPO_NAME="${REPO_NAME:-zapret2-void}"
REPO_URL="https://github.com/${REPO_OWNER}/${REPO_NAME}/releases/latest/download"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
die() { printf '\033[31mLOI: %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die 'phai chay bang root'
[ "$(uname -m)" = x86_64 ] || die 'chi ho tro x86_64'
command -v xbps-install >/dev/null 2>&1 || die 'khong tim thay xbps-install'
command -v sv >/dev/null 2>&1 || die 'khong tim thay sv (runit)'

say '1/4  Dang ky repo'
mkdir -p /etc/xbps.d
printf 'repository=%s\n' "$REPO_URL" > /etc/xbps.d/99-repository-zapret2.conf
chmod 0644 /etc/xbps.d/99-repository-zapret2.conf

say '2/4  Sync repo (nhan y khi duoc hoi fingerprint)'
xbps-install -S

say '3/4  Cai zapret2'
xbps-install -y zapret2

say '4/4  Bat service runit'
sv enable zapret2 2>/dev/null || ln -sfn /etc/sv/zapret2 /var/service/zapret2
sv up zapret2 2>/dev/null || true

echo
echo 'Xong. Tu nay chi can chay lenh cap nhat he thong:'
echo '  sudo xbps-install -Syu'
echo 'zapret2 se duoc cap nhat cung cac goi khac; scriptlet cua goi tu restart service.'
echo
echo 'Kiem tra:'
echo '  sv status zapret2'
echo '  /opt/zapret2/nfq2/nfqws2 --version'
echo '  nft list table inet zapret2'
