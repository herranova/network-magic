"""Network Magic - yerel ağ yönetim uygulaması (Flask sunucusu)."""
from __future__ import annotations

import csv
import io
import ipaddress
import os
import socket
import threading
import webbrowser
from datetime import datetime, timedelta, timezone
from functools import wraps
from urllib.parse import urlsplit

from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    send_from_directory,
)

from netmagic import actions, config, db, discovery, monitor as monitor_mod, netinfo

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024
app.json.ensure_ascii = False
app.json.sort_keys = False
app.config["TEMPLATES_AUTO_RELOAD"] = True

db.init_db()

SCAN_LOCK = threading.Lock()
SCAN_STATE: dict = {
    "running": False,
    "phase": "Hazır",
    "progress": 0,
    "started": None,
    "finished": None,
    "found": 0,
    "new": 0,
    "error": None,
    "kind": "manual",
}
SPEED_LOCK = threading.Lock()
SPEED_CACHE: dict = {}
SERVER_PORT = config.DEFAULT_PORT


# --------------------------------------------------------------------------- #
# Yardımcılar
# --------------------------------------------------------------------------- #
def _own_ips() -> set[str]:
    """Bu bilgisayarın IP'leri; LAN adresiyle açılan arayüz de yerel sayılsın."""
    ips = {"127.0.0.1", "::1"}
    try:
        route = netinfo.primary_interface()
        if route.get("ip"):
            ips.add(route["ip"])
        for iface in netinfo.all_interfaces():
            if iface.get("ip"):
                ips.add(iface["ip"])
    except Exception:
        pass
    return ips


def _is_local_request() -> bool:
    return request.remote_addr in {None, *_own_ips()}


def _host_only(value: str) -> str:
    """'192.168.1.5:8765' -> '192.168.1.5', '[::1]:8765' -> '::1'."""
    value = (value or "").strip().lower()
    if value.startswith("["):
        return value[1:].split("]", 1)[0]
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def _allowed_hostnames() -> set[str]:
    names = {"localhost"}
    try:
        hostname = socket.gethostname().lower()
        names.update({hostname, f"{hostname}.local"})
    except OSError:
        pass
    extra = os.environ.get("NETMAGIC_ALLOWED_HOSTS", "")
    names.update(h.strip().lower() for h in extra.split(",") if h.strip())
    return names


def _host_header_trusted(host_header: str) -> bool:
    """DNS rebinding koruması: yalnızca IP adresi, localhost veya bu bilgisayarın adıyla
    gelen istekler kabul edilir. Saldırgan bir alan adı (ör. evil.example -> 127.0.0.1)
    Host başlığında kendi adını taşır ve burada reddedilir."""
    host = _host_only(host_header)
    if not host:
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return host in _allowed_hostnames()


@app.before_request
def _request_guard():
    if not _host_header_trusted(request.host):
        return jsonify({"ok": False, "message": "Geçersiz Host başlığı."}), 403
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return None
    # CSRF koruması: tarayıcıda açık başka bir site, bu bilgisayardaki Network Magic'e
    # (yönetici haklarıyla çalışır) kullanıcı adına istek gönderememeli.
    origin = request.headers.get("Origin")
    if origin is not None:
        if urlsplit(origin).netloc.lower() != request.host.lower():
            return jsonify({"ok": False, "message": "Farklı kaynaktan gelen istek reddedildi."}), 403
    elif request.headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
        return jsonify({"ok": False, "message": "Farklı kaynaktan gelen istek reddedildi."}), 403
    return None


def local_only(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not _is_local_request() and db.get_setting("allow_lan_control", "0") != "1":
            return (
                jsonify(
                    {
                        "ok": False,
                        "message": "Bu işlem yalnızca Network Magic'in çalıştığı bilgisayardan yapılabilir. "
                        "Uzaktan yönetim için Ayarlar > LAN'dan yönetim seçeneğini açın.",
                    }
                ),
                403,
            )
        return view(*args, **kwargs)

    return wrapper


def _apply_self_name(force: bool = False) -> None:
    """İlk kurulumda/ayarlarda verilen bilgisayar adını 'Bu PC' cihazına uygular."""
    name = (db.get_setting("device_name", "") or "").strip()
    if not name:
        return
    for device in db.list_devices():
        if device.get("is_self") and (force or not (device.get("name") or "").strip()):
            db.update_device(device["id"], {"name": name})


def _int_or_none(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def scan_progress(percent: int, message: str) -> None:
    with SCAN_LOCK:
        SCAN_STATE["progress"] = percent
        SCAN_STATE["phase"] = message


def _run_scan(kind: str = "manual", deep: bool = True, override: str | None = None) -> None:
    scan_id = db.start_scan(kind)
    try:
        settings = db.get_settings()
        subnet = override if override is not None else settings.get("subnet_override", "")
        engine = discovery.ScanEngine(
            progress=scan_progress,
            should_stop=lambda: False,
            deep=deep,
            subnet_override=subnet,
        )
        devices = engine.run()
        baseline = settings.get("baseline_done") != "1"
        merged: list[dict] = []
        new_devices = db.upsert_scan(devices, baseline=baseline, merged=merged)
        for m in merged:
            # Eski MAC'e bağlı bir engel kuralı varsa kaldır; kural yeni MAC ile yeniden uygulanır
            if monitor.blocked_state.get(m["old_mac"]):
                actions.firewall_set_block(m["old_mac"], m["ip"], False)
            monitor.record_block(m["old_mac"], None, None)
            db.add_alert(
                "device",
                "info",
                f"{m['name']} yeni bir MAC adresiyle tanındı",
                f"Cihaz gizlilik için MAC adresini değiştirmiş ({m['old_mac']} → {m['mac']}). "
                "Aynı ada sahip olduğu için mevcut kaydıyla eşleştirildi; yeni cihaz sayılmadı.",
                m["mac"],
            )
        db.mark_offline_except({d["mac"] for d in devices})
        db.finish_scan(scan_id, len(devices), len(new_devices))

        _apply_self_name()

        if baseline:
            db.set_setting("baseline_done", "1")
            db.add_alert(
                "system",
                "info",
                "Ağ keşfi tamamlandı",
                f"{len(devices)} cihaz bulundu. Ağ haritanızı inceleyebilir, cihazları yeniden adlandırabilirsiniz.",
            )
        else:
            if db.get_setting("notify_new", "1") == "1":
                for item in new_devices:
                    name = item.get("name") or item.get("ip") or item["mac"]
                    vendor = item.get("vendor") or ""
                    extra = ""
                    if vendor == "Rastgele MAC":
                        extra = " MAC adresi rastgele (gizlilik) görünümlü."
                    elif vendor:
                        extra = f" Üretici: {vendor}."
                    db.add_alert(
                        "new_device",
                        "warning",
                        f"Yeni cihaz algılandı: {name}",
                        f"{item.get('ip')} adresinde daha önce görülmeyen bir cihaz ağa katıldı."
                        + extra,
                        item["mac"],
                    )
                    actions.send_desktop_notification(
                        "Network Magic — Yeni Cihaz Algılandı!",
                        f"{name} ({item.get('ip', '')}) ağınıza katıldı.{extra}",
                    )
        with SCAN_LOCK:
            SCAN_STATE.update(
                {
                    "running": False,
                    "phase": "Tamamlandı",
                    "progress": 100,
                    "finished": db.iso(),
                    "found": len(devices),
                    "new": len(new_devices),
                    "error": None,
                }
            )
        try:
            monitor.enforce_rules()
        except Exception:
            pass
    except Exception as exc:  # pragma: no cover - güvenlik ağı
        db.finish_scan(scan_id, 0, 0)
        db.add_alert("system", "critical", "Tarama başarısız", f"Ağ taranırken hata oluştu: {exc}")
        with SCAN_LOCK:
            SCAN_STATE.update(
                {
                    "running": False,
                    "phase": "Hata",
                    "progress": 100,
                    "finished": db.iso(),
                    "error": str(exc),
                }
            )


def start_scan(kind: str = "manual", deep: bool = True, override: str | None = None) -> bool:
    with SCAN_LOCK:
        if SCAN_STATE["running"]:
            return False
        SCAN_STATE.update(
            {
                "running": True,
                "phase": "Tarama başlatılıyor",
                "progress": 0,
                "started": db.iso(),
                "finished": None,
                "found": 0,
                "new": 0,
                "error": None,
                "kind": kind,
            }
        )
    db.set_setting("_last_scan_request", db.iso())
    threading.Thread(target=_run_scan, args=(kind, deep, override), daemon=True).start()
    return True


monitor = monitor_mod.Monitor(start_scan, lambda: SCAN_STATE["running"])


def _restricted_now(device: dict) -> bool:
    if device.get("blocked") or device.get("paused"):
        return True
    schedule = device.get("schedule")
    if schedule:
        now = datetime.now().astimezone()
        hours = schedule.get(str(now.weekday()))
        if hours is not None and now.hour not in hours:
            return True
    return False


def _device_payload(device: dict) -> dict:
    device = dict(device)
    device["restricted"] = _restricted_now(device)
    return device


def _counts() -> dict:
    devices = db.list_devices()
    return {
        "total": len(devices),
        "online": sum(1 for d in devices if d.get("online")),
        "untrusted": sum(1 for d in devices if not d.get("trusted")),
        "restricted": sum(1 for d in devices if _restricted_now(d)),
        "alerts": db.unread_alert_count(),
    }


# --------------------------------------------------------------------------- #
# Sayfalar
# --------------------------------------------------------------------------- #
@app.get("/")
def index():
    return render_template(
        "index.html",
        version=config.APP_VERSION,
        app_name=config.APP_NAME,
        tagline=config.APP_TAGLINE,
    )


@app.get("/robots.txt")
def robots_txt():
    """Yerel ağ uygulaması: arama motorlarına kapalı."""
    return Response("User-agent: *\nDisallow: /\n", mimetype="text/plain")


@app.get("/manifest.webmanifest")
def web_manifest():
    """Telefonda 'Ana ekrana ekle' ile uygulama gibi açılması için PWA bildirimi."""
    manifest = {
        "name": config.APP_NAME,
        "short_name": config.APP_NAME,
        "description": config.APP_TAGLINE,
        "id": "/",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "any",
        "background_color": "#090e1a",
        "theme_color": "#090e1a",
        "lang": "tr",
        "icons": [
            {"src": "/static/img/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/static/img/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/static/img/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
        "shortcuts": [
            {"name": "Cihazlar", "url": "/#devices", "icons": [{"src": "/static/img/icon-192.png", "sizes": "192x192"}]},
            {"name": "İnternet & Hız", "url": "/#internet", "icons": [{"src": "/static/img/icon-192.png", "sizes": "192x192"}]},
        ],
    }
    response = jsonify(manifest)
    response.headers["Content-Type"] = "application/manifest+json; charset=utf-8"
    return response


@app.get("/sw.js")
def service_worker():
    # Kök kapsamda (/) çalışabilmesi için kök yoldan sunulur
    response = send_from_directory(app.static_folder, "js/sw.js", mimetype="text/javascript", max_age=0)
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/guest/<token>")
def guest_page(token: str):
    if not actions.guest_valid(token):
        return render_template("guest.html", valid=False, token=token, files=[], expires=""), 403
    state = actions.get_guest_state()
    expires = state.get("expires", "")
    try:
        expires = datetime.fromisoformat(expires).astimezone().strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError):
        pass
    return render_template(
        "guest.html",
        valid=True,
        token=token,
        files=actions.shared_files(),
        expires=expires,
    )


@app.get("/guest/<token>/download/<path:name>")
def guest_download(token: str, name: str):
    if not actions.guest_valid(token):
        return jsonify({"ok": False, "message": "Misafir bağlantısı geçersiz veya süresi dolmuş."}), 403
    return send_from_directory(config.SHARE_DIR, name, as_attachment=True)


# --------------------------------------------------------------------------- #
# Durum & tarama
# --------------------------------------------------------------------------- #
@app.get("/api/status")
def api_status():
    network = netinfo.local_network()
    wifi = netinfo.wifi_status()
    stats = netinfo.adapter_stats(network.get("name", ""))
    snap = monitor.snapshot()
    settings = db.get_settings()
    share = actions.share_usage()
    history = db.scan_history(1)
    return jsonify(
        {
            "ok": True,
            "app": {
                "name": config.APP_NAME,
                "version": config.APP_VERSION,
                "hostname": socket.gethostname(),
                "admin": actions.is_admin(),
                "lan_url": netinfo.lan_url(SERVER_PORT),
                "port": SERVER_PORT,
                "started_at": getattr(app, "_started_at", None),
            },
            "network": {
                **network,
                "wifi": wifi,
                "speed_mbps": stats.get("speed_mbps", 0),
                "up": stats.get("up", False),
                "internet": snap.get("internet", True),
                "latency": snap.get("latency", {}),
                "outage": snap.get("outage", {}),
            },
            "stats": {
                "rx_bps": snap["rx_bps"],
                "tx_bps": snap["tx_bps"],
                "rx_total": snap["rx_total"],
                "tx_total": snap["tx_total"],
                "samples": snap["samples"],
            },
            "counts": _counts(),
            "share": share,
            "speed": dict(SPEED_CACHE),
            "scan": dict(SCAN_STATE),
            "last_scan": history[0] if history else None,
            "settings": {
                "auto_scan": settings.get("auto_scan") == "1",
                "scan_interval_minutes": settings.get("scan_interval_minutes", "10"),
                "subnet_override": settings.get("subnet_override", ""),
                "notify_new": settings.get("notify_new") == "1",
                "onboarded": settings.get("onboarded") == "1",
                "device_name": settings.get("device_name", ""),
                "allow_lan_control": settings.get("allow_lan_control", "0") == "1",
            },
        }
    )


@app.post("/api/scan")
@local_only
def api_scan():
    payload = request.get_json(silent=True) or {}
    started = start_scan(
        "manual",
        deep=payload.get("deep", True),
        override=payload.get("subnet") or None,
    )
    if not started:
        return jsonify({"ok": False, "message": "Zaten bir tarama sürüyor."}), 409
    return jsonify({"ok": True, "message": "Tarama başlatıldı.", "scan": dict(SCAN_STATE)})


@app.get("/api/scan/status")
def api_scan_status():
    return jsonify(
        {
            "ok": True,
            "scan": dict(SCAN_STATE),
            "devices": [_device_payload(d) for d in db.list_devices()],
            "counts": _counts(),
        }
    )


@app.get("/api/scan/history")
def api_scan_history():
    return jsonify({"ok": True, "history": db.scan_history(30)})


# --------------------------------------------------------------------------- #
# Cihazlar
# --------------------------------------------------------------------------- #
@app.get("/api/devices")
def api_devices():
    devices = [_device_payload(d) for d in db.list_devices()]
    return jsonify({"ok": True, "devices": devices, "counts": _counts()})


@app.patch("/api/devices/<int:dev_id>")
@local_only
def api_update_device(dev_id: int):
    payload = request.get_json(silent=True) or {}
    existing = db.get_device(dev_id)
    if not existing:
        return jsonify({"ok": False, "message": "Cihaz bulunamadı."}), 404
    if payload.get("type") == existing.get("type"):
        # Tür değişmediyse "elle seçildi" diye kilitleme; taramalar daha iyi tahmin yapabilsin
        payload = {k: v for k, v in payload.items() if k != "type"}
    device = db.update_device(dev_id, payload)
    if not device:
        return jsonify({"ok": False, "message": "Cihaz bulunamadı."}), 404
    if "trusted" in payload:
        db.add_alert(
            "system",
            "info",
            f"{device['display_name']} güvenilir olarak işaretlendi" if payload["trusted"] else f"{device['display_name']} güvenilir listesinden çıkarıldı",
            "Cihaz güvenlik durumu güncellendi.",
            device["mac"],
        )
    return jsonify({"ok": True, "device": _device_payload(device)})


@app.delete("/api/devices/<int:dev_id>")
@local_only
def api_delete_device(dev_id: int):
    device = db.get_device(dev_id)
    if not device:
        return jsonify({"ok": False, "message": "Cihaz bulunamadı."}), 404
    if device.get("blocked"):
        return jsonify({"ok": False, "message": "Önce cihazın engelini kaldırın."}), 400
    # Duraklatma/plan nedeniyle eklenmiş bir kural varsa cihazla birlikte kaldır;
    # aksi halde silinen cihazın kuralı uygulama kapanana kadar kalırdı.
    if monitor.blocked_state.get(device["mac"]) or device.get("paused") or device.get("schedule"):
        if device.get("ip"):
            actions.firewall_set_block(device["mac"], device["ip"], False)
    monitor.record_block(device["mac"], None, None)
    db.delete_device(dev_id)
    return jsonify({"ok": True})


@app.post("/api/devices/<int:dev_id>/merge")
@local_only
def api_merge_device(dev_id: int):
    """Bu cihaz (dev_id) ile seçilen kayıt (into) aynı fiziksel cihaz: tek kayıtta birleştir."""
    payload = request.get_json(silent=True) or {}
    into = _int_or_none(payload.get("into"))
    src, dst = db.get_device(dev_id), db.get_device(into) if into else None
    if not src or not dst:
        return jsonify({"ok": False, "message": "Cihaz bulunamadı."}), 404
    if src["id"] == dst["id"]:
        return jsonify({"ok": False, "message": "Bir cihaz kendisiyle birleştirilemez."}), 400
    if src.get("is_self") and dst.get("is_self"):
        return jsonify({"ok": False, "message": "Geçersiz birleştirme."}), 400
    # Her iki MAC için uygulanmış kuralları kaldır; birleşik kayıt için kural yeniden hesaplanır
    for d in (src, dst):
        if monitor.blocked_state.get(d["mac"]) and d.get("ip"):
            actions.firewall_set_block(d["mac"], d["ip"], False)
        monitor.record_block(d["mac"], None, None)
    merged = db.merge_devices(src["id"], dst["id"])
    if not merged:
        return jsonify({"ok": False, "message": "Birleştirilemedi."}), 400
    db.add_alert(
        "device", "info", f"Cihaz kayıtları birleştirildi: {merged['display_name']}",
        f"{src['display_name']} ({src.get('ip') or '—'}) ve {dst['display_name']} aynı cihaz olarak işaretlendi.",
        merged["mac"],
    )
    try:
        monitor.enforce_rules()
    except Exception:
        pass
    return jsonify({"ok": True, "device": _device_payload(merged)})


@app.post("/api/devices/<int:dev_id>/ping")
@local_only
def api_device_ping(dev_id: int):
    device = db.get_device(dev_id)
    if not device:
        return jsonify({"ok": False, "message": "Cihaz bulunamadı."}), 404
    ip = device.get("ip")
    if not ip:
        return jsonify({"ok": False, "message": "Cihazın IP adresi yok."}), 400
    res = actions.ping_device(ip)
    return jsonify(res)


@app.post("/api/devices/<int:dev_id>/wake")
@local_only
def api_device_wake(dev_id: int):
    device = db.get_device(dev_id)
    if not device:
        return jsonify({"ok": False, "message": "Cihaz bulunamadı."}), 404
    mac = device.get("mac")
    if not mac:
        return jsonify({"ok": False, "message": "Cihazın MAC adresi kayıtlı değil."}), 400
    res = actions.wake_on_lan(mac)
    name = device.get("name") or device.get("display_name") or device.get("ip") or mac
    db.add_alert(
        "device",
        "info",
        f"Wake-on-LAN sinyali gönderildi: {name}",
        f"{device.get('ip', '')} ({mac}) cihazına Magic Packet gönderildi.",
        mac,
    )
    return jsonify(res)


@app.post("/api/devices/<int:dev_id>/block")
@local_only
def api_block_device(dev_id: int):
    device = db.get_device(dev_id)
    if not device:
        return jsonify({"ok": False, "message": "Cihaz bulunamadı."}), 404
    if device.get("is_self") or device.get("ip") == netinfo.default_gateway():
        return jsonify({"ok": False, "message": "Kendi bilgisayarınızı veya yönlendiriciyi engelleyemezsiniz."}), 400
    payload = request.get_json(silent=True) or {}
    blocked = bool(payload.get("blocked"))
    result = actions.firewall_set_block(device["mac"], device["ip"], blocked)
    if not result["ok"]:
        return jsonify({"ok": False, "message": result["message"]}), 400
    db.update_device(dev_id, {"blocked": blocked})
    monitor.record_block(device["mac"], device["ip"], blocked)
    message = result["message"]
    if not blocked:
        # Engel kalktı ama duraklatma/plan hâlâ kısıtlıyorsa kuralı hemen geri koy
        updated = db.get_device(dev_id)
        if updated and monitor._desired_block(updated, datetime.now().astimezone()):
            again = actions.firewall_set_block(device["mac"], device["ip"], True)
            if again["ok"]:
                monitor.record_block(device["mac"], device["ip"], True)
                message = "Kalıcı engel kaldırıldı; duraklatma veya saat planı nedeniyle cihaz hâlâ kısıtlı."
    return jsonify({"ok": True, "message": message, "device": _device_payload(db.get_device(dev_id))})


@app.post("/api/devices/<int:dev_id>/pause")
@local_only
def api_pause_device(dev_id: int):
    device = db.get_device(dev_id)
    if not device:
        return jsonify({"ok": False, "message": "Cihaz bulunamadı."}), 404
    if device.get("is_self") or device.get("ip") == netinfo.default_gateway():
        return jsonify({"ok": False, "message": "Kendi bilgisayarınızı veya yönlendiriciyi duraklatamazsınız."}), 400
    payload = request.get_json(silent=True) or {}
    minutes = _int_or_none(payload.get("minutes") or 0)
    if minutes is None or minutes < 0 or minutes > 24 * 60:
        return jsonify({"ok": False, "message": "Geçersiz süre."}), 400
    if minutes > 0:
        until = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat(timespec="seconds")
        result = actions.firewall_set_block(device["mac"], device["ip"], True)
        if not result["ok"]:
            return jsonify({"ok": False, "message": result["message"]}), 400
        db.update_device(dev_id, {"pause_until": until})
        monitor.record_block(device["mac"], device["ip"], True)
        message = f"{device['display_name']} için yerel erişim {minutes} dakika duraklatıldı."
    else:
        db.update_device(dev_id, {"pause_until": None})
        updated = db.get_device(dev_id) or device
        # Kalıcı engel veya saat planı hâlâ geçerliyse kuralı kaldırma
        desired = monitor._desired_block(updated, datetime.now().astimezone())
        result = actions.firewall_set_block(device["mac"], device["ip"], desired)
        monitor.record_block(device["mac"], device["ip"], desired if result["ok"] else None)
        message = "Duraklatma kaldırıldı." if not desired else "Duraklatma kaldırıldı; cihaz engel/plan nedeniyle hâlâ kısıtlı."
    return jsonify(
        {"ok": True, "message": message, "device": _device_payload(db.get_device(dev_id))}
    )


@app.post("/api/devices/<int:dev_id>/schedule")
@local_only
def api_schedule_device(dev_id: int):
    device = db.get_device(dev_id)
    if not device:
        return jsonify({"ok": False, "message": "Cihaz bulunamadı."}), 404
    payload = request.get_json(silent=True) or {}
    schedule = payload.get("schedule")
    if schedule is not None:
        if not isinstance(schedule, dict):
            return jsonify({"ok": False, "message": "Geçersiz plan."}), 400
        cleaned: dict[str, list[int]] = {}
        for day in range(7):
            hours = schedule.get(str(day))
            if hours is None:
                continue
            if not isinstance(hours, list):
                return jsonify({"ok": False, "message": "Geçersiz plan."}), 400
            values = {_int_or_none(h) for h in hours}
            cleaned[str(day)] = sorted(h for h in values if h is not None and 0 <= h <= 23)
        schedule = cleaned or None
    db.update_device(dev_id, {"schedule": schedule})
    device = db.get_device(dev_id)
    if actions.is_admin() and device and device.get("ip") and not device.get("is_self"):
        desired = monitor._desired_block(device, datetime.now().astimezone())
        result = actions.firewall_set_block(device["mac"], device["ip"], desired)
        monitor.record_block(device["mac"], device["ip"], desired if result["ok"] else None)
    return jsonify({"ok": True, "device": _device_payload(db.get_device(dev_id))})


# --------------------------------------------------------------------------- #
# Uyarılar & trafik
# --------------------------------------------------------------------------- #
@app.get("/api/alerts")
def api_alerts():
    return jsonify(
        {
            "ok": True,
            "alerts": db.list_alerts(120),
            "unread": db.unread_alert_count(),
        }
    )


@app.post("/api/alerts/read")
@local_only
def api_alerts_read():
    payload = request.get_json(silent=True) or {}
    db.mark_alerts_read(payload.get("ids"))
    return jsonify({"ok": True, "unread": db.unread_alert_count()})


@app.delete("/api/alerts")
@local_only
def api_alerts_clear():
    db.clear_alerts()
    return jsonify({"ok": True})


@app.get("/api/traffic")
def api_traffic():
    minutes = request.args.get("minutes", default=60, type=int)
    if minutes <= 0:
        data = monitor.snapshot()["samples"]
    else:
        data = db.traffic_history(minutes)
        live = monitor.snapshot()["samples"]
        seen = {row["ts"] for row in data}
        data += [row for row in live if row["ts"] not in seen]
        data.sort(key=lambda r: r["ts"])
    return jsonify({"ok": True, "samples": data})


# --------------------------------------------------------------------------- #
# İnternet, Wi-Fi, yazıcı, onarım
# --------------------------------------------------------------------------- #
@app.post("/api/speedtest/run")
@local_only
def api_speedtest_run():
    global SPEED_CACHE
    if not SPEED_LOCK.acquire(blocking=False):
        return jsonify({"ok": False, "message": "Hız testi zaten çalışıyor."}), 409
    try:
        result = actions.speedtest()
        SPEED_CACHE = result
        return jsonify({"ok": True, "result": result})
    finally:
        SPEED_LOCK.release()


@app.get("/api/speedtest")
def api_speedtest_get():
    return jsonify({"ok": True, "result": SPEED_CACHE or None})


@app.get("/api/latency")
def api_latency():
    """Modem (yerel ağ) ve internet (sağlayıcı) gecikmesi + teşhis."""
    minutes = max(5, min(7 * 24 * 60, request.args.get("minutes", default=60, type=int)))
    recent = monitor.latency_samples(5)
    gw5 = monitor_mod.summarize_latency([s["gw_ms"] for s in recent])
    inet5 = monitor_mod.summarize_latency([s["inet_ms"] for s in recent])
    if minutes <= 60:
        samples = monitor.latency_samples(minutes)
        series_gw = [s["gw_ms"] for s in samples]
        series_inet = [s["inet_ms"] for s in samples]
        resolution = 10
    else:
        rows = db.latency_history(minutes)
        samples = [
            {"ts": r["ts"], "gw_ms": r["gw_ms"], "inet_ms": r["inet_ms"],
             "gw_loss": r["gw_loss"], "inet_loss": r["inet_loss"]}
            for r in rows
        ]
        series_gw = [r["gw_ms"] for r in rows]
        series_inet = [r["inet_ms"] for r in rows]
        resolution = 60
    return jsonify(
        {
            "ok": True,
            "minutes": minutes,
            "resolution_s": resolution,
            "samples": samples,
            "summary": {
                "gw": monitor_mod.summarize_latency(series_gw),
                "inet": monitor_mod.summarize_latency(series_inet),
            },
            "recent": {"gw": gw5, "inet": inet5},
            "verdict": monitor_mod.latency_verdict(gw5, inet5),
            "gateway": netinfo.default_gateway(),
        }
    )


@app.get("/api/outages")
def api_outages():
    days = request.args.get("days", default=30, type=int)
    return jsonify({"ok": True, **db.outage_report(days)})


@app.get("/api/wifi")
def api_wifi():
    return jsonify(
        {"ok": True, "status": netinfo.wifi_status(), "networks": netinfo.wifi_networks()}
    )


@app.get("/api/wifi/analyzer")
def api_wifi_analyzer():
    refresh = request.args.get("refresh") == "1"
    return jsonify({"ok": True, "analysis": netinfo.wifi_channel_analysis(refresh=refresh)})


@app.post("/api/test-notification")
@local_only
def api_test_notification():
    ok = actions.send_desktop_notification(
        "Network Magic Bildirim Testi",
        "Masaüstü bildirimleri ve Wi-Fi hırsız alarmı sorunsuz çalışıyor!"
    )
    return jsonify({"ok": ok, "message": "Masaüstü test bildirimi gönderildi."})


@app.get("/api/printers")
def api_printers():
    return jsonify({"ok": True, "printers": netinfo.printers()})


@app.post("/api/repair")
@local_only
def api_repair():
    payload = request.get_json(silent=True) or {}
    iface = netinfo.primary_interface().get("name", "")
    result = actions.repair(payload.get("action", ""), iface)
    if result.get("ok"):
        netinfo.invalidate_caches()
    status = 200 if result["ok"] or result.get("output") is not None else 400
    return jsonify({"ok": result["ok"], "message": result["message"], "output": result.get("output", "")}), status


# --------------------------------------------------------------------------- #
# Dosya paylaşımı & misafir
# --------------------------------------------------------------------------- #
@app.get("/api/share")
def api_share():
    return jsonify(
        {
            "ok": True,
            "files": actions.shared_files(),
            "usage": actions.share_usage(),
            "url": netinfo.lan_url(SERVER_PORT) + "/share",
            "guest": _guest_state_for_request(),
        }
    )


@app.post("/api/share/upload")
@local_only
def api_share_upload():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"ok": False, "message": "Dosya seçilmedi."}), 400
    uploaded = []
    for item in files:
        if item and item.filename:
            uploaded.append(actions.save_upload(item.filename, item.stream))
    return jsonify({"ok": True, "uploaded": uploaded, "files": actions.shared_files()})


@app.delete("/api/share/<path:name>")
@local_only
def api_share_delete(name: str):
    ok = actions.delete_shared_file(name)
    return jsonify({"ok": ok, "files": actions.shared_files()})


@app.get("/share/<path:name>")
def api_share_download(name: str):
    return send_from_directory(config.SHARE_DIR, name, as_attachment=True)


def _can_manage() -> bool:
    return _is_local_request() or db.get_setting("allow_lan_control", "0") == "1"


def _guest_state_for_request() -> dict:
    """Misafir anahtarı yalnızca yönetim yetkisi olan isteklere verilir; aksi halde ağdaki
    herhangi bir cihaz /api üzerinden anahtarı okuyabilirdi."""
    state = actions.get_guest_state()
    if not _can_manage():
        state = {**state, "token": ""}
    return state


@app.get("/api/guest")
def api_guest():
    state = _guest_state_for_request()
    link = f"{netinfo.lan_url(SERVER_PORT)}/guest/{state['token']}" if state["enabled"] and state["token"] else ""
    return jsonify(
        {
            "ok": True,
            "guest": state,
            "link": link,
            "qr": actions.qr_data_uri(link) if link else "",
        }
    )


@app.post("/api/guest")
@local_only
def api_guest_set():
    payload = request.get_json(silent=True) or {}
    hours = max(1, min(24 * 30, _int_or_none(payload.get("hours")) or 24))
    state = actions.set_guest_access(bool(payload.get("enabled")), hours)
    link = f"{netinfo.lan_url(SERVER_PORT)}/guest/{state['token']}" if state["enabled"] else ""
    return jsonify(
        {
            "ok": True,
            "guest": state,
            "link": link,
            "qr": actions.qr_data_uri(link) if link else "",
        }
    )


@app.get("/api/qr")
def api_qr():
    text = request.args.get("text", "")
    if not text:
        return jsonify({"ok": False, "message": "Metin gerekli."}), 400
    return jsonify({"ok": True, "qr": actions.qr_data_uri(text)})


# --------------------------------------------------------------------------- #
# Ayarlar, rapor, sıfırlama
# --------------------------------------------------------------------------- #
@app.get("/api/settings")
def api_settings_get():
    settings = db.get_settings()
    settings.pop("guest_token", None)
    return jsonify({"ok": True, "settings": settings, "admin": actions.is_admin()})


@app.put("/api/settings")
@local_only
def api_settings_put():
    payload = request.get_json(silent=True) or {}
    allowed = {
        "auto_scan",
        "scan_interval_minutes",
        "subnet_override",
        "notify_new",
        "device_name",
        "allow_lan_control",
    }
    values: dict[str, str] = {}
    for key, value in payload.items():
        if key not in allowed:
            continue
        if key in {"auto_scan", "notify_new", "allow_lan_control"}:
            values[key] = "1" if value else "0"
        elif key == "scan_interval_minutes":
            try:
                values[key] = str(max(2, min(1440, int(value))))
            except (TypeError, ValueError):
                continue
        elif key == "subnet_override":
            values[key] = str(value or "").strip()
        else:
            values[key] = str(value or "").strip()[:80]
    previous_name = db.get_setting("device_name", "")
    db.set_settings(values)
    if values.get("device_name") and values["device_name"] != previous_name:
        _apply_self_name(force=True)
    settings = db.get_settings()
    settings.pop("guest_token", None)
    return jsonify({"ok": True, "settings": settings})


@app.post("/api/onboarding")
@local_only
def api_onboarding():
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("device_name") or "").strip()[:80]
    values = {"onboarded": "1"}
    if name:
        values["device_name"] = name
    db.set_settings(values)
    if name:
        _apply_self_name(force=True)
    return jsonify({"ok": True})


@app.post("/api/reset")
@local_only
def api_reset():
    payload = request.get_json(silent=True) or {}
    if str(payload.get("confirm", "")).upper() != "SIFIRLA":
        return jsonify({"ok": False, "message": "Onay metni hatalı."}), 400
    db.clear_devices()
    db.set_setting("baseline_done", "0")
    actions.firewall_cleanup_all()
    monitor.forget_all()
    return jsonify({"ok": True, "message": "Tüm cihaz kayıtları ve geçmiş silindi."})


@app.get("/api/report")
def api_report():
    devices = db.list_devices()
    by_type: dict[str, int] = {}
    vendors: dict[str, int] = {}
    for d in devices:
        by_type[d.get("type") or "unknown"] = by_type.get(d.get("type") or "unknown", 0) + 1
        if d.get("vendor"):
            vendors[d["vendor"]] = vendors.get(d["vendor"], 0) + 1
    traffic = db.traffic_history(24 * 60)
    rx_bytes = sum(row["rx_bps"] for row in traffic) * 60 / 8
    tx_bytes = sum(row["tx_bps"] for row in traffic) * 60 / 8
    return jsonify(
        {
            "ok": True,
            "generated_at": db.iso(),
            "counts": _counts(),
            "by_type": by_type,
            "top_vendors": sorted(vendors.items(), key=lambda x: x[1], reverse=True)[:8],
            "traffic_24h": {"rx_bytes": round(rx_bytes), "tx_bytes": round(tx_bytes)},
            "devices": [_device_payload(d) for d in devices],
        }
    )


@app.get("/api/export/devices.csv")
def api_export_devices():
    devices = db.list_devices()
    buffer = io.StringIO()
    buffer.write("\ufeff")
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(
        ["Ad", "IP", "MAC", "Üretici", "Tür", "Güvenilir", "Engelli", "Çevrimiçi", "İlk görülme", "Son görülme", "Not"]
    )
    for d in devices:
        writer.writerow(
            [
                d.get("display_name", ""),
                d.get("ip", ""),
                d.get("mac", ""),
                d.get("vendor", ""),
                config.DEVICE_TYPES.get(d.get("type", "unknown"), d.get("type", "")),
                "Evet" if d.get("trusted") else "Hayır",
                "Evet" if d.get("blocked") else "Hayır",
                "Evet" if d.get("online") else "Hayır",
                d.get("first_seen", ""),
                d.get("last_seen", ""),
                d.get("notes", ""),
            ]
        )
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=network-magic-cihazlar.csv"},
    )


@app.post("/api/quit")
@local_only
def api_quit():
    monitor.stop()
    threading.Timer(0.6, lambda: os._exit(0)).start()
    return jsonify({"ok": True, "message": "Network Magic kapatılıyor."})


@app.errorhandler(404)
def not_found(error):
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "message": "Bulunamadı."}), 404
    if request.path.startswith(("/share/", "/guest/", "/static/")):
        # Silinmiş dosya / eski bağlantı: kontrol paneli yerine açık bir "bulunamadı" sayfası
        return render_template("guest.html", valid=False, missing=True, token="", files=[], expires=""), 404
    return render_template("index.html", version=config.APP_VERSION, app_name=config.APP_NAME, tagline=config.APP_TAGLINE), 200


@app.errorhandler(500)
def server_error(error):
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "message": "Sunucu hatası."}), 500
    return "Sunucu hatası", 500


def main() -> None:
    global SERVER_PORT
    port = int(os.environ.get("NETMAGIC_PORT", str(config.DEFAULT_PORT)))
    SERVER_PORT = port
    app._started_at = db.iso()
    monitor.start()
    url = f"http://127.0.0.1:{port}"
    lan = netinfo.lan_url(port)
    print("=" * 62)
    print(f"  {config.APP_NAME} {config.APP_VERSION} - {config.APP_TAGLINE}")
    print(f"  Yerel:  {url}")
    print(f"  Ağ:     {lan}")
    print(f"  Yönetici: {'Evet' if actions.is_admin() else 'Hayır (engelleme özellikleri sınırlı)'}")
    print("  Kapatmak için Ctrl+C")
    print("=" * 62)
    if os.environ.get("NETMAGIC_NO_BROWSER") != "1":
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    try:
        app.run(host=config.HOST, port=port, threaded=True, use_reloader=False)
    finally:
        monitor.stop()


if __name__ == "__main__":
    main()
