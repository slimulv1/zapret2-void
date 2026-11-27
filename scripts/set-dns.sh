#!/bin/sh
# Tuỳ chọn: trỏ DNS của interface WAN về dnscrypt-proxy (127.0.0.1).
# Không được scriptlet gọi tự động vì sẽ ngắt mạng vài giây.
set -eu
IFACE="${IFACE:-eno1}"
[ "$(id -u)" -eq 0 ] || { echo "chạy bằng root" >&2; exit 1; }
uuid=$(nmcli -g GENERAL.CON-UUID device show "$IFACE" 2>/dev/null | head -1)
[ -n "$uuid" ] || { echo "không tìm thấy kết nối NetworkManager cho $IFACE" >&2; exit 1; }
nmcli connection modify uuid "$uuid" ipv4.dns 127.0.0.1 ipv4.ignore-auto-dns yes
nmcli connection up uuid "$uuid" >/dev/null
echo "DNS của $IFACE -> 127.0.0.1"
