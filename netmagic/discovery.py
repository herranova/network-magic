"""Ağ keşfi: ping taraması, ARP, mDNS, SSDP/UPnP ve port taraması."""
from __future__ import annotations

import ipaddress
import re
import socket
import struct
import subprocess
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from . import config, netinfo
from .netinfo import CREATE_NO_WINDOW, normalize_mac

ProgressCB = Callable[[int, str], None]

_OUI: dict[str, tuple[int, str]] | None = None
_OUI_LOCK = threading.Lock()

MANUF_SPECIAL = {
    "apple": "Apple",
    "samsung": "Samsung",
    "cisco": "Cisco",
    "tp-link": "TP-Link",
    "tplink": "TP-Link",
    "hewlett packard": "HP",
    "hp inc": "HP",
    "intel": "Intel",
    "xiaomi": "Xiaomi",
    "huawei": "Huawei",
    "sony": "Sony",
    "lg electronics": "LG",
    "espressif": "Espressif",
    "tuya": "Tuya",
    "sonos": "Sonos",
    "synology": "Synology",
    "qnap": "QNAP",
    "netgear": "Netgear",
    "d-link": "D-Link",
    "ubiquiti": "Ubiquiti",
    "mikrotik": "MikroTik",
    "roku": "Roku",
    "google": "Google",
    "amazon": "Amazon",
    "microsoft": "Microsoft",
    "nintendo": "Nintendo",
    "canon": "Canon",
    "epson": "Epson",
    "brother": "Brother",
    "xerox": "Xerox",
    "hikvision": "Hikvision",
    "dahua": "Dahua",
    "raspberry": "Raspberry Pi",
}


def _clean_vendor(name: str) -> str:
    name = name.strip().strip('"').replace("\\", "")
    if not name:
        return ""
    low = name.lower()
    for needle, clean in MANUF_SPECIAL.items():
        if low.startswith(needle):
            return clean
    name = re.sub(r"\s*,?\s*(Inc\.?|Ltd\.?|LLC|Corp\.?|Co\.?|GmbH|B\.V\.|S\.A\.)$", "", name, flags=re.I)
    name = re.sub(r"\s{2,}", " ", name).strip(" ,")
    return name[:48]


def _load_oui() -> dict[str, tuple[int, str]]:
    global _OUI
    if _OUI is not None:
        return _OUI
    with _OUI_LOCK:
        if _OUI is not None:
            return _OUI
        table: dict[str, tuple[int, str]] = {}
        path = next((p for p in config.OUI_FILES if Path(p).exists()), None)
        if path:
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if path.suffix == ".csv":
                            parts = line.split(",")
                            if len(parts) < 3 or parts[0] == "Registry":
                                continue
                            prefix = re.sub(r"[^0-9A-Fa-f]", "", parts[1]).upper()
                            vendor = parts[2]
                        else:
                            parts = line.split("\t")
                            if len(parts) < 2:
                                continue
                            raw_prefix = parts[0].split("/")[0]
                            prefix = re.sub(r"[^0-9A-Fa-f]", "", raw_prefix).upper()
                            vendor = parts[2] if len(parts) > 2 and parts[2].strip() else parts[1]
                        if len(prefix) < 6:
                            continue
                        cleaned = _clean_vendor(vendor)
                        if cleaned:
                            table[prefix] = (len(prefix), cleaned)
            except OSError:
                table = {}
        if not table:
            table = {
                k.upper(): (6, _clean_vendor(v)) for k, v in config.FALLBACK_OUI.items() if len(k) == 6
            }
        _OUI = table
        return table


def vendor_for_mac(mac: str) -> str:
    hexchars = re.sub(r"[^0-9A-Fa-f]", "", mac or "").upper()
    if len(hexchars) != 12:
        return ""
    # Yerel olarak yönetilen (rastgele) MAC adresleri
    try:
        if int(hexchars[1], 16) & 0x2:
            return ""
    except ValueError:
        return ""
    table = _load_oui()
    for length in (9, 7, 6):
        entry = table.get(hexchars[:length])
        if entry:
            return entry[1]
    return ""


def _is_random_mac(mac: str) -> bool:
    hexchars = re.sub(r"[^0-9A-Fa-f]", "", mac or "").upper()
    if len(hexchars) != 12:
        return False
    try:
        return bool(int(hexchars[1], 16) & 0x2)
    except ValueError:
        return False


# --------------------------------------------------------------------------- #
# Temel ağ işlemleri
# --------------------------------------------------------------------------- #
def hosts_in_subnet(ip: str, prefix: int, limit: int = 512) -> list[str]:
    if not ip or ip.startswith(("127.", "169.254.", "0.")):
        return []
    try:
        addr = ipaddress.IPv4Address(ip)
        if addr.is_loopback or addr.is_link_local or addr.is_unspecified:
            return []
        net = ipaddress.IPv4Network(f"{ip}/{prefix}", strict=False)
        if net.is_loopback or net.is_link_local:
            return []
    except ValueError:
        return []
    if net.num_addresses > limit + 2:
        # Çok büyük ağlarda yerel /24 ile sınırla
        net = ipaddress.IPv4Network(f"{ip}/24", strict=False)
    return [str(h) for h in net.hosts()]


def parse_subnet_override(value: str) -> list[str]:
    value = (value or "").strip()
    if not value:
        return []
    try:
        net = ipaddress.IPv4Network(value, strict=False)
        if net.is_loopback or net.is_link_local:
            return []
    except ValueError:
        return []
    if net.num_addresses > 1026:
        return []
    return [str(h) for h in net.hosts()]


def ping_host(ip: str, timeout_ms: int = 350) -> bool:
    try:
        proc = subprocess.run(
            ["ping", "-n", "1", "-w", str(timeout_ms), "-4", ip],
            capture_output=True,
            timeout=max(1.0, timeout_ms / 1000 + 1.0),
            creationflags=CREATE_NO_WINDOW,
        )
        return proc.returncode == 0 and b"TTL=" in proc.stdout.upper()
    except (subprocess.TimeoutExpired, OSError):
        return False


_RTT_RE = re.compile(rb"[=<]\s*(\d+)\s*ms\s+TTL", re.IGNORECASE)


def parse_ping_rtt(output: bytes) -> float | None:
    """Windows ping çıktısından gecikmeyi okur ("time=12ms TTL", "süre<1ms TTL")."""
    match = _RTT_RE.search(output or b"")
    if not match:
        return None
    return float(match.group(1))


def ping_rtt(ip: str, timeout_ms: int = 1000) -> float | None:
    """Tek ICMP ping; yanıt yoksa None, varsa ms cinsinden gecikme."""
    if not ip:
        return None
    try:
        proc = subprocess.run(
            ["ping", "-n", "1", "-w", str(timeout_ms), "-4", ip],
            capture_output=True,
            timeout=timeout_ms / 1000 + 1.5,
            creationflags=CREATE_NO_WINDOW,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    return parse_ping_rtt(proc.stdout)


def tcp_rtt(host: str, port: int = 443, timeout: float = 1.5) -> float | None:
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return round((time.perf_counter() - start) * 1000, 1)
    except OSError:
        return None


def ping_sweep(
    hosts: list[str],
    workers: int = 64,
    timeout_ms: int = 350,
    progress: ProgressCB | None = None,
    should_stop: Callable[[], bool] | None = None,
    base: int = 0,
    span: int = 0,
) -> set[str]:
    alive: set[str] = set()
    done = 0
    total = max(1, len(hosts))
    with ThreadPoolExecutor(max_workers=min(workers, total)) as pool:
        futures = {pool.submit(ping_host, ip, timeout_ms): ip for ip in hosts}
        for fut in as_completed(futures):
            ip = futures[fut]
            done += 1
            try:
                if fut.result():
                    alive.add(ip)
            except Exception:
                pass
            if progress and (done % max(1, total // 60) == 0 or done == total):
                progress(base + int(span * done / total), f"{done} / {total} adres tarandı")
            if should_stop and should_stop():
                break
    return alive


def arp_table() -> dict[str, str]:
    code, out = netinfo.run_command(["arp", "-a"], timeout=12)
    if code != 0:
        return {}
    table: dict[str, str] = {}
    pattern = re.compile(
        r"^\s*(\d{1,3}(?:\.\d{1,3}){3})\s+([0-9a-fA-F]{2}(?:[-:][0-9a-fA-F]{2}){5})\s+\S+",
        re.MULTILINE,
    )
    for match in pattern.finditer(out):
        ip, mac = match.group(1), normalize_mac(match.group(2))
        try:
            first = int(ip.split(".")[0])
        except ValueError:
            continue
        if first >= 224 or ip.endswith(".255") or mac in {"FF:FF:FF:FF:FF:FF", "00:00:00:00:00:00"}:
            continue
        table[ip] = mac
    return table


def resolve_hostnames(ips: list[str], timeout: float = 2.0) -> dict[str, str]:
    result: dict[str, str] = {}

    def lookup(ip: str) -> tuple[str, str]:
        try:
            host, _, _ = socket.gethostbyaddr(ip)
            return ip, host.split(".")[0]
        except (socket.herror, socket.gaierror, OSError):
            return ip, ""

    if not ips:
        return result
    with ThreadPoolExecutor(max_workers=min(24, len(ips))) as pool:
        futures = {pool.submit(lookup, ip): ip for ip in ips}
        try:
            for fut in as_completed(futures, timeout=timeout):
                ip, name = fut.result()
                if name:
                    result[ip] = name
        except Exception:
            pass
    return result


# --------------------------------------------------------------------------- #
# mDNS
# --------------------------------------------------------------------------- #
def _encode_name(name: str) -> bytes:
    out = b""
    for part in name.rstrip(".").split("."):
        if not part:
            continue
        raw = part.encode("utf-8")
        out += bytes([len(raw)]) + raw
    return out + b"\x00"


def _read_name(data: bytes, offset: int) -> tuple[str, int]:
    parts: list[str] = []
    jumped = False
    next_offset = offset
    for _ in range(80):
        if offset >= len(data):
            break
        length = data[offset]
        if length == 0:
            offset += 1
            if not jumped:
                next_offset = offset
            break
        if length & 0xC0 == 0xC0:
            if offset + 1 >= len(data):
                break
            pointer = ((length & 0x3F) << 8) | data[offset + 1]
            if not jumped:
                next_offset = offset + 2
            jumped = True
            offset = pointer
            continue
        offset += 1
        parts.append(data[offset : offset + length].decode("utf-8", "replace"))
        offset += length
    if not jumped:
        next_offset = offset
    return ".".join(parts), next_offset


def _build_mdns_query(names: list[str], qtype: int = 12, unicast: bool = True) -> bytes:
    header = struct.pack(">HHHHHH", 0, 0, len(names), 0, 0, 0)
    body = b""
    for name in names:
        body += _encode_name(name)
        body += struct.pack(">HH", qtype, 0x8001 if unicast else 1)
    return header + body


def _clean_instance(name: str) -> str:
    name = re.sub(r"\\(\d{3})", lambda m: chr(int(m.group(1))), name)
    return name.replace("\\", "").strip()


def _parse_dns(data: bytes) -> dict[str, Any]:
    """mDNS yanıtını kayıtlara ayırır."""
    result: dict[str, Any] = {"ptr": [], "srv": [], "a": {}, "txt": [], "names": {}}
    if len(data) < 12:
        return result
    try:
        _, _, qd, an, ns, ar = struct.unpack(">HHHHHH", data[:12])
    except struct.error:
        return result
    offset = 12
    for _ in range(qd):
        _, offset = _read_name(data, offset)
        offset += 4
    for _ in range(an + ns + ar):
        try:
            name, offset = _read_name(data, offset)
            if offset + 10 > len(data):
                break
            rtype, _, _, rdlen = struct.unpack(">HHIH", data[offset : offset + 10])
            offset += 10
            rstart = offset
            rdata = data[offset : offset + rdlen]
            offset += rdlen
            if rtype == 12:  # PTR
                target, _ = _read_name(data, rstart)
                result["ptr"].append((name, target))
            elif rtype == 33:  # SRV
                if len(rdata) >= 6:
                    target, _ = _read_name(data, rstart + 6)
                    result["srv"].append((name, target))
            elif rtype == 1 and rdlen == 4:  # A
                result["a"][socket.inet_ntoa(rdata)] = name
            elif rtype == 16:  # TXT
                txt_parts = []
                pos = 0
                while pos < len(rdata):
                    ln = rdata[pos]
                    pos += 1
                    txt_parts.append(rdata[pos : pos + ln].decode("utf-8", "replace"))
                    pos += ln
                result["txt"].append((name, txt_parts))
        except Exception:
            break
    return result


def mdns_discover(timeout: float = 1.8) -> dict[str, Any]:
    """Yerel ağdaki mDNS/Bonjour cihazlarını ve isimlerini bulur."""
    records: list[dict[str, Any]] = []
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(0.25)
        packet = _build_mdns_query(config.MDNS_SERVICES, qtype=12, unicast=True)
        sock.sendto(packet, ("224.0.0.251", 5353))
        end = time.time() + timeout
        while time.time() < end:
            try:
                data, _ = sock.recvfrom(9000)
            except socket.timeout:
                continue
            records.append(_parse_dns(data))
        sock.close()
    except OSError:
        pass

    a_map: dict[str, str] = {}
    srv_map: dict[str, tuple[str, str]] = {}
    instance_names: dict[str, str] = {}
    txt_map: dict[str, list[str]] = {}
    for rec in records:
        a_map.update(rec["a"])
        for instance, target in rec["srv"]:
            srv_map[instance] = (target, instance)
        for name, target in rec["ptr"]:
            if not name.lower().endswith(".in-addr.arpa"):
                instance_names[target] = name
        for name, parts in rec["txt"]:
            txt_map[name] = parts

    # SRV hedefi -> IP eşlemesi
    host_to_ip: dict[str, str] = {}
    for ip, host in a_map.items():
        host_to_ip[host] = ip
    by_ip: dict[str, dict[str, Any]] = {}
    for instance, (target, _) in srv_map.items():
        ip = host_to_ip.get(target)
        if not ip:
            continue
        entry = by_ip.setdefault(ip, {"name": "", "services": [], "model": ""})
        friendly = _clean_instance(instance.split("._")[0])
        if friendly and not entry["name"]:
            entry["name"] = friendly
        svc = instance.split("._", 1)[1] if "._" in instance else ""
        if svc:
            entry["services"].append("_" + svc.split("._")[0].lstrip("_"))
        for txt_name, parts in txt_map.items():
            if txt_name == instance:
                for part in parts:
                    if part.lower().startswith("model="):
                        entry["model"] = part.split("=", 1)[1]
    # Ters PTR isimleri
    for ip, host in a_map.items():
        entry = by_ip.setdefault(ip, {"name": "", "services": [], "model": ""})
        if not entry["name"]:
            entry["name"] = _clean_instance(host.split(".")[0])
    return by_ip


def _clean_hostname(name: str) -> str:
    name = _clean_instance(name or "").strip().rstrip(".")
    if name.lower().endswith(".local"):
        name = name[:-6]
    return name.strip()[:80]


def reverse_ptr_name(ip: str) -> str:
    return ".".join(reversed(ip.split("."))) + ".in-addr.arpa"


def ip_from_ptr_name(name: str) -> str:
    """'30.1.168.192.in-addr.arpa' -> '192.168.1.30'"""
    parts = name.lower().rstrip(".").split(".")
    if len(parts) < 6 or parts[-2:] != ["in-addr", "arpa"]:
        return ""
    octets = parts[:4]
    if not all(p.isdigit() and 0 <= int(p) <= 255 for p in octets):
        return ""
    return ".".join(reversed(octets))


def mdns_reverse_lookup(ips: list[str], timeout: float = 2.0) -> dict[str, str]:
    """mDNS ters PTR sorgusu: telefonlar/TV kutuları kendi adını söyler (ör. 'Android_B8PDKN3Q').

    Sorgu hem çok noktaya (224.0.0.251) hem de her cihaza doğrudan (unicast 5353) gönderilir.
    """
    result: dict[str, str] = {}
    if not ips:
        return result
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
        sock.settimeout(0.25)
    except OSError:
        return result
    try:
        for start in range(0, len(ips), 12):
            batch = ips[start:start + 12]
            packet = _build_mdns_query([reverse_ptr_name(ip) for ip in batch], qtype=12, unicast=True)
            try:
                sock.sendto(packet, ("224.0.0.251", 5353))
            except OSError:
                pass
        for ip in ips:
            try:
                sock.sendto(_build_mdns_query([reverse_ptr_name(ip)], qtype=12, unicast=True), (ip, 5353))
            except OSError:
                continue
        end = time.time() + timeout
        while time.time() < end and len(result) < len(ips):
            try:
                data, _ = sock.recvfrom(9000)
            except socket.timeout:
                continue
            except OSError:
                break
            for name, target in _parse_dns(data)["ptr"]:
                ip = ip_from_ptr_name(name)
                host = _clean_hostname(target)
                if ip and host:
                    result.setdefault(ip, host)
    finally:
        sock.close()
    return result


# --------------------------------------------------------------------------- #
# NetBIOS (Windows bilgisayarlar, NAS, bazı TV'ler)
# --------------------------------------------------------------------------- #
_NBSTAT_QUERY = (
    b"\x13\x37\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00"
    + b"\x20" + b"CKAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" + b"\x00"  # '*' + boşluk dolgusu, birinci seviye kodlama
    + b"\x00\x21\x00\x01"  # NBSTAT, IN
)


def parse_nbstat(data: bytes) -> str:
    """NBSTAT yanıtından makine adını (benzersiz, sonek 0x00) çıkarır."""
    try:
        if len(data) < 57:
            return ""
        _, offset = _read_name(data, 12)
        offset += 10  # type, class, ttl, rdlength
        count = data[offset]
        offset += 1
        for i in range(count):
            entry = data[offset + i * 18: offset + i * 18 + 18]
            if len(entry) < 18:
                break
            name = entry[:15].decode("ascii", "replace").strip()
            suffix, flags = entry[15], entry[16]
            if suffix == 0x00 and not (flags & 0x80) and name and name != "*":
                return name
    except (IndexError, ValueError):
        return ""
    return ""


def netbios_names(ips: list[str], timeout: float = 1.5) -> dict[str, str]:
    result: dict[str, str] = {}
    if not ips:
        return result
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.25)
    except OSError:
        return result
    try:
        for ip in ips:
            try:
                sock.sendto(_NBSTAT_QUERY, (ip, 137))
            except OSError:
                continue
        end = time.time() + timeout
        while time.time() < end and len(result) < len(ips):
            try:
                data, addr = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break  # Windows: ulaşılamayan hedef ICMP'si ConnectionResetError olarak gelebilir
            name = parse_nbstat(data)
            if name:
                result[addr[0]] = name
    finally:
        sock.close()
    return result


# --------------------------------------------------------------------------- #
# Web arayüzü başlığı (kamera, yazıcı, akıllı priz, NAS…)
# --------------------------------------------------------------------------- #
_GENERIC_TITLES = {
    "", "index", "home", "login", "log in", "sign in", "web server", "document", "untitled",
    "404 not found", "403 forbidden", "not found", "forbidden", "redirect", "redirecting",
    "loading", "loading...", "web user login", "welcome", "default page", "it works!",
    "http server test page", "error", "giriş", "oturum aç", "web management", "web ui",
}
_WEB_PORTS = [(80, "http"), (8080, "http"), (443, "https"), (8443, "https"), (81, "http"), (8008, "http")]


def clean_web_title(title: str) -> str:
    import html as _html

    title = re.sub(r"\s+", " ", _html.unescape(title or "")).strip()
    if title.lower() in _GENERIC_TITLES or len(title) < 3:
        return ""
    if re.fullmatch(r"[\d.:\s/-]+", title):  # yalnızca IP/sayı
        return ""
    return title[:60]


def _fetch_title(ip: str, port: int, scheme: str, timeout: float) -> str:
    import ssl

    url = f"{scheme}://{ip}:{port}/"
    ctx = ssl._create_unverified_context() if scheme == "https" else None
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 NetworkMagic/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read(65536)
            charset = resp.headers.get_content_charset() or "utf-8"
    except urllib.error.HTTPError as exc:  # 401 sayfaları da başlık taşıyabilir
        try:
            raw = exc.read(65536)
            charset = "utf-8"
        except Exception:
            return ""
    except Exception:
        return ""
    text = raw.decode(charset, "replace")
    match = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
    return clean_web_title(match.group(1)) if match else ""


def http_titles(targets: dict[str, list[int]], timeout: float = 1.8) -> dict[str, str]:
    """Açık web portu olan cihazların sayfa başlığını okur."""
    jobs = []
    for ip, ports in targets.items():
        for port, scheme in _WEB_PORTS:
            if port in ports:
                jobs.append((ip, port, scheme))
                break
    result: dict[str, str] = {}
    if not jobs:
        return result
    with ThreadPoolExecutor(max_workers=min(12, len(jobs))) as pool:
        futures = {pool.submit(_fetch_title, ip, port, scheme, timeout): ip for ip, port, scheme in jobs[:32]}
        for fut in as_completed(futures):
            try:
                title = fut.result()
            except Exception:
                continue
            if title:
                result[futures[fut]] = title
    return result


# --------------------------------------------------------------------------- #
# SSDP / UPnP
# --------------------------------------------------------------------------- #
def upnp_location_allowed(location: str, responder_ip: str) -> bool:
    """SSDP yanıtındaki LOCATION adresi yalnızca yanıtı gönderen cihazın kendi http(s)
    adresiyse okunur. Aksi halde ağdaki bir cihaz, taramayı yapan bilgisayara istediği
    adresi (file://, başka bir sunucu, 127.0.0.1…) açtırabilirdi."""
    try:
        parts = urlparse(location)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(responder_ip) and parts.hostname == responder_ip


def _fetch_upnp_description(location: str) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        req = urllib.request.Request(
            location, headers={"User-Agent": "NetMagic/1.0 UPnP/1.1"}
        )
        with urllib.request.urlopen(req, timeout=1.8) as resp:
            raw = resp.read(300000)
        text = raw.decode("utf-8", "replace")
        patterns = {
            "name": r"<friendlyName>(.*?)</friendlyName>",
            "manufacturer": r"<manufacturer>(.*?)</manufacturer>",
            "model": r"<modelName>(.*?)</modelName>",
            "device_type": r"<deviceType>(.*?)</deviceType>",
            "model_number": r"<modelNumber>(.*?)</modelNumber>",
        }
        for key, pattern in patterns.items():
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                result[key] = re.sub(r"\s+", " ", match.group(1)).strip()[:120]
    except Exception:
        pass
    return result


def ssdp_discover(timeout: float = 2.2) -> dict[str, dict[str, str]]:
    message = (
        "M-SEARCH * HTTP/1.1\r\n"
        "HOST: 239.255.255.250:1900\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 2\r\n"
        "ST: ssdp:all\r\n"
        "USER-AGENT: NetMagic/1.0 UPnP/1.1\r\n\r\n"
    ).encode()
    responses: dict[str, dict[str, str]] = {}
    locations: dict[str, str] = {}
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(0.3)
        sock.sendto(message, ("239.255.255.250", 1900))
        sock.sendto(message, ("239.255.255.250", 1900))
        end = time.time() + timeout
        while time.time() < end:
            try:
                data, addr = sock.recvfrom(8192)
            except socket.timeout:
                continue
            text = data.decode("utf-8", "replace")
            headers: dict[str, str] = {}
            for line in text.split("\r\n")[1:]:
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.strip().lower()] = value.strip()
            ip = addr[0]
            entry = responses.setdefault(ip, {})
            if headers.get("server"):
                entry["server"] = headers["server"][:120]
            if headers.get("st"):
                entry["st"] = headers["st"]
            if headers.get("usn"):
                entry["usn"] = headers["usn"]
            loc = headers.get("location")
            if loc and upnp_location_allowed(loc, ip):
                locations[ip] = loc
        sock.close()
    except OSError:
        pass

    def enrich(item: tuple[str, str]) -> tuple[str, dict[str, str]]:
        ip, loc = item
        return ip, _fetch_upnp_description(loc)

    if locations:
        with ThreadPoolExecutor(max_workers=12) as pool:
            futures = [pool.submit(enrich, pair) for pair in list(locations.items())[:24]]
            try:
                for fut in as_completed(futures, timeout=4):
                    try:
                        ip, info = fut.result()
                    except Exception:
                        continue
                    if info:
                        responses.setdefault(ip, {}).update(info)
            except (FuturesTimeout, TimeoutError):  # Python 3.10'da ikisi farklı sınıflar
                pass
    return responses


# --------------------------------------------------------------------------- #
# Port taraması
# --------------------------------------------------------------------------- #
def scan_ports(ips: list[str], timeout: float = 0.35, workers: int = 128) -> dict[str, list[int]]:
    result: dict[str, list[int]] = {ip: [] for ip in ips}
    tasks = [(ip, port) for ip in ips for port in config.COMMON_PORTS]

    def probe(ip: str, port: int) -> tuple[str, int, bool]:
        try:
            with socket.create_connection((ip, port), timeout=timeout):
                return ip, port, True
        except (OSError, socket.timeout):
            return ip, port, False

    if not tasks:
        return result
    with ThreadPoolExecutor(max_workers=min(workers, len(tasks))) as pool:
        futures = [pool.submit(probe, ip, port) for ip, port in tasks]
        for fut in as_completed(futures):
            try:
                ip, port, ok = fut.result()
            except Exception:
                continue
            if ok:
                result[ip].append(port)
    for ip in result:
        result[ip].sort()
    return result


# --------------------------------------------------------------------------- #
# Cihaz türü tahmini
# --------------------------------------------------------------------------- #
PHONE_WORDS = ("iphone", "android", "pixel", "galaxy", "redmi", "oneplus", "telefon", "phone")
TABLET_WORDS = ("ipad", "tablet", "tab ")
TV_WORDS = ("tv", "bravia", "aquos", "roku", "chromecast", "firetv", "fire tv", "apple tv", "shield", "television", "smart-tv", "googletv")
CONSOLE_WORDS = ("playstation", "xbox", "nintendo", "switch")
PRINTER_WORDS = ("printer", "yazıcı", "yazici", "laserjet", "deskjet", "officejet", "imageclass", "ecotank")
NAS_WORDS = ("nas", "synology", "diskstation", "qnap", "terramaster", "asustor", "plex", "server", "sunucu")
CAMERA_WORDS = ("camera", "kamera", "ipcam", "ip cam", "hikvision", "dahua", "reolink", "wyze", "imilab")
SPEAKER_WORDS = ("sonos", "homepod", "echo", "google home", "nest audio", "speaker", "hoparlör")


def guess_type(
    ip: str,
    gateway: str,
    vendor: str,
    hostname: str,
    ports: list[int],
    services: list[str],
    ssdp: dict[str, str] | None = None,
    is_self: bool = False,
) -> str:
    low_vendor = (vendor or "").lower()
    low_host = (hostname or "").lower()
    low_services = " ".join(s.lower() for s in services)
    ssdp = ssdp or {}
    ssdp_type = (ssdp.get("device_type") or "").lower()
    ssdp_name = (ssdp.get("name") or "").lower()
    ssdp_st = (ssdp.get("st") or "").lower()
    text = " ".join([low_host, ssdp_name, low_services, ssdp_st])

    if ip and ip == gateway:
        return "router"
    if is_self:
        return "laptop" if re.search(r"laptop|notebook|dizüstü", low_host) else "computer"
    if 9100 in ports or 631 in ports or 515 in ports or "printer" in ssdp_type:
        return "printer"
    if "mediarenderer" in ssdp_type and ("speaker" in text or low_vendor in {"sonos", "google", "amazon"}):
        return "speaker"
    if 8008 in ports or 8009 in ports or "googlecast" in text or "mediarenderer" in ssdp_type:
        if "tv" in text or "display" in text or low_vendor in {"sony", "lg", "samsung", "tcl", "hisense", "vizio", "roku"}:
            return "tv"
        return "speaker" if "speaker" in text else "tv"
    if 554 in ports or 8554 in ports or any(w in low_vendor for w in ("hikvision", "dahua", "reolink", "axis", "wyze", "imilab")) or any(w in low_host for w in CAMERA_WORDS):
        return "camera"
    if 62078 in ports:
        return "phone"
    if (5000 in ports or 5001 in ports or 32400 in ports) and (445 in ports or 139 in ports or 5000 in ports):
        return "nas"
    if any(w in low_vendor for w in ("synology", "qnap", "asustor", "terramaster")):
        return "nas"
    if "ipad" in low_host or "tablet" in low_host:
        return "tablet"
    if any(w in low_host for w in PHONE_WORDS):
        return "phone"
    if "macbook" in low_host or "laptop" in low_host or "notebook" in low_host:
        return "laptop"
    if any(w in low_host for w in CONSOLE_WORDS) or any(w in low_vendor for w in ("sony interactive", "nintendo")):
        return "console"
    if any(w in text for w in TV_WORDS) or any(
        w in low_vendor for w in ("vizio", "roku", "tcl", "hisense", "vestel", "arçelik", "beko")
    ):
        return "tv"
    if any(w in low_host for w in PRINTER_WORDS) or any(
        w in low_vendor for w in ("canon", "epson", "brother", "xerox", "lexmark", "kyocera", "ricoh")
    ):
        return "printer"
    if any(w in low_host for w in NAS_WORDS):
        return "nas"
    if any(w in text for w in SPEAKER_WORDS) or any(
        w in low_vendor for w in ("sonos", "bose", "harman")
    ):
        return "speaker"
    if "airplay" in low_services or "raop" in low_services or "companion-link" in low_services:
        return "phone" if "iphone" in low_host else "speaker"
    if any(w in low_vendor for w in ("espressif", "tuya", "shelly", "aqara", "broadlink", "nest labs")):
        return "iot"
    if 3389 in ports or 445 in ports or 139 in ports or 22 in ports or 548 in ports:
        return "computer"
    if 80 in ports or 443 in ports:
        if any(w in low_vendor for w in ("tp-link", "cisco", "netgear", "d-link", "zyxel", "mikrotik", "ubiquiti")):
            return "router"
        return "computer"
    if any(w in low_vendor for w in ("apple", "samsung", "xiaomi", "huawei", "oppo", "vivo", "oneplus", "motorola", "realme")):
        return "phone"
    if low_vendor == "rastgele mac" and not ports:
        # Gizlilik amaçlı rastgele MAC kullanan, hiç servis açmayan cihazlar neredeyse her zaman telefondur
        return "phone"
    return "unknown"


# --------------------------------------------------------------------------- #
# Tarama motoru
# --------------------------------------------------------------------------- #
class ScanEngine:
    def __init__(
        self,
        progress: ProgressCB | None = None,
        should_stop: Callable[[], bool] | None = None,
        deep: bool = True,
        subnet_override: str = "",
    ) -> None:
        self.progress = progress or (lambda p, m: None)
        self.should_stop = should_stop or (lambda: False)
        self.deep = deep
        self.subnet_override = subnet_override
        self.local = netinfo.local_network()

    def _emit(self, percent: int, message: str) -> None:
        try:
            self.progress(max(0, min(100, percent)), message)
        except Exception:
            pass

    def run(self) -> list[dict[str, Any]]:
        self.local = netinfo.local_network()
        local = self.local
        gateway = local.get("gateway") or ""
        my_ip = local.get("ip") or ""
        my_mac = normalize_mac(local.get("mac") or "")
        self._emit(2, "Yerel ağ bilgileri alınıyor")

        if not my_ip or my_ip.startswith(("127.", "169.254.")):
            self._emit(100, "Geçerli bir yerel ağ adresi bulunamadı.")
            return []

        hosts = parse_subnet_override(self.subnet_override) if self.subnet_override else []
        if not hosts:
            hosts = hosts_in_subnet(my_ip, int(local.get("prefix") or 24))
        if not hosts:
            hosts = [my_ip]
        self._emit(5, f"{len(hosts)} adres taranacak")

        alive = ping_sweep(
            hosts,
            workers=64,
            timeout_ms=350,
            progress=self._emit,
            should_stop=self.should_stop,
            base=5,
            span=35,
        )
        self._emit(41, "MAC adresleri okunuyor")
        arp = arp_table()

        # Alt ağdaki tüm ARP kayıtları da cihaz sayılır (ICMP kapalı olabilir)
        try:
            net = ipaddress.IPv4Network(f"{my_ip}/{local.get('prefix') or 24}", strict=False)
        except ValueError:
            net = None
        candidates: set[str] = set(alive)
        for ip in arp:
            try:
                if net and ipaddress.IPv4Address(ip) in net:
                    candidates.add(ip)
            except ValueError:
                continue
        if gateway:
            candidates.add(gateway)
        if my_ip:
            candidates.add(my_ip)
        candidates = {
            ip for ip in candidates
            if not ip.endswith(".255")
            and not ip.startswith(("127.", "169.254.", "224.", "239.", "255.", "0."))
        }
        ips = sorted(candidates, key=lambda x: tuple(int(p) for p in x.split(".")))
        self._emit(45, "Cihaz isimleri çözümleniyor")

        mDNS: dict[str, Any] = {}
        ssdp: dict[str, dict[str, str]] = {}
        hostnames: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=3) as pool:
            f_mdns = pool.submit(mdns_discover, 1.8)
            f_ssdp = pool.submit(ssdp_discover, 2.2)
            f_hosts = pool.submit(resolve_hostnames, ips, 2.0)
            try:
                mDNS = f_mdns.result(timeout=5)
            except Exception:
                mDNS = {}
            try:
                ssdp = f_ssdp.result(timeout=6)
            except Exception:
                ssdp = {}
            try:
                hostnames = f_hosts.result(timeout=5)
            except Exception:
                hostnames = {}
        self._emit(68, "Servisler ve portlar inceleniyor")

        def known_name(ip: str) -> str:
            return mDNS.get(ip, {}).get("name") or hostnames.get(ip) or ssdp.get(ip, {}).get("name") or ""

        # Adı hâlâ bilinmeyenler için ek kaynaklar: mDNS ters sorgu + NetBIOS (port taramasıyla paralel)
        unnamed = [ip for ip in ips if ip != my_ip and not known_name(ip)]
        ports_by_ip: dict[str, list[int]] = {}
        rev_names: dict[str, str] = {}
        nb_names: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=3) as pool:
            f_rev = pool.submit(mdns_reverse_lookup, unnamed, 2.0)
            f_nb = pool.submit(netbios_names, unnamed, 1.5)
            if self.deep:
                ports_by_ip = scan_ports(ips)
            try:
                rev_names = f_rev.result(timeout=6)
            except Exception:
                rev_names = {}
            try:
                nb_names = f_nb.result(timeout=6)
            except Exception:
                nb_names = {}
        self._emit(84, "Cihaz adları tamamlanıyor")

        # Hâlâ adsız ve web arayüzü olan cihazların sayfa başlığı (kamera, yazıcı, priz…)
        web_titles: dict[str, str] = {}
        still = {ip: ports_by_ip.get(ip, []) for ip in unnamed if not rev_names.get(ip) and not nb_names.get(ip)}
        if still and self.deep:
            try:
                web_titles = http_titles({ip: p for ip, p in still.items() if p})
            except Exception:
                web_titles = {}
        self._emit(92, "Cihaz kayıtları hazırlanıyor")

        devices: list[dict[str, Any]] = []
        for ip in ips:
            mac = normalize_mac(arp.get(ip, "")) if arp.get(ip) else ""
            is_self = bool(ip == my_ip and (not mac or not my_mac or mac == my_mac))
            if not mac and is_self and my_mac:
                mac = my_mac
            if not mac:
                mac = f"ip-{ip}"
            mdns_info = mDNS.get(ip, {})
            ssdp_info = ssdp.get(ip, {})
            ports = ports_by_ip.get(ip, [])
            services = list(dict.fromkeys(mdns_info.get("services", [])))
            hostname = (
                mdns_info.get("name")
                or hostnames.get(ip)
                or rev_names.get(ip)
                or nb_names.get(ip)
                or ssdp_info.get("name")
                or web_titles.get(ip)
                or ""
            )
            vendor = "" if mac.lower().startswith("ip-") else vendor_for_mac(mac)
            if not vendor and _is_random_mac(mac):
                vendor = "Rastgele MAC"
            dtype = guess_type(
                ip,
                gateway,
                vendor,
                hostname,
                ports,
                services,
                ssdp_info,
                is_self=is_self,
            )
            display = hostname or ssdp_info.get("name") or ""
            devices.append(
                {
                    "ip": ip,
                    "mac": mac,
                    "hostname": hostname[:120],
                    "vendor": vendor[:80],
                    "type": dtype,
                    "open_ports": [{"port": p, "service": config.COMMON_PORTS.get(p, "?")} for p in ports],
                    "services": {
                        "mdns": services,
                        "ssdp_name": ssdp_info.get("name", ""),
                        "ssdp_model": ssdp_info.get("model", ""),
                        "ssdp_manufacturer": ssdp_info.get("manufacturer", ""),
                        "ssdp_type": ssdp_info.get("device_type", ""),
                        "server": ssdp_info.get("server", ""),
                        "mdns_host": rev_names.get(ip, ""),
                        "netbios": nb_names.get(ip, ""),
                        "web_title": web_titles.get(ip, ""),
                    },
                    "display_name": display,
                    "is_self": is_self,
                    "online": True,
                }
            )
        self._emit(100, f"{len(devices)} cihaz bulundu")
        return devices
