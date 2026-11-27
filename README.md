# zapret2-void

[![Build](https://github.com/slimulv1/zapret2-void/actions/workflows/build.yml/badge.svg)](https://github.com/slimulv1/zapret2-void/actions/workflows/build.yml)
[![Auto update](https://github.com/slimulv1/zapret2-void/actions/workflows/update-template.yml/badge.svg)](https://github.com/slimulv1/zapret2-void/actions/workflows/update-template.yml)
[![Release](https://img.shields.io/github/v/release/slimulv1/zapret2-void)](https://github.com/slimulv1/zapret2-void/releases/latest)
[![License](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

Overlay Void cho zapret2, auto-update kiểu xlibre.

## Cài

```sh
wget -O - https://raw.githubusercontent.com/slimulv1/zapret2-void/main/scripts/install-zapret2.sh \
  | tee install-zapret2.sh && chmod +x install-zapret2.sh && sudo ./install-zapret2.sh
```

Fingerprint lần đầu: `y`. Có key: `PUBKEY_URL=<url> sudo ./install-zapret2.sh`.

## Update & kiểm tra

```sh
sudo xbps-install -Syu
sv status zapret2
/opt/zapret2/nfq2/nfqws2 --version
nft list table inet zapret2
```

## Cơ chế

- 04:00 UTC: `update.sh` bump template — tag numeric, không draft/prerelease, chặn downgrade, soak 24h, hash release asset + đối chiếu `asset.digest`.
- Push `srcpkgs/**` → build x86_64 glibc/musl, ký, đăng release `v<version>`.
- `INSTALL`: restart service sau upgrade. `REMOVE`: xoá symlink khi gỡ gói (bỏ qua lúc upgrade).
- Cron 15 phút: `dns-autoset.py` quét DoH song song, loại answer poisoned, chọn latency thấp nhất; đổi `server_names` của dnscrypt-proxy sau 2 lần liên tiếp + ngưỡng 20ms. NM DNS vẫn `127.0.0.1` nên không ngắt mạng.

## Gói

`nftables iproute2 python3` · `system_accounts=tpws` · `conf_files=/etc/zapret2/config /etc/nftables.conf /etc/zapret2/dns-candidates /etc/cron.d/zapret2-dns-autoset` · `archs=x86_64*` · `nostrip`.

Đóng gói sẵn: profile zapret2, `/etc/nftables.conf` (bảng `void_filter`), mẫu DNS tại `/usr/share/examples/zapret2/dnscrypt-proxy.toml`. Scriptlet tự thay nftables.conf nếu thiếu `void_filter` (có backup). Không tự đổi NetworkManager DNS — chạy `sudo bash scripts/set-dns.sh` nếu cần.

Sửa danh sách DNS tại `/etc/zapret2/dns-candidates` (mẫu Ghostline); chạy ngay: `sudo python3 /usr/lib/zapret2/dns-autoset/dns-autoset.py`; xem thử không đổi: `--dry-run`. Profile zapret2 mẫu của Ghostline tại `/usr/share/examples/zapret2/strategies.json`.

Config giữ bản cũ; bản mới ở `/etc/zapret2/config.new-<pkgver>`, mẫu tại `/usr/share/examples/zapret2/zapret2-config`.

## License & secrets

Repo: GPL-3.0-or-later. Upstream zapret2 không có license.

Secrets: `PRIV_KEY` (bắt buộc), `SIGN_PASS`, `PULL_PUSH` (tuỳ chọn). Không commit private key.

Repo bên thứ ba, không chính thức.
