# zapret2-void

Overlay void-packages cho [zapret2](https://github.com/bol-van/zapret2), theo mô hình [xlibre-void/xlibre](https://github.com/xlibre-void/xlibre): upstream ra bản mới → workflow bump template, build, ký, đăng release. Trên Void, lệnh cập nhật hệ thống tự nâng zapret2.

[Release mới nhất](https://github.com/slimulv1/zapret2-void/releases/latest)

## Cài đặt

```sh
wget -O - https://raw.githubusercontent.com/slimulv1/zapret2-void/main/scripts/install-zapret2.sh \
  | tee install-zapret2.sh && chmod +x install-zapret2.sh && sudo ./install-zapret2.sh
```

Script thêm repo, sync, cài gói và bật service. Lần đầu xbps hỏi fingerprint → gõ `y`. Nếu maintainer đã đăng public key:

```sh
PUBKEY_URL=<url-to-*.plist> sudo ./install-zapret2.sh
```

## Cập nhật & kiểm tra

```sh
sudo xbps-install -Syu          # hoặc "Update all" trong OctoXBPS
sv status zapret2
/opt/zapret2/nfq2/nfqws2 --version
nft list table inet zapret2
```

## Cơ chế

- `update-template.yml` (04:00 UTC): chạy `srcpkgs/zapret2/update.sh` — tag numeric, không draft/prerelease, chặn downgrade, soak 24h, hash đúng release asset và đối chiếu `asset.digest` (sha256sum.txt của zapret2 chỉ có hash binary bên trong).
- `build.yml`: build `x86_64` glibc + musl, ký repo/packages, đăng release `v<version>` (dọn asset cũ cùng tag/arch).
- Scriptlet `INSTALL` tự `sv restart zapret2` sau upgrade khi service đang chạy; `REMOVE` chỉ xoá symlink `/var/service/zapret2` khi gỡ gói thật, không phải lúc upgrade.

## Gói

`depends="nftables iproute2"` · `system_accounts="tpws"` · `conf_files="/etc/zapret2/config"` · `archs="x86_64*"` · binary static nên `nostrip`.

Tác giả upstream: `bol-van` (không có tên/email công khai). Nguồn: `github.com/bol-van/zapret2`. Upstream không có file LICENSE → `license="custom:..."`.

Config của bạn được giữ khi nâng; bản mới lưu ở `/etc/zapret2/config.new-<pkgver>`. So sánh với `/usr/share/examples/zapret2/zapret2-config` rồi quyết định — **đừng tự xoá file `.new`**.

## Maintainer

Secrets: `PRIV_KEY` (RSA PEM), `SIGN_PASS` (tuỳ chọn), `PULL_PUSH` (tuỳ chọn — nếu thiếu, dùng `GITHUB_TOKEN` và `gh workflow run build.yml`). Không commit private key.

Repo bên thứ ba, không chính thức, không liên kết Void Linux hay bol-van.
