# zapret2-void

Repo void-packages overlay cho **zapret2** ([bol-van/zapret2](https://github.com/bol-van/zapret2)), mô phỏng cơ chế của [xlibre-void/xlibre](https://github.com/xlibre-void/xlibre): khi upstream ra bản mới, workflow tự bump `template`, build gói `.xbps`, ký và đăng release. Trên Void Linux, chỉ cần thêm repo — **lệnh cập nhật hệ thống sẽ tự nâng zapret2 cùng các gói khác**.

## Cấu trúc

```
.github/workflows/update-template.yml   # cron 04:00 UTC: chạy srcpkgs/*/update.sh, commit/push
.github/workflows/build.yml             # push srcpkgs/** -> build + ký + release .xbps
srcpkgs/zapret2/
  template                              # build_style=fetch, archs=x86_64*, conf_files
  update.sh                             # kiểm tra release mới, cập nhật version/checksum
  INSTALL                               # scriptlet: tự restart zapret2 sau khi nâng gói
  files/zapret2/{run,finish,config}     # runit service + profile DPI
scripts/install-zapret2.sh              # installer client (two-step, giống xlibre)
99-repository-zapret2.conf              # file repo conf
```

## Secrets GitHub (Settings → Secrets and variables → Actions)

| Secret | Mục đích |
|---|---|
| `PULL_PUSH` | **Tuỳ chọn**: PAT có quyền `repo` + `workflow`. Nếu không set, workflow dùng `GITHUB_TOKEN` và kích hoạt build rõ ràng bằng `gh workflow run`. |
| `PRIV_KEY` | Private RSA PEM (`ssh-keygen -t rsa -b 4096 -m PEM -f private.pem`). **Không commit.** |
| `SIGN_PASS` | Passphrase của private key (nếu có). |

## Cài đặt trên Void Linux

```sh
wget -O - https://raw.githubusercontent.com/slimulv1/zapret2-void/main/scripts/install-zapret2.sh \
  | tee install-zapret2.sh && chmod +x install-zapret2.sh && sudo ./install-zapret2.sh
```

Script thêm `/etc/xbps.d/99-repository-zapret2.conf`, sync repo, cài gói `zapret2` và bật service runit. Dùng kiểu two-step để stdin rảnh cho câu hỏi fingerprint của xbps.

Giống xlibre, repo nên publish public key tại `repo-keys/x86_64/<fingerprint>.plist`. Khi đó cài không cần trả lời fingerprint:

```sh
PUBKEY_URL=https://raw.githubusercontent.com/slimulv1/zapret2-void/main/repo-keys/x86_64/<fingerprint>.plist \
  sudo ./install-zapret2.sh
```

Nếu chưa có key, bỏ qua biến này và nhấn `y` khi xbps hỏi fingerprint lần đầu.

## Tự cập nhật như xlibre

Không cần cron riêng. Chạy lệnh cập nhật Void như thường:

```sh
sudo xbps-install -Syu
```

(hoặc nút **Update all** trong OctoXBPS). Khi repo có gói `zapret2` phiên bản mới, xbps tự nâng nó cùng mọi gói khác. File `srcpkgs/zapret2/INSTALL` có scriptlet `post_upgrade`: nếu service đang chạy và route mặc định còn tốt, nó tự `sv restart zapret2` để dùng binary mới ngay. Nếu bạn đang offline hoặc service đang tắt, scriptlet bỏ qua — bạn có thể restart thủ công sau.

Kiểm tra sau khi update:

```sh
sv status zapret2
/opt/zapret2/nfq2/nfqws2 --version
nft list table inet zapret2
```

## Cơ chế phía repo

1. `update-template.yml` chạy daily, `find srcpkgs -mindepth 2 -maxdepth 2 -name update.sh`.
2. `update.sh`: gọi `gh api repos/bol-van/zapret2/releases/latest`; kiểm tra tag numeric, không draft/prerelease, chặn downgrade, yêu cầu release cũ hơn 24h (`SOAK_SECONDS`), tải đúng **release asset** `zapret2-vX.tar.gz`, tính SHA-256, đối chiếu `asset.digest` của API, rồi sửa `version`, `revision=1`, `checksum` trong `template`. (`sha256sum.txt` của zapret2 chỉ chứa hash binary bên trong, không có hash archive.)
3. Commit/push kích hoạt `build.yml`: build cho `x86_64` glibc + musl, ký repo/packages, ghi checksum, đăng GitHub Release.
4. Client `xbps-install -Syu` thấy bản mới và nâng gói.

## Lưu ý

- Repo bên thứ ba, không được Void Linux hậu thuẫn; chỉ dùng khi tin maintainer.
- Upstream không khai báo license (`license: null`, không có file LICENSE), nên template dùng `license="custom:..."`.
- `PULL_PUSH` bắt buộc: `GITHUB_TOKEN` không kích hoạt workflow khác khi push.

## Disclaimer

Repo không chính thức, không liên kết với Void Linux hay bol-van/zapret2.
