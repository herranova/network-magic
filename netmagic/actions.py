"""Güvenlik eylemleri, onarım araçları, hız testi ve dosya paylaşımı."""
from __future__ import annotations

import base64
import ctypes
import io
import os
import re
import secrets
import shutil
import socket
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import qrcode
import qrcode.image.svg

from . import config, db, netinfo


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _rule_name(mac: str) -> str:
    clean = re.sub(r"[^0-9A-Za-z]", "", mac or "")[:24] or "device"
    return f"NetMagic-Block-{clean}"


# --------------------------------------------------------------------------- #
# Windows Güvenlik Duvarı ile cihaz engelleme
# --------------------------------------------------------------------------- #
def firewall_set_block(mac: str, ip: str, block: bool) -> dict[str, Any]:
    if not is_admin():
        return {"ok": False, "message": "Bu işlem yönetici hakları gerektirir. Network Magic'i yönetici olarak çalıştırın."}
    try:
        socket.inet_aton(ip)
    except OSError:
        return {"ok": False, "message": "Geçersiz IP adresi."}
    name = _rule_name(mac)
    outputs: list[str] = []
    code, out = netinfo.run_command(
        ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={name}"], timeout=15
    )
    if block:
        for direction in ("out", "in"):
            code, out = netinfo.run_command(
                [
                    "netsh",
                    "advfirewall",
                    "firewall",
                    "add",
                    "rule",
                    f"name={name}",
                    f"dir={direction}",
                    "action=block",
                    f"remoteip={ip}",
                    "enable=yes",
                    "profile=any",
                ],
                timeout=15,
            )
            outputs.append(out.strip())
            if code != 0:
                return {"ok": False, "message": f"Güvenlik duvarı kuralı eklenemedi: {out.strip()[:300]}"}
        return {"ok": True, "message": f"{ip} için yerel erişim engellendi."}
    return {"ok": True, "message": "Cihazın yerel erişim engeli kaldırıldı."}


def firewall_rule_exists(mac: str) -> bool:
    if not is_admin():
        return False
    code, out = netinfo.run_command(
        ["netsh", "advfirewall", "firewall", "show", "rule", f"name={_rule_name(mac)}"], timeout=10
    )
    return code == 0 and "NetMagic-Block" in out


def firewall_cleanup_all() -> None:
    """Network Magic tarafından eklenmiş tüm kuralları siler."""
    if not is_admin():
        return
    netinfo.run_powershell(
        "Get-NetFirewallRule -DisplayName 'NetMagic-Block-*' -ErrorAction SilentlyContinue "
        "| Remove-NetFirewallRule -ErrorAction SilentlyContinue",
        timeout=30,
    )


# --------------------------------------------------------------------------- #
# Bağlantı onarımı
# --------------------------------------------------------------------------- #
def repair(action: str, iface_name: str = "") -> dict[str, Any]:
    if action == "flush_dns":
        code, out = netinfo.run_command(["ipconfig", "/flushdns"], timeout=25)
        ok = code == 0
        label = "DNS önbelleği temizlendi."
    elif action == "renew_ip":
        _, out1 = netinfo.run_command(["ipconfig", "/release"], timeout=40)
        code, out2 = netinfo.run_command(["ipconfig", "/renew"], timeout=90)
        out = out1 + "\n" + out2
        ok = code == 0
        label = "IP adresi yenilendi."
    elif action == "restart_adapter":
        if not iface_name:
            return {"ok": False, "message": "Ağ bağdaştırıcısı bulunamadı."}
        if not is_admin():
            return {"ok": False, "message": "Bağdaştırıcıyı yeniden başlatmak yönetici hakları gerektirir."}
        code, out = netinfo.run_powershell(
            "Restart-NetAdapter -Name $env:NETMAGIC_IFACE -Confirm:$false",
            timeout=60,
            env={"NETMAGIC_IFACE": iface_name},
        )
        ok = code == 0
        label = "Ağ bağdaştırıcısı yeniden başlatıldı."
    elif action == "reset_winsock":
        if not is_admin():
            return {"ok": False, "message": "Bu işlem yönetici hakları gerektirir."}
        code, out = netinfo.run_command(["netsh", "winsock", "reset"], timeout=30)
        ok = code == 0
        label = "Winsock kataloğu sıfırlandı. Etkili olması için bilgisayarı yeniden başlatın."
    elif action == "reset_tcpip":
        if not is_admin():
            return {"ok": False, "message": "Bu işlem yönetici hakları gerektirir."}
        code, out = netinfo.run_command(["netsh", "int", "ip", "reset"], timeout=40)
        ok = code == 0
        label = "TCP/IP yığını sıfırlandı. Etkili olması için bilgisayarı yeniden başlatın."
    else:
        return {"ok": False, "message": "Bilinmeyen işlem."}
    return {
        "ok": ok,
        "message": label if ok else "İşlem tamamlanamadı.",
        "output": (out or "").strip()[-3000:],
    }


def network_latency(samples: int = 5) -> dict[str, Any]:
    times: list[float] = []
    for _ in range(samples):
        start = time.perf_counter()
        try:
            with socket.create_connection(("1.1.1.1", 443), timeout=2.0):
                times.append((time.perf_counter() - start) * 1000)
        except OSError:
            pass
        time.sleep(0.05)
    if not times:
        return {"ping_ms": None, "jitter_ms": None}
    avg = sum(times) / len(times)
    jitter = (sum(abs(t - avg) for t in times) / len(times)) if len(times) > 1 else 0
    return {"ping_ms": round(avg, 1), "jitter_ms": round(jitter, 1)}


def ping_device(ip: str, count: int = 3) -> dict[str, Any]:
    """Belirli bir IP adresine ICMP ping atıp gecikme ve paket kaybını döndürür."""
    try:
        socket.inet_aton(ip)
    except OSError:
        return {"ok": False, "message": "Geçersiz IP adresi.", "avg_ms": None, "loss_pct": 100}
    code, out = netinfo.run_command(["ping", "-n", str(count), "-w", "1000", ip], timeout=10)
    avg_match = re.search(r"(?:Average|Ortalama)\s*=\s*(\d+)\s*ms", out, re.IGNORECASE)
    loss_match = re.search(r"\((\d+)%\s*(?:loss|kay[ıi]p)\)", out, re.IGNORECASE)
    avg_ms = int(avg_match.group(1)) if avg_match else None
    loss = int(loss_match.group(1)) if loss_match else (0 if code == 0 else 100)
    ok = code == 0 or (loss < 100)
    msg = f"Yanıt süresi: {avg_ms} ms (Kayıp: %{loss})" if ok and avg_ms is not None else ("Cihaz yanıt vermedi." if loss == 100 else f"Kayıp: %{loss}")
    return {
        "ok": ok,
        "ip": ip,
        "avg_ms": avg_ms,
        "loss_pct": loss,
        "message": msg,
        "output": out.strip()[-1000:],
    }


def _download_test(url: str, max_bytes: int = 24_000_000, max_seconds: float = 14.0) -> float:
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 NetMagic-Speedtest/1.0", "Cache-Control": "no-cache"}
    )
    start = time.perf_counter()
    total = 0
    with urllib.request.urlopen(req, timeout=20) as resp:
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if total >= max_bytes or time.perf_counter() - start >= max_seconds:
                break
    elapsed = max(0.05, time.perf_counter() - start)
    return (total * 8) / elapsed / 1_000_000


def _upload_test(url: str, size: int = 8_000_000, max_seconds: float = 15.0) -> float:
    payload = os.urandom(512 * 1024) * (size // (512 * 1024))
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "User-Agent": "Mozilla/5.0 NetMagic-Speedtest/1.0",
            "Content-Type": "application/octet-stream",
        },
    )
    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=25) as resp:
        resp.read()
    elapsed = max(0.05, time.perf_counter() - start)
    return (len(payload) * 8) / elapsed / 1_000_000


def public_ip() -> str:
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                value = resp.read(64).decode("utf-8", "replace").strip()
            if value and len(value) < 64:
                return value
        except Exception:
            continue
    return ""


def speedtest() -> dict[str, Any]:
    result: dict[str, Any] = {
        "tested_at": db.iso(),
        "ping_ms": None,
        "jitter_ms": None,
        "download_mbps": None,
        "upload_mbps": None,
        "public_ip": "",
        "errors": [],
    }
    latency = network_latency()
    result.update(latency)
    try:
        result["download_mbps"] = round(
            _download_test("https://speed.cloudflare.com/__down?bytes=25000000"), 1
        )
    except Exception as exc:
        result["errors"].append(f"İndirme testi: {exc}")
        try:
            result["download_mbps"] = round(
                _download_test("https://proof.ovh.net/files/10Mb.dat", 12_000_000, 12), 1
            )
        except Exception as exc2:
            result["errors"].append(f"Alternatif indirme testi: {exc2}")
    try:
        result["upload_mbps"] = round(_upload_test("https://speed.cloudflare.com/__up"), 1)
    except Exception as exc:
        result["errors"].append(f"Yükleme testi: {exc}")
    result["public_ip"] = public_ip()
    return result


# --------------------------------------------------------------------------- #
# Dosya paylaşımı
# --------------------------------------------------------------------------- #
INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_filename(name: str) -> str:
    name = Path(name or "dosya").name
    name = INVALID_CHARS.sub("_", name).strip(" .")
    if not name:
        name = "dosya"
    if len(name) > 120:
        stem, dot, ext = name.rpartition(".")
        name = (stem[:110] + dot + ext) if dot else name[:120]
    return name


def shared_files() -> list[dict[str, Any]]:
    config.SHARE_DIR.mkdir(parents=True, exist_ok=True)
    files = []
    for path in sorted(config.SHARE_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not path.is_file() or path.name.startswith("."):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        files.append(
            {
                "name": path.name,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds"),
            }
        )
    return files


def save_upload(filename: str, stream) -> dict[str, Any]:
    config.SHARE_DIR.mkdir(parents=True, exist_ok=True)
    name = safe_filename(filename)
    target = config.SHARE_DIR / name
    counter = 1
    while target.exists():
        stem = Path(name).stem
        suffix = Path(name).suffix
        target = config.SHARE_DIR / f"{stem} ({counter}){suffix}"
        counter += 1
    with open(target, "wb") as fh:
        shutil.copyfileobj(stream, fh)
    stat = target.stat()
    return {"name": target.name, "size": stat.st_size}


def delete_shared_file(name: str) -> bool:
    path = (config.SHARE_DIR / safe_filename(name)).resolve()
    if config.SHARE_DIR.resolve() not in path.parents:
        return False
    if path.is_file():
        path.unlink()
        return True
    return False


def share_usage() -> dict[str, int]:
    config.SHARE_DIR.mkdir(parents=True, exist_ok=True)
    total = 0
    count = 0
    for path in config.SHARE_DIR.iterdir():
        if path.is_file() and not path.name.startswith("."):
            count += 1
            try:
                total += path.stat().st_size
            except OSError:
                pass
    usage = shutil.disk_usage(config.SHARE_DIR)
    return {"files": count, "bytes": total, "disk_free": usage.free, "disk_total": usage.total}


def qr_data_uri(text: str) -> str:
    try:
        factory = qrcode.image.svg.SvgPathImage
        img = qrcode.make(text, image_factory=factory, box_size=10, border=2)
        buffer = io.BytesIO()
        img.save(buffer)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/svg+xml;base64,{encoded}"
    except Exception:
        return ""


# --------------------------------------------------------------------------- #
# Misafir erişimi
# --------------------------------------------------------------------------- #
def get_guest_state() -> dict[str, Any]:
    settings = db.get_settings()
    enabled = settings.get("guest_enabled") == "1"
    expires = settings.get("guest_expires", "")
    if enabled and expires:
        try:
            if datetime.fromisoformat(expires) < datetime.now(timezone.utc):
                enabled = False
                db.set_settings({"guest_enabled": "0"})
        except ValueError:
            pass
    return {
        "enabled": enabled,
        "token": settings.get("guest_token", ""),
        "expires": expires if enabled else "",
    }


def set_guest_access(enabled: bool, hours: int = 24) -> dict[str, Any]:
    if enabled:
        token = secrets.token_urlsafe(16)
        expires = (datetime.now(timezone.utc) + timedelta(hours=max(1, hours))).isoformat(timespec="seconds")
        db.set_settings({"guest_enabled": "1", "guest_token": token, "guest_expires": expires})
        db.add_alert("system", "info", "Misafir erişimi açıldı", f"{hours} saat geçerli bir misafir bağlantısı oluşturuldu.")
        return {"enabled": True, "token": token, "expires": expires}
    db.set_settings({"guest_enabled": "0", "guest_expires": ""})
    return {"enabled": False, "token": "", "expires": ""}


def guest_valid(token: str) -> bool:
    state = get_guest_state()
    return bool(state["enabled"]) and secrets.compare_digest(str(state["token"]), str(token or ""))


# --------------------------------------------------------------------------- #
# Wake-on-LAN (Magic Packet)
# --------------------------------------------------------------------------- #
def wake_on_lan(mac: str, broadcast: str = "255.255.255.255", port: int = 9) -> dict[str, Any]:
    """Ağ kartına Wake-on-LAN (Magic Packet) göndererek cihazı uzaktan uyandırır."""
    clean = re.sub(r"[^0-9A-Fa-f]", "", mac or "").strip()
    if len(clean) != 12:
        return {"ok": False, "message": f"Geçersiz MAC adresi: '{mac}'"}
    try:
        mac_bytes = bytes.fromhex(clean)
    except ValueError as e:
        return {"ok": False, "message": f"MAC adresi çözümlenemedi: {e}"}

    packet = b"\xff" * 6 + mac_bytes * 16

    destinations = [(broadcast, port), ("255.255.255.255", 9), ("255.255.255.255", 7)]
    net = netinfo.local_network()
    gw = net.get("gateway", "")
    if gw and gw.count(".") == 3:
        prefix_parts = gw.split(".")[:3]
        destinations.append((".".join(prefix_parts) + ".255", port))

    sent_count = 0
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for ip_addr, p in set(destinations):
            try:
                s.sendto(packet, (ip_addr, p))
                sent_count += 1
            except OSError:
                pass

    return {
        "ok": True,
        "message": f"{mac} adresine Wake-on-LAN sinyali (Magic Packet) başarıyla gönderildi ({sent_count} hedefe iletildi).",
    }


# --------------------------------------------------------------------------- #
# Masaüstü Bildirimi (Windows Toast / Balloon)
# --------------------------------------------------------------------------- #
def send_desktop_notification(title: str, message: str) -> bool:
    """Windows masaüstünde bildirim balonu / toast gösterir (arka planda asenkron çalışır)."""
    if os.name != "nt":
        return False

    # Başlık ve mesaj ağdaki cihazların bildirdiği adları içerebilir (mDNS, UPnP…). Betiğe
    # gömülmez, ortam değişkeniyle verilir: PowerShell "akıllı tırnak" (’) karakterlerini de
    # tırnak saydığı için metni betiğe yazmak komut enjeksiyonuna açık olurdu.
    ps_script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "Add-Type -AssemblyName System.Drawing; "
        "$n = New-Object System.Windows.Forms.NotifyIcon; "
        "$n.Icon = [System.Drawing.SystemIcons]::Shield; "
        "$n.BalloonTipTitle = $env:NETMAGIC_TOAST_TITLE; "
        "$n.BalloonTipText = $env:NETMAGIC_TOAST_TEXT; "
        "$n.Visible = $true; "
        "$n.ShowBalloonTip(5000); "
        "Start-Sleep -Milliseconds 1200; "
        "$n.Dispose()"
    )
    env = {
        "NETMAGIC_TOAST_TITLE": _notification_text(title, 60) or config.APP_NAME,
        "NETMAGIC_TOAST_TEXT": _notification_text(message, 240) or " ",
    }
    threading.Thread(
        target=netinfo.run_powershell, args=(ps_script,), kwargs={"timeout": 10, "env": env}, daemon=True
    ).start()
    return True


def _notification_text(value: str, limit: int) -> str:
    """Kontrol karakterlerini (ortam değişkeninde geçersiz olan NUL dahil) ayıklar."""
    return "".join(ch for ch in str(value or "") if ch.isprintable()).strip()[:limit]
