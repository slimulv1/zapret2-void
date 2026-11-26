# Public key repo

Sau lần build đầu tiên, maintainer publish file public key dạng XBPS plist tại:

```
repo-keys/x86_64/<fingerprint>.plist
```

để client cài không phải trả lời fingerprint thủ công:

```sh
PUBKEY_URL=https://raw.githubusercontent.com/slimulv1/zapret2-void/main/repo-keys/x86_64/<fingerprint>.plist \
  sudo ./install-zapret2.sh
```

Hoặc tự tải file đó vào `/var/db/xbps/keys/` rồi chạy `xbps-install -S`.

Private key (`PRIV_KEY` secret) tuyệt đối không được commit vào repo này.
