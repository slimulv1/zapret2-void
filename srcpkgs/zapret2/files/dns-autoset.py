#!/usr/bin/env python3
# DNS health auditor + set-change switcher for dnscrypt-proxy.
# Design (2026-11-27): ghostline-style ranking (parallel probes, poison rejection,
# per-network cache, 24h TTL, 90% coverage, loss/median/p90/jitter) + dnscrypt-proxy
# native wp2 load balancing. Latency-only changes do NOT restart anything; only a
# changed/lost pool or broken local DNS triggers a bounded, verified switch.
import base64
import concurrent.futures
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
DNSCRYPT_CONF = os.environ.get("ZAPRET_DNS_CONF", "/etc/dnscrypt-proxy.toml")
CONFIG = os.environ.get("ZAPRET_DNS_CONFIG", "/etc/zapret2/dns-autoset.conf")
STATE = os.environ.get("ZAPRET_DNS_STATE", "/var/lib/zapret2/dns-autoset/state.json")
LOCK = "/run/lock/zapret2-dns-autoset.lock"
LOG = os.environ.get("ZAPRET_DNS_LOG", "/var/log/zapret2-dns-autoset.log")
TEST_DOMAIN = "example.com"
POISON_DOMAINS = ("cloudflare.com", "google.com")
ROUNDS = 3
TIMEOUT = 2.0
FULL_TTL = 86400
COVERAGE = 0.9
COOLDOWN = 21600
CHARS = "abcdefghijklmnopqrstuvwxyz0123456789"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def settings():
    out = {"mode": "pool", "pool_size": 3}
    try:
        with open(CONFIG) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    out[k.strip()] = v.strip().strip("'\"")
    except OSError:
        pass
    return out


def log(msg):
    line = "[dns-autoset] %s %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S"), msg)
    try:
        with open(LOG, "a") as f:
            f.write(line)
        if os.path.getsize(LOG) > 1024 * 1024:
            os.replace(LOG, LOG + ".1")
    except OSError:
        pass
    if "--dry-run" in sys.argv or sys.stdout.isatty():
        sys.stdout.write(line)


def rnd_label(n=8):
    return "".join(random.choice(CHARS) for _ in range(n))


def dns_query(name, qid=None, edns=False):
    qname = b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\x00"
    flags = 0x0100
    arcount = 1 if edns else 0
    pkt = struct.pack("!HHHHHH", qid or random.randint(0, 65535), flags, 1, 0, 0, arcount)
    pkt += qname + struct.pack("!HH", 1, 1)
    if edns:
        pkt += b"\x00" + struct.pack("!HHIH", 41, 4096, 0x0080, 0)  # OPT, DO bit
    return pkt


def parse_dns(data, qid=None):
    if len(data) < 12:
        return None
    if qid is not None and struct.unpack("!H", data[:2])[0] != qid:
        return None
    rcode = data[3] & 0x0F
    ad = bool(data[3] & 0x20)
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
    return rcode, ad, ips


def public_ip(ip):
    try:
        return ipaddress.ip_address(ip).is_global
    except ValueError:
        return False


def probe(url):
    latencies = []
    failures = 0
    for i in range(ROUNDS + 1):
        validity = i == 0
        name = TEST_DOMAIN if validity else rnd_label() + "." + TEST_DOMAIN
        qid = random.randint(0, 65535)
        q = dns_query(name, qid, edns=validity)
        b64 = base64.urlsafe_b64encode(q).rstrip(b"=").decode()
        target = url + ("&" if "?" in url else "?") + "dns=" + b64
        req = urllib.request.Request(target, headers={
            "Accept": "application/dns-message",
            "User-Agent": "zapret2-dns-autoset/2.0",
        })
        started = time.monotonic()
        try:
            with OPENER.open(req, timeout=TIMEOUT) as resp:
                if not resp.geturl().startswith("https://"):
                    return {"ok": False, "reason": "non-https redirect"}
                body = resp.read()
        except Exception as exc:
            if not validity and failures == 0:
                failures = 1
                time.sleep(0.1)
                continue
            return {"ok": False, "reason": "error: %s" % exc}
        dt = (time.monotonic() - started) * 1000
        parsed = parse_dns(body, qid)
        if parsed is None:
            return {"ok": False, "reason": "bad dns response"}
        rcode, _ad, ips = parsed
        if rcode not in (0, 3):
            return {"ok": False, "reason": "rcode:%d" % rcode}
        if validity:
            if rcode != 0 or not ips or any(not public_ip(ip) for ip in ips):
                return {"ok": False, "reason": "poisoned/empty on validity query"}
        else:
            latencies.append(dt)
            time.sleep(0.1)
    if not latencies:
        return {"ok": False, "reason": "no latency samples"}
    latencies.sort()
    n = len(latencies)
    median = latencies[n // 2]
    p90 = latencies[min(n - 1, int(0.9 * n))] if n > 1 else median
    mean = sum(latencies) / n
    jitter = (sum((x - mean) ** 2 for x in latencies) / n) ** 0.5
    loss = failures / float(ROUNDS)
    # ghostline-style poison check: a domain that should be public returning
    # only private/reserved addresses means the upstream is rewriting answers.
    poisoned = False
    for domain in POISON_DOMAINS:
        qid = random.randint(0, 65535)
        q = dns_query(domain, qid)
        b64 = base64.urlsafe_b64encode(q).rstrip(b"=").decode()
        try:
            with OPENER.open(urllib.request.Request(
                    url + ("&" if "?" in url else "?") + "dns=" + b64,
                    headers={"Accept": "application/dns-message"}), timeout=TIMEOUT) as resp:
                parsed = parse_dns(resp.read(), qid)
        except Exception:
            continue
        if parsed and parsed[0] == 0 and parsed[2] and any(not public_ip(ip) for ip in parsed[2]):
            poisoned = True
    return {"ok": True, "median_ms": round(median), "p90_ms": round(p90),
            "jitter_ms": round(jitter), "loss": round(loss, 2), "poisoned": poisoned}


def load_candidates():
    out = {}
    with open(CANDIDATES) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "|" not in line:
                continue
            name, url = line.split("|", 1)
            out[name.strip()] = url.strip()
    return out


def load_state():
    try:
        with open(STATE) as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    fd, path = tempfile.mkstemp(dir=os.path.dirname(STATE))
    with os.fdopen(fd, "w") as f:
        json.dump(state, f)
    os.chmod(path, 0o644)
    os.replace(path, STATE)


def net_key():
    try:
        out = subprocess.check_output(["ip", "route", "get", "1.1.1.1"], text=True, timeout=3)
        dev = re.search(r"dev\s+(\S+)", out).group(1)
        gw = re.search(r"via\s+(\S+)", out)
        mac = open("/sys/class/net/%s/address" % dev).read().strip()
        return "%s|%s" % (gw.group(1) if gw else "direct", mac)
    except Exception:
        return "unknown"


def current_names():
    try:
        with open(DNSCRYPT_CONF) as f:
            text = f.read()
    except OSError:
        return None, ""
    m = re.search(r"(?m)^server_names\s*=\s*\[([^\]]*)\]", text)
    if not m:
        return None, text
    names = [a or b for a, b in re.findall(r"'([^']+)'|\"([^\"]+)\"", m.group(1))]
    return names, text


def local_dns_ok():
    qid = random.randint(0, 65535)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1)
        s.sendto(dns_query(TEST_DOMAIN, qid), ("127.0.0.1", 53))
        data, _ = s.recvfrom(4096)
        s.close()
        parsed = parse_dns(data, qid)
        return bool(parsed and parsed[0] == 0 and parsed[2])
    except Exception:
        return False


def apply_pool(names, state):
    text = current_names()[1]
    if not re.search(r"(?m)^server_names\s*=", text):
        log("Không thấy server_names trong config; không tự tạo")
        return False
    backup = DNSCRYPT_CONF + ".bak.zapret2"
    with open(backup, "w") as f:
        f.write(text)
    updated = re.sub(r"(?m)^server_names\s*=.*$",
                     "server_names = [%s]" % ", ".join("'%s'" % n for n in names), text)
    if not re.search(r"(?m)^lb_strategy\s*=", updated):
        updated = re.sub(r"(?m)^(server_names\s*=.*)$", r"\1\nlb_strategy = 'wp2'", updated, count=1)
    else:
        updated = re.sub(r"(?m)^lb_strategy\s*=.*$", "lb_strategy = 'wp2'", updated)
    with open(DNSCRYPT_CONF, "w") as f:
        f.write(updated)
    ok = False
    for _ in range(3):
        subprocess.run(["sv", "restart", "dnscrypt-proxy"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(3):
            if local_dns_ok():
                ok = True
                break
            time.sleep(1)
        if ok:
            break
    if not ok:
        with open(DNSCRYPT_CONF, "w") as f:
            f.write(text)
        subprocess.run(["sv", "restart", "dnscrypt-proxy"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log("Đổi pool thất bại; đã khôi phục config và kiểm tra lại: %s" %
            ("OK" if local_dns_ok() else "VẪN LỖI"))
        return False
    log("Đổi pool -> [%s] OK" % ", ".join(names))
    return True


def rank(results):
    def key(r):
        return (r.get("poisoned", False), not r["ok"],
                round(r.get("loss", 0) * 10), r.get("median_ms", 1 << 30), r["name"])
    return sorted(results, key=key)


def main():
    dry = "--dry-run" in sys.argv
    if not os.path.exists("/usr/bin/dnscrypt-proxy") or not os.path.exists("/var/service/dnscrypt-proxy"):
        log("dnscrypt-proxy chưa được cài (binary/service thiếu); bỏ qua")
        return 0
    if not dry:
        fd = os.open(LOCK, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            log("Một lần chạy khác đang giữ lock; bỏ qua")
            return 0

    if not local_dns_ok():
        log("DNS local 127.0.0.1:53 KHÔNG trả lời; sẽ thử phục hồi pool")
        repair = True
    else:
        repair = False

    if subprocess.run(["ip", "route", "get", "1.1.1.1"], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode != 0:
        log("Không có route mặc định; bỏ qua lần quét")
        return 0

    cfg = settings()
    try:
        pool_size = max(1, int(cfg.get("pool_size", 3)))
    except ValueError:
        pool_size = 3
    candidates = load_candidates()
    state = load_state()
    key = net_key()
    entry = state.get(key, {})
    names_now, _ = current_names()
    if names_now is None:
        log("Config không có server_names hợp lệ; bỏ qua")
        return 0
    cooldown = entry.get("cooldown", {})
    now = time.time()

    ranked_old = entry.get("results", [])
    fresh = (bool(entry.get("full_at")) and now - entry.get("full_at", 0) <= FULL_TTL and
             len(ranked_old) >= COVERAGE * len(candidates))
    if fresh and not repair:
        todo = list(dict.fromkeys(names_now + [r["name"] for r in ranked_old[:pool_size]]))
        todo = [n for n in todo if n in candidates and cooldown.get(n, 0) < now]
        log("Quick check: %d resolver" % len(todo))
    else:
        todo = [n for n in candidates if cooldown.get(n, 0) < now]
        log("Full scan: %d resolver" % len(todo))

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, max(1, len(todo)))) as ex:
        futures = {ex.submit(probe, candidates[n]): n for n in todo}
        for fut in concurrent.futures.as_completed(futures, timeout=90):
            name = futures[fut]
            try:
                r = fut.result()
            except Exception as exc:
                r = {"ok": False, "reason": str(exc)}
            r["name"] = name
            results.append(r)
            log("%-28s %s" % (name, ("%s ms loss=%s jitter=%s%s" % (
                r.get("median_ms"), r.get("loss"), r.get("jitter_ms"),
                " POISONED" if r.get("poisoned") else "")) if r["ok"] else r.get("reason", "FAIL")))

    ordered = rank(results)
    if dry:
        print(json.dumps(ordered, indent=2))
        return 0
    good = [r for r in ordered if r["ok"] and not r.get("poisoned")]
    if not good:
        log("Không có resolver đạt; giữ config hiện tại")
        return 0

    if fresh and not repair:
        merged = {r["name"]: r for r in ranked_old}
        merged.update({r["name"]: r for r in results})
        results_all = list(merged.values())
    else:
        results_all = results
        entry["full_at"] = now

    chosen = [r["name"] for r in rank([r for r in results_all if r["ok"] and not r.get("poisoned")])[:pool_size]]
    if cfg.get("mode") == "single":
        chosen = chosen[:1]

    # wp2 tự xếp lại theo RTT, nên THỨ TỰ trong server_names không quan trọng.
    # Chỉ restart khi TẬP HỢP resolver đổi (ghostline ID-set diff), không phải reorder.
    if not repair and sorted(chosen) == sorted(names_now):
        log("Giữ pool %s (không restart)" % chosen)
        entry.update({"results": results_all, "last_scan": now})
        state[key] = entry
        save_state(state)
        return 0

    if apply_pool(chosen, state):
        entry.update({"results": results_all, "last_scan": now})
        state[key] = entry
        save_state(state)
    else:
        for n in chosen:
            if n not in names_now:
                cooldown[n] = now + COOLDOWN
        entry.update({"cooldown": cooldown, "last_scan": now})
        state[key] = entry
        save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
