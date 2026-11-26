# zapret2-void

Repo void-packages overlay cho **zapret2** ([bol-van/zapret2](https://github.com/bol-van/zapret2)), mô phỏng cơ chế tự động của [xlibre-void/xlibre](https://github.com/xlibre-void/xlibre).

Mục tiêu: khi upstream phát hành bản mới, workflow tự cập nhật `template`, build gói `.xbps` cho Void Linux, ký và đăng release. Trên máy client, repo và cron tự giữ zapret2 ở bản mới nhất.

## Cấu trúc

```
.github/workflows/update-template.yml   # cron 04:00 UTC: chạy mọi srcpkgs/*/update.sh, commit/push
.github/workflows/build.yml             # push srcpkgs/** -> build + ký + release .xbps
srcpkgs/zapret2/
  template                              # xbps template (build_style=fetch, archs=x86_64*)
  update.sh                             # kiểm tra release mới, cập nhật version/checksum
  files/zapret2/{run,finish,config}     # runit service + profile DPI
scripts/
  install-zapret2.sh                    # one-line installer cho client Void Linux
  zapret2-pkg-autoupdate                # cron root: sync/update/restart có kiểm tra
  zapret2-autoupdate.cron               # file cron mẫu
99-repository-zapret2.conf              # file repo conf
```

## Secrets cần thiết (GitHub Settings → Secrets and variables → Actions)

| Secret | Mục đích |
|---|---|
| `PULL_PUSH` | PAT có quyền `repo` để workflow commit/push (dùng `GITHUB_TOKEN` sẽ không kích hoạt `build.yml`). |
| `PRIV_KEY` | Private RSA PEM (`ssh-keygen -t rsa -b 4096 -m PEM -f private.pem`) dùng ký repo/packages. **Không commit.** |
| `SIGN_PASS` | Passphrase của private key (nếu có). |

Khi client chạy `xbps-install -S`, xbps sẽ hỏi chấp nhận fingerprint của repo — gõ `y` một lần. Các lần sau không hỏi nữa.

## Cài đặt trên Void Linux (client)

```sh
wget -O - https://raw.githubusercontent.com/slimulv1/zapret2-void/main/scripts/install-zapret2.sh \
  | tee install-zapret2.sh && chmod +x install-zapret2.sh && sudo ./install-zapret2.sh
```
(Kiểu two-step như xlibre để script không chiếm stdin khi xbps hỏi fingerprint.)

Script sẽ: thêm `/etc/xbps.d/99-repository-zapret2.conf`, sync repo (bạn nhấn `y` khi hỏi fingerprint), cài `zapret2`, bật service runit, và cài cron `/etc/cron.d/zapret2-autoupdate` để tự cập nhật lúc 03:20 mỗi ngày.

Kiểm tra:

```sh
sv status zapret2
/opt/zapret2/nfq2/nfqws2 --version
nft list table inet zapret2
ss -lunt 'sport = :53'
```

## Cơ chế cập nhật

1. `update-template.yml` chạy daily, tìm `srcpkgs/*/update.sh`.
2. `update.sh` gọi GitHub API `releases/latest` của bolt-van/zapret2, kiểm tra tag numeric, không draft/prerelease, chặn downgrade, yêu cầu release cũ hơn 24h (override bằng `SOAK_SECONDS`), tải đúng **release asset** `zapret2-vX.tar.gz`, tính SHA-256 và đối chiếu với `asset.digest` của API, rồi sửa `version`, `revision=1`, `checksum` trong `template`.
3. Commit/push tự động kích hoạt `build.yml`, build `.xbps` cho `x86_64` (glibc + musl), ký, ghi checksum, đăng GitHub Release.
4. Cron trên client `xbps-install -S` rồi `xbps-install -u zapret2`; nếu version đổi thì preflight mạng và `sv restart zapret2`.

## Lưu ý bảo mật

- Repo bên thứ ba không được Void Linux hậu thuẫn; chỉ dùng khi bạn tin tưởng maintainer.
- `update.sh` **không** dùng `gh release download --archive=tar.gz` (đó là source archive của repo, không phải release asset chứa binary). Archive integrity lấy từ `asset.digest`; 3 binary được installer/kiểm tra riêng qua `sha256sum.txt`.
- Cron restart service có thể làm đứt DNS vài giây; vì vậy chạy vào cửa sổ đêm và có preflight network.

## Disclaimer

Repo không chính thức, không liên kết với Void Linux hay bol-van/zapret2. Upstream không khai báo license trong repo (`license: null`, không có file LICENSE), nên template dùng `license="custom:..."`.
