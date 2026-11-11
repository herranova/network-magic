"""Yerel ağ, Wi-Fi, yazıcı ve bağdaştırıcı bilgileri."""
from __future__ import annotations

import ctypes
import ipaddress
import json
import os
import re
import socket
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

import psutil

CREATE_NO_WINDOW = 0x08000000


def _oem_encoding() -> str:
    try:
        return f"cp{ctypes.windll.kernel32.GetOEMCP()}"
    except Exception:
        return "cp1254"


def decode_oem(data: bytes) -> str:
    try:
        return data.decode(_oem_encoding(), errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def run_command(args: list[str], timeout: float = 20) -> tuple[int, str]:
    """Konsol penceresi açmadan komut çalıştırır (OEM kodlaması)."""
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
        return proc.returncode, decode_oem(proc.stdout) + decode_oem(proc.stderr)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return 1, str(exc)


def run_powershell(script: str, timeout: float = 30, env: dict[str, str] | None = None) -> tuple[int, str]:
    """PowerShell'i UTF-8 çıktıyla çalıştırır.

    Dışarıdan gelen metinler (cihaz adı, bağdaştırıcı adı…) betiğe gömülmez; `env` ile
    ortam değişkeni olarak verilir ve betikte `$env:AD` ile okunur. Böylece tırnak
    kaçırma hatalarıyla komut enjeksiyonu mümkün olmaz.
    """
    full = (
        "$ProgressPreference='SilentlyContinue';"
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
        "$OutputEncoding=[System.Text.Encoding]::UTF8;" + script
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", full],
            capture_output=True,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
            env={**os.environ, **env} if env else None,
        )
        return proc.returncode, proc.stdout.decode("utf-8", errors="replace") + proc.stderr.decode(
            "utf-8", errors="replace"
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return 1, str(exc)


def normalize_mac(mac: str) -> str:
    hexchars = re.sub(r"[^0-9A-Fa-f]", "", mac or "").upper()
    if len(hexchars) != 12:
        return (mac or "").upper()
    return ":".join(hexchars[i : i + 2] for i in range(0, 12, 2))


def mask_to_prefix(mask: str) -> int:
    try:
        return ipaddress.IPv4Network(f"0.0.0.0/{mask}").prefixlen
    except ValueError:
        return 24


_ROUTE_TTL = 30.0
_route_cache: tuple[float, dict[str, str]] | None = None


def _route_info() -> dict[str, str]:
    """Varsayılan rota bilgisi; ağ değişince (Wi-Fi/kablo geçişi) yenilensin diye kısa ömürlü önbellek."""
    global _route_cache
    now = time.monotonic()
    if _route_cache and now - _route_cache[0] < _ROUTE_TTL:
        return _route_cache[1]
    data = _route_info_uncached()
    _route_cache = (now, data)
    return data


def _route_cache_clear() -> None:
    global _route_cache
    _route_cache = None


def _route_info_uncached() -> dict[str, str]:
    """Varsayılan ağ geçidini ve yerel IP'yi route tablosundan okur."""
    gateway, local_ip = "", ""
    code, out = run_command(["route", "print", "-4"], timeout=12)
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0":
            try:
                ipaddress.IPv4Address(parts[2])
                ipaddress.IPv4Address(parts[3])
            except ValueError:
                continue
            gateway, local_ip = parts[2], parts[3]
            break
    return {"gateway": gateway, "local_ip": local_ip}


def default_gateway() -> str:
    return _route_info()["gateway"]


def _interface_ipv4() -> list[dict[str, Any]]:
    stats = psutil.net_if_stats()
    result: list[dict[str, Any]] = []
    for name, addrs in psutil.net_if_addrs().items():
        if name.lower().startswith(("loopback", "loopback pseudo")):
            continue
        st = stats.get(name)
        if st and not st.isup:
            continue
        for addr in addrs:
            if addr.family != socket.AF_INET:
                continue
            if addr.address.startswith(("127.", "169.254.")):
                continue
            mac = ""
            for link in addrs:
                if link.family == psutil.AF_LINK and link.address:
                    mac = normalize_mac(link.address)
                    break
            result.append(
                {
                    "name": name,
                    "ip": addr.address,
                    "netmask": addr.netmask or "255.255.255.0",
                    "prefix": mask_to_prefix(addr.netmask or "255.255.255.0"),
                    "mac": mac,
                }
            )
    return result


def primary_interface() -> dict[str, Any]:
    """Varsayılan rotayı taşıyan arayüzü döndürür."""
    route = _route_info()
    candidates = _interface_ipv4()
    if not candidates:
        return {
            "name": "Bilinmiyor",
            "ip": "127.0.0.1",
            "netmask": "255.255.255.0",
            "prefix": 24,
            "mac": "",
            "gateway": route.get("gateway", ""),
        }

    chosen = None
    if route.get("gateway"):
        try:
            gw_int = int(ipaddress.IPv4Address(route["gateway"]))
        except ValueError:
            gw_int = -1
        for c in candidates:
            try:
                net = ipaddress.IPv4Network(f"{c['ip']}/{c['prefix']}", strict=False)
            except ValueError:
                continue
            if ipaddress.IPv4Address(gw_int) in net:
                chosen = c
                break
        if chosen is None:
            for c in candidates:
                if c["ip"] == route.get("local_ip"):
                    chosen = c
                    break
    if chosen is None:
        wireless = [c for c in candidates if "wi-fi" in c["name"].lower() or "wlan" in c["name"].lower()]
        chosen = wireless[0] if wireless else candidates[0]

    chosen = dict(chosen)
    chosen["gateway"] = route.get("gateway", "")
    chosen["netmask"] = chosen.get("netmask") or "255.255.255.0"
    return chosen


def local_network() -> dict[str, Any]:
    iface = primary_interface()
    network = ""
    try:
        network = str(
            ipaddress.IPv4Network(f"{iface['ip']}/{iface['prefix']}", strict=False).network_address
        )
    except ValueError:
        network = ""
    iface["network"] = network
    iface["hostname"] = socket.gethostname()
    iface["fqdn"] = _fqdn()
    return iface


@lru_cache(maxsize=1)
def _fqdn() -> str:
    # getfqdn() ters DNS sorgusu yapar ve saniyeler sürebilir; her durum sorgusunda çağırma.
    try:
        return socket.getfqdn()
    except OSError:
        return socket.gethostname()


def lan_url(port: int) -> str:
    ip = primary_interface().get("ip") or "127.0.0.1"
    return f"http://{ip}:{port}"


# --------------------------------------------------------------------------- #
# Wi-Fi
# --------------------------------------------------------------------------- #
def _parse_colon_pairs(text: str) -> list[tuple[str, str]]:
    pairs = []
    for raw in text.splitlines():
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        pairs.append((key.strip(), value.strip()))
    return pairs


_wifi_status_cache: tuple[float, dict[str, Any]] | None = None
_wifi_networks_cache: tuple[float, list[dict[str, Any]]] | None = None


def invalidate_caches() -> None:
    """Ağ bilgileri değiştiğinde (ör. DHCP yenileme) önbellekleri temizler."""
    global _wifi_status_cache, _wifi_networks_cache, _printer_cache
    _route_cache_clear()
    _wifi_status_cache = None
    _wifi_networks_cache = None
    _printer_cache = None


def _wifi_status_fallback() -> dict[str, Any]:
    """netsh, konum izni olmadığında çalışmaz; profil bilgisinden yararlan."""
    script = (
        "Get-NetConnectionProfile | Select-Object Name,InterfaceAlias,NetworkCategory "
        "| ConvertTo-Json -Compress"
    )
    code, out = run_powershell(script, timeout=15)
    if code != 0 or not out.strip():
        return {"connected": False, "available": False}
    try:
        parsed = json.loads(out.strip())
    except json.JSONDecodeError:
        return {"connected": False, "available": False}
    if isinstance(parsed, dict):
        parsed = [parsed]
    profiles = [p for p in parsed if isinstance(p, dict)]
    chosen = None
    for p in profiles:
        alias = str(p.get("InterfaceAlias") or "").lower()
        if any(w in alias for w in ("wi-fi", "wifi", "wlan", "kablosuz", "wireless", "802.11")):
            chosen = p
            break
    if chosen is None:
        return {"connected": False, "available": False}
    return {
        "available": True,
        "connected": True,
        "ssid": str(chosen.get("Name") or ""),
        "state": "connected",
        "interface": str(chosen.get("InterfaceAlias") or ""),
        "category": str(chosen.get("NetworkCategory") or ""),
        "band": "",
        "source": "profil",
    }


def wifi_status() -> dict[str, Any]:
    global _wifi_status_cache
    now = time.monotonic()
    if _wifi_status_cache and now - _wifi_status_cache[0] < 8:
        return _wifi_status_cache[1]
    data = _wifi_status_uncached()
    _wifi_status_cache = (now, data)
    return data


def _wifi_status_uncached() -> dict[str, Any]:
    code, out = run_command(["netsh", "wlan", "show", "interfaces"], timeout=12)
    if code != 0 or not out.strip():
        return _wifi_status_fallback()
    pairs = _parse_colon_pairs(out)
    if not pairs:
        return _wifi_status_fallback()
    data: dict[str, Any] = {"available": True, "connected": False}
    for key, value in pairs:
        low = key.lower()
        if low == "ssid":
            data["ssid"] = value
        elif "bssid" in low:
            data["bssid"] = value
        elif low in ("band", "bant") and "ghz" in value.lower():
            data["band_raw"] = value
        elif "%" in value:
            try:
                data["signal"] = int(re.sub(r"[^0-9]", "", value.split("%")[0]))
            except ValueError:
                pass
        elif "802.11" in value:
            data["radio"] = value
        elif any(w in low for w in ("authentication", "kimlik", "doğrulama")):
            data["security"] = value
        elif any(w in low for w in ("state", "durum")):
            data["state"] = value
        elif any(w in low for w in ("channel", "kanal")):
            data["channel"] = value
    state = (data.get("state") or "").lower()
    # "disconnected" kelimesi "connected" içerir; önce olumsuz durumları ele.
    negative = any(w in state for w in ("disconnected", "kesildi", "bağlı değil", "bagli degil", "disconnecting"))
    data["connected"] = bool(
        data.get("ssid")
        and not negative
        and ("connected" in state or "bağlı" in state or "bagli" in state or not state)
    )
    radio = (data.get("radio") or "").lower()
    channel = data.get("channel") or ""
    try:
        ch = int(re.sub(r"[^0-9]", "", str(channel)))
    except ValueError:
        ch = 0
    band_raw = data.pop("band_raw", "")
    if band_raw:
        data["band"] = re.sub(r"\s+", " ", band_raw.replace(",", ".")).strip()
    elif ch > 14:
        data["band"] = "5 GHz"
    elif ch:
        data["band"] = "2.4 GHz"
    elif "ac" in radio or "802.11a" == radio.strip():
        data["band"] = "5 GHz"
    else:
        data["band"] = ""
    if not data.get("ssid"):
        fallback = _wifi_status_fallback()
        if fallback.get("connected"):
            return fallback
    return data


_wifi_networks_lock = threading.Lock()


def wifi_networks(force: bool = False) -> list[dict[str, Any]]:
    global _wifi_networks_cache
    # /api/wifi ve /api/wifi/analyzer aynı anda istenir; tarama bir kez yapılsın
    with _wifi_networks_lock:
        now = time.monotonic()
        if not force and _wifi_networks_cache and now - _wifi_networks_cache[0] < 20:
            return _wifi_networks_cache[1]
        data = _wifi_networks_uncached()
        _wifi_networks_cache = (time.monotonic(), data)
        return data


_last_wlan_scan = 0.0


def trigger_wlan_scan(wait: float = 3.5) -> bool:
    """Windows'a yeni bir Wi-Fi taraması yaptırır.

    `netsh wlan show networks` tarama BAŞLATMAZ; yalnızca Windows'un önbellekteki son
    listesini okur ve bu liste çoğu zaman yalnızca bağlı ağı içerir. WlanScan çağrısı
    ile sürücüye gerçek tarama yaptırıp sonuçların gelmesini bekleriz.
    """
    global _last_wlan_scan
    if time.monotonic() - _last_wlan_scan < 15:
        return False
    try:
        wlanapi = ctypes.windll.wlanapi
    except (AttributeError, OSError):
        return False

    class GUID(ctypes.Structure):
        _fields_ = [("d1", ctypes.c_uint32), ("d2", ctypes.c_uint16), ("d3", ctypes.c_uint16), ("d4", ctypes.c_ubyte * 8)]

    class WLAN_INTERFACE_INFO(ctypes.Structure):
        _fields_ = [("guid", GUID), ("description", ctypes.c_wchar * 256), ("state", ctypes.c_uint32)]

    handle = ctypes.c_void_p()
    negotiated = ctypes.c_uint32()
    if wlanapi.WlanOpenHandle(2, None, ctypes.byref(negotiated), ctypes.byref(handle)) != 0:
        return False
    scanned = False
    iface_list = ctypes.c_void_p()
    try:
        if wlanapi.WlanEnumInterfaces(handle, None, ctypes.byref(iface_list)) != 0 or not iface_list.value:
            return False
        count = ctypes.c_uint32.from_address(iface_list.value).value
        base = iface_list.value + 8  # dwNumberOfItems + dwIndex
        for i in range(min(count, 8)):
            info = WLAN_INTERFACE_INFO.from_address(base + i * ctypes.sizeof(WLAN_INTERFACE_INFO))
            if wlanapi.WlanScan(handle, ctypes.byref(info.guid), None, None, None) == 0:
                scanned = True
    except Exception:
        return False
    finally:
        if iface_list.value:
            wlanapi.WlanFreeMemory(iface_list)
        wlanapi.WlanCloseHandle(handle, None)
    if scanned:
        _last_wlan_scan = time.monotonic()
        time.sleep(wait)  # sürücü taramayı genelde 2-4 sn'de tamamlar
    return scanned


def _band_for(band_raw: str, channel: int) -> str:
    if band_raw:
        return re.sub(r"\s+", " ", band_raw.replace(",", ".")).strip()
    if channel > 14:
        return "5 GHz"
    if channel:
        return "2.4 GHz"
    return ""


def parse_wifi_networks(out: str) -> list[dict[str, Any]]:
    """`netsh wlan show networks mode=bssid` çıktısını ağ + BSSID (yayın noktası) listesine çevirir."""
    networks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    bss: dict[str, Any] | None = None
    for raw in out.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^SSID\s+\d+\s*:\s*(.*)$", line, re.IGNORECASE)
        if m:
            current = {"ssid": m.group(1).strip(), "auth": "", "encryption": "", "access_points": []}
            networks.append(current)
            bss = None
            continue
        if current is None or ":" not in line:
            continue
        m = re.match(r"^BSSID\s+\d+\s*:\s*(.*)$", line, re.IGNORECASE)
        if m:
            bss = {"bssid": m.group(1).strip().lower(), "signal": 0, "channel": 0, "band_raw": "", "radio": ""}
            current["access_points"].append(bss)
            continue
        key, value = line.split(":", 1)
        key, value = key.strip().lower(), value.strip()
        # Anahtarlar birebir karşılaştırılır: "Channel Utilization: 6 (2 %)" gibi
        # satırlar sinyal veya kanal sanılmasın.
        if key in ("authentication", "kimlik doğrulama", "kimlik dogrulama"):
            current["auth"] = value
        elif key in ("encryption", "şifreleme", "sifreleme"):
            current["encryption"] = value
        elif bss is None:
            continue
        elif key in ("signal", "sinyal"):
            digits = re.sub(r"[^0-9]", "", value.split("%")[0])
            bss["signal"] = int(digits) if digits else 0
        elif key in ("channel", "kanal"):
            digits = re.sub(r"[^0-9]", "", value)
            bss["channel"] = int(digits) if digits else 0
        elif key in ("band", "bant") and "ghz" in value.lower():
            bss["band_raw"] = value
        elif key in ("radio type", "radyo türü", "radyo turu"):
            bss["radio"] = value

    for net in networks:
        aps = net["access_points"]
        for ap in aps:
            ap["band"] = _band_for(ap.pop("band_raw", ""), ap["channel"])
        aps.sort(key=lambda a: a["signal"], reverse=True)
        best = aps[0] if aps else {}
        net["signal"] = best.get("signal", 0)
        net["channel"] = str(best.get("channel") or "")
        net["band"] = best.get("band", "")
        net["radio"] = best.get("radio", "")
        net["bssids"] = len(aps)
        bands = sorted({a["band"] for a in aps if a["band"]})
        net["bands"] = bands
    networks.sort(key=lambda n: n.get("signal", 0), reverse=True)
    return networks


def _wifi_networks_uncached() -> list[dict[str, Any]]:
    trigger_wlan_scan()
    code, out = run_command(["netsh", "wlan", "show", "networks", "mode=bssid"], timeout=15)
    if code != 0:
        return []
    return parse_wifi_networks(out)


# --------------------------------------------------------------------------- #
# Yazıcılar & bağdaştırıcı istatistikleri
# --------------------------------------------------------------------------- #
_printer_cache: tuple[datetime, list[dict[str, Any]]] | None = None


def printers() -> list[dict[str, Any]]:
    global _printer_cache
    now = datetime.now(timezone.utc)
    if _printer_cache and now - _printer_cache[0] < timedelta(seconds=60):
        return _printer_cache[1]
    script = (
        "Get-Printer | Select-Object Name,DriverName,PortName,Shared,ShareName,PrinterStatus "
        "| ConvertTo-Json -Compress"
    )
    code, out = run_powershell(script, timeout=25)
    result: list[dict[str, Any]] = []
    if code == 0 and out.strip():
        try:
            parsed = json.loads(out.strip())
            if isinstance(parsed, dict):
                parsed = [parsed]
            for p in parsed:
                result.append(
                    {
                        "name": p.get("Name") or "",
                        "driver": p.get("DriverName") or "",
                        "port": p.get("PortName") or "",
                        "shared": bool(p.get("Shared")),
                        "share_name": p.get("ShareName") or "",
                        "status": str(p.get("PrinterStatus") or ""),
                    }
                )
        except json.JSONDecodeError:
            pass
    _printer_cache = (now, result)
    return result


def adapter_stats(iface_name: str) -> dict[str, Any]:
    try:
        counters = psutil.net_io_counters(pernic=True)
        stats = psutil.net_if_stats().get(iface_name)
        c = counters.get(iface_name)
        if not c:
            return {"rx_total": 0, "tx_total": 0, "speed_mbps": 0, "up": False}
        return {
            "rx_total": c.bytes_recv,
            "tx_total": c.bytes_sent,
            "speed_mbps": stats.speed if stats else 0,
            "up": bool(stats.isup) if stats else False,
        }
    except Exception:
        return {"rx_total": 0, "tx_total": 0, "speed_mbps": 0, "up": False}


def all_interfaces() -> list[dict[str, Any]]:
    return _interface_ipv4()


def wifi_channel_analysis(refresh: bool = False) -> dict[str, Any]:
    """Çevredeki Wi-Fi ağlarını ve kanal yoğunluğunu analiz eder, en temiz kanalı önerir."""
    status = wifi_status()
    networks = wifi_networks(force=refresh)

    own_ssid = (status.get("ssid") or "") if status.get("connected") else ""
    own_bssid = (status.get("bssid") or "").lower()
    current_channel = 0
    try:
        current_channel = int(re.sub(r"[^0-9]", "", str(status.get("channel") or "")) or 0)
    except ValueError:
        current_channel = 0

    # Her yayın noktası (BSSID) ayrı sayılır: tek bir ağ adı birden çok modem/radyo içerebilir.
    channels_24: dict[int, int] = {ch: 0 for ch in range(1, 14)}
    channels_5: dict[int, int] = {ch: 0 for ch in CHANNELS_5}
    foreign: list[tuple[int, int]] = []  # (kanal, sinyal) — kendi ağımız hariç, öneri puanı için
    ap_total = 0
    for n in networks:
        is_own = bool(own_ssid) and n.get("ssid") == own_ssid
        for ap in n.get("access_points") or []:
            band = str(ap.get("band") or "")
            ch = int(ap.get("channel") or 0)
            if band.startswith("6") or not ch:
                continue  # 6 GHz kanal numaraları 2.4/5 GHz ile çakışır
            ap_total += 1
            if 1 <= ch <= 14 and not band.startswith("5"):
                channels_24[ch] = channels_24.get(ch, 0) + 1
            elif ch >= 32:
                channels_5[ch] = channels_5.get(ch, 0) + 1
            else:
                continue
            if not (is_own or (own_bssid and ap.get("bssid") == own_bssid)):
                foreign.append((ch, int(ap.get("signal") or 0)))

    def weight(signal: int) -> float:
        # Güçlü (yakın) ağlar zayıf olanlardan çok daha fazla parazit yapar
        return 0.25 + max(0, min(100, signal)) / 100

    def score_24(candidate: int) -> float:
        # 2.4 GHz'de kanallar 20 MHz genişliğinde: ±4 kanal içindekiler çakışır
        return sum(weight(s) for ch, s in foreign if ch <= 14 and abs(ch - candidate) <= 4)

    def score_5(block: tuple[int, ...]) -> float:
        # 5 GHz modemler genelde 80 MHz kullanır: 4 kanallık blok birlikte değerlendirilir
        return sum(weight(s) for ch, s in foreign if ch in block)

    best_24 = min((1, 6, 11), key=lambda c: (score_24(c), c))
    best_block = min(BLOCKS_5, key=lambda b: (score_5(b), b in DFS_BLOCKS, b[0]))
    best_5 = best_block[0]

    location_restricted = (not networks or all(not n.get("access_points") for n in networks))
    if not location_restricted:
        n24 = sum(1 for ch, _ in foreign if ch <= 14 and abs(ch - best_24) <= 4)
        n5 = sum(1 for ch, _ in foreign if ch in best_block)
        dfs_note = " (DFS kanalı: radar algılanırsa modem kanal değiştirebilir)" if best_block in DFS_BLOCKS else ""
        recommendation = (
            f"{len(networks)} ağ, {ap_total} yayın noktası bulundu. "
            f"2.4 GHz için en temiz: Kanal {best_24} ({n24} çakışan yayın). "
            f"5 GHz için en temiz: Kanal {best_block[0]}–{best_block[-1]} bloğu ({n5} yayın){dfs_note}."
        )
    else:
        recommendation = (
            "Çevredeki ağlar listelenemedi. Windows Ayarları > Gizlilik ve güvenlik > Konum "
            "bölümünde konum servisinin ve masaüstü uygulamalarının konum erişiminin açık olduğundan emin olun."
        )

    return {
        "status": status,
        "total_networks": len(networks),
        "total_access_points": ap_total,
        "channels_24": dict(sorted(channels_24.items())),
        "channels_5": dict(sorted(channels_5.items())),
        "best_24": best_24,
        "best_5": best_5,
        "best_5_block": list(best_block),
        "current_channel": current_channel,
        "recommendation": recommendation,
        "location_restricted": location_restricted,
    }


CHANNELS_5 = [36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140, 144, 149, 153, 157, 161, 165]
BLOCKS_5 = [(36, 40, 44, 48), (52, 56, 60, 64), (100, 104, 108, 112), (116, 120, 124, 128), (132, 136, 140, 144), (149, 153, 157, 161)]
DFS_BLOCKS = {(52, 56, 60, 64), (100, 104, 108, 112), (116, 120, 124, 128), (132, 136, 140, 144)}
