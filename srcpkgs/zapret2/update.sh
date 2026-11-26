#!/usr/bin/env bash
# Hardened variant of xlibre-void/xlibre's per-package update.sh.
# Requires: gh, jq, curl, sha256sum, tar, sort -V (GitHub ubuntu runner has all).
set -euo pipefail

__dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TPL="${__dir}/template"
REPO="bol-van/zapret2"
SOAK_SECONDS="${SOAK_SECONDS:-86400}"

j="$(gh api "repos/${REPO}/releases/latest")"

tag="$(jq -r '.tag_name // empty' <<<"$j")"
[ -n "$tag" ] && [[ "$tag" =~ ^v[0-9]+(\.[0-9]+)*$ ]] || { echo "tag không hợp lệ: ${tag:-<rỗng>}" >&2; exit 1; }
[ "$(jq -r '.draft' <<<"$j")" = false ] || { echo "release là draft" >&2; exit 1; }
[ "$(jq -r '.prerelease' <<<"$j")" = false ] || { echo "release là prerelease" >&2; exit 1; }

VERSION="${tag#v}"
CURRENT="$(sed -n 's/^version=//p' "$TPL")"
[ -n "$CURRENT" ] || { echo "template thiếu version" >&2; exit 1; }

# Chặn downgrade: so sánh số, không so sánh chuỗi (v1.0.10 > v1.0.8).
if [ "$(printf '%s\n%s\n' "$CURRENT" "$VERSION" | sort -V | tail -1)" = "$CURRENT" ]; then
    echo "Không có bản mới (current=$CURRENT latest=$VERSION)"
    exit 0
fi

# Soak: tránh áp dụng release vừa đăng (mặc định 24h).
published="$(jq -r '.published_at // empty' <<<"$j")"
if [ -n "$published" ]; then
    age=$(( $(date -u +%s) - $(date -u -d "$published" +%s) ))
    if [ "$age" -lt "$SOAK_SECONDS" ]; then
        echo "Soak: release mới ${age}s (< ${SOAK_SECONDS}s), bỏ qua"
        exit 0
    fi
fi

# QUAN TRỌNG: hash trên release asset, KHÔNG phải `gh release download --archive=tar.gz`
# (đó là source archive của repo). sha256sum.txt của zapret2 cũng KHÔNG chứa hash archive.
asset="zapret2-${tag}.tar.gz"
digest="$(jq -r --arg a "$asset" '.assets[] | select(.name == $a) | .digest // empty' <<<"$j")"
[ -n "$digest" ] || { echo "Không tìm thấy asset hoặc digest: $asset" >&2; exit 1; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
curl -fL --proto '=https' --tlsv1.2 --retry 3 --max-time 300 \
    "https://github.com/${REPO}/releases/download/${tag}/${asset}" -o "${tmp}/${asset}"

sha="$(sha256sum "${tmp}/${asset}" | awk '{print $1}')"
[[ "$sha" =~ ^[a-f0-9]{64}$ ]] || { echo "SHA-256 không hợp lệ" >&2; exit 1; }
[ "$sha" = "${digest#sha256:}" ] || { echo "Digest mismatch: API=$digest local=$sha" >&2; exit 1; }

if tar -tzf "${tmp}/${asset}" | grep -Eq '(^/|(^|/)\.\.(/|$))'; then
    echo "Archive chứa đường dẫn không an toàn" >&2
    exit 1
fi

[ -n "$VERSION" ] && [ -n "$sha" ] || exit 1
sed -i "s/^version=.*/version=${VERSION}/" "$TPL"
sed -i "s/^revision=.*/revision=1/" "$TPL"
sed -i "s/^checksum=.*/checksum=${sha}/" "$TPL"
echo "zapret2 template: ${CURRENT} -> ${VERSION} (${sha})"
