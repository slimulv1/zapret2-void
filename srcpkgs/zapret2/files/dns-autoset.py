#!/usr/bin/env python3
# Auto-select the fastest healthy encrypted DNS for dnscrypt-proxy.
# Inspired by hashcott/ghostline: parallel scan, reject poisoned answers,
# keep the best server, switch only after a sustained improvement.
# NetworkManager DNS stays 127.0.0.1, so switching does not cut the network.
import base64
import fcntl
import ipaddress
import json
import os
import random
import re
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request

CANDIDATES = os.environ.get("ZAPRET_DNS_CANDIDATES", "/etc/zapret2/dns-candidates")
DNSCRYPT_CONF = "/etc/dnscrypt-proxy.toml"
STATE = "/var/lib/zapret2/dns-autoset/state.json"
LOCK = "/run/lock/zapret2-dns-autoset.lock"
LOG = "/var/log/zapret2-dns-autoset.log"
TEST_DOMAIN = "example.com"
TIMEOUT = 2.5
ROUNDS = 2
MIN_IMPROVE_MS = 20
CONFIRM = 2
CHARS = "abcdefghijklmnopqrstuvwxyz0123456789"


def log(msg):
    line = "[dns-autoset] %s %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S"), msg)
    try:
        with open(LOG, "a") as f:
            f.write(line)
    except OSError:
        pass
    sys.stdout.write(line)


def rnd_label(n=8):
    return "".join(random.choice(CHARS) for _ in range(n))


def dns_query(name):
    qname = b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\x00"
    return struct.pack("!HHHHHH", random.randint(0, 65535), 0x0100, 1, 0, 0, 0) + qname + struct.pack("!HH", 1, 1)


def parse_dns(data):
    if len(data) < 12:
        return None
    rcode = data[3] & 0x0F
    ancount = struct.unpack("!H", data[6:8])[0]
    i = 12
    while i < len(data) and data[i] != 0:
        i += data[i] + 1
    i += 5
    ips = []
    for _ in range(ancount):
        if i >= len(data):
            break
        if data[i] & 0xC0 == 0xC0:
            i += 2
        else:
            while i < len(data) and data[i] != 0:
                i += data[i] + 1
            i += 1
        if i + 10 > len(data):
            break
        typ, cls, _ttl, rdlen = struct.unpack("!HHIH", data[i:i + 10])
        i += 10
        raw = data[i:i + rdlen]
        i += rdlen
        if typ == 1 and cls == 1 and rdlen == 4:
            ips.append(socket.inet_ntoa(raw))
    return rcode, ips


def public_ip(ip):
    try:
        return ipaddress.ip_address(ip).is_global
    except ValueError:
        return False


def probe(url):
    latencies = []
    # Lượt 0: kiểm tra thật + chống poison. Các lượt sau: random label để đo latency
    # (NOERROR/NODATA hoặc NXDOMAIN đều hợp lệ, như ghostline scanner).
    for i in range(ROUNDS + 1):
        name = TEST_DOMAIN if i == 0 else rnd_label() + "." + TEST_DOMAIN
        q = dns_query(name)
        b64 = base64.urlsafe_b64encode(q).rstrip(b"=").decode()
        target = url + ("&" if "?" in url else "?") + "dns=" + b64
        req = urllib.request.Request(target, headers={
            "Accept": "application/dns-message",
            "User-Agent": "zapret2-dns-autoset/1.0",
        })
        started = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                body = resp.read()
        except Exception as exc:
            return None, "error: %s" % exc
        dt = (time.monotonic() - started) * 1000
        parsed = parse_dns(body)
        if parsed is None:
            return None, "bad dns response"
        rcode, ips = parsed
        if rcode not in (0, 3):
            return None, "rcode:%d" % rcode
        if i == 0:
            if rcode != 0 or not ips:
                return None, "empty/nxdomain on validity query"
            if any(not public_ip(ip) for ip in ips):
                return None, "poisoned"
        else:
            latencies.append(dt)
    return round(min(latencies)), ""


def load_candidates():
    out = []
    with open(CANDIDATES) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "|" not in line:
                continue
            name, url = line.split("|", 1)
            out.append((name.strip(), url.strip()))
    return out


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    fd, path = tempfile.mkstemp(dir=os.path.dirname(STATE))
    with os.fdopen(fd, "w") as f:
        json.dump(state, f)
    os.replace(path, STATE)


def local_dns_ok():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.sendto(dns_query(TEST_DOMAIN), ("127.0.0.1", 53))
        data, _ = s.recvfrom(4096)
        s.close()
        parsed = parse_dns(data)
        return bool(parsed and parsed[0] in (0, 3))
    except Exception:
        return False


def apply_server(name):
    with open(DNSCRYPT_CONF) as f:
        original = f.read()
    backup = "%s.bak.%s" % (DNSCRYPT_CONF, time.strftime("%Y%m%d%H%M%S"))
    with open(backup, "w") as f:
        f.write(original)
    updated, n = re.subn(r"(?m)^server_names\s*=.*$", "server_names = ['%s']" % name, original)
    if n != 1:
        log("Không tìm thấy dòng server_names trong %s" % DNSCRYPT_CONF)
        return False
    with open(DNSCRYPT_CONF, "w") as f:
        f.write(updated)
    subprocess.run(["sv", "restart", "dnscrypt-proxy"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(20):
        if local_dns_ok():
            log("Đổi DNS chính -> %s OK" % name)
            return True
        time.sleep(0.5)
    with open(DNSCRYPT_CONF, "w") as f:
        f.write(original)
    subprocess.run(["sv", "restart", "dnscrypt-proxy"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log("Đổi sang %s thất bại; đã khôi phục cấu hình cũ" % name)
    return False


def main():
    dry = "--dry-run" in sys.argv
    if not dry:
        fd = os.open(LOCK, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return 0
    results = []
    for name, url in load_candidates():
        lat, reason = probe(url)
        results.append({"name": name, "latency": lat, "ok": lat is not None, "reason": reason})
        log("%-28s %s%s" % (name, ("%d ms" % lat) if lat is not None else "FAIL", (" " + reason) if reason else ""))
    results.sort(key=lambda r: (not r["ok"], r["latency"] if r["latency"] is not None else 1 << 30))
    ok = [r for r in results if r["ok"]]
    if dry:
        print(json.dumps(results, indent=2))
        return 0
    if not ok:
        log("Không có resolver nào đạt; giữ nguyên cấu hình")
        return 0
    best = ok[0]
    state = load_state()
    current = state.get("current", "")
    cur = next((r for r in ok if r["name"] == current), None)
    cur_lat = cur["latency"] if cur else 1 << 30
    if best["name"] == current:
        save_state({"current": current, "latency": best["latency"], "streak": 0, "last_scan": time.time()})
        log("Giữ %s (%d ms)" % (current, best["latency"]))
        return 0
    if best["latency"] + MIN_IMPROVE_MS >= cur_lat:
        save_state({"current": current, "latency": cur_lat, "streak": 0, "last_scan": time.time()})
        log("Chưa đủ ngưỡng cải thiện %d ms; giữ %s" % (MIN_IMPROVE_MS, current))
        return 0
    # Không yêu cầu CÙNG một tên ở 2 lần: hai resolver nhanh có thể đổi vị trí
    # qua lại. Chỉ cần liên tiếp CONFIRM lần đều có ứng viên vượt ngưỡng.
    streak = state.get("streak", 0) + 1
    if streak < CONFIRM:
        save_state({"current": current, "latency": cur_lat, "streak": streak,
                    "best_candidate": best["name"], "last_scan": time.time()})
        log("Có ứng viên tốt hơn: %s (%d ms), lần %d/%d" % (best["name"], best["latency"], streak, CONFIRM))
        return 0
    if apply_server(best["name"]):
        save_state({"current": best["name"], "latency": best["latency"], "streak": 0, "last_scan": time.time()})
    else:
        save_state({"current": current, "latency": cur_lat, "streak": 0, "last_scan": time.time()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
