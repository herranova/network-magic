"""SQLite veri katmanı."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from . import config

_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mac TEXT NOT NULL UNIQUE,
    ip TEXT,
    hostname TEXT,
    vendor TEXT,
    name TEXT,
    type TEXT DEFAULT 'unknown',
    trusted INTEGER DEFAULT 0,
    blocked INTEGER DEFAULT 0,
    notes TEXT DEFAULT '',
    open_ports TEXT DEFAULT '[]',
    services TEXT DEFAULT '{}',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    online INTEGER DEFAULT 0,
    pause_until TEXT,
    schedule TEXT,
    is_self INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT,
    mac TEXT,
    read INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS traffic (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    rx_bps REAL DEFAULT 0,
    tx_bps REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started TEXT NOT NULL,
    finished TEXT,
    device_count INTEGER DEFAULT 0,
    new_count INTEGER DEFAULT 0,
    kind TEXT DEFAULT 'manual'
);
CREATE TABLE IF NOT EXISTS outages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started TEXT NOT NULL,
    ended TEXT,
    cause TEXT DEFAULT 'unknown'
);
CREATE TABLE IF NOT EXISTS latency (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    gw_ms REAL,
    inet_ms REAL,
    gw_loss REAL DEFAULT 0,
    inet_loss REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_outages_started ON outages(started);
CREATE INDEX IF NOT EXISTS idx_latency_ts ON latency(ts);
CREATE INDEX IF NOT EXISTS idx_traffic_ts ON traffic(ts);
CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(ts);
CREATE INDEX IF NOT EXISTS idx_devices_last ON devices(last_seen);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    return (dt or utcnow()).isoformat(timespec="seconds")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.SHARE_DIR.mkdir(parents=True, exist_ok=True)
    with _lock, _conn() as conn:
        conn.executescript(SCHEMA)
        # Şema göçleri (eski veritabanlarına yeni sütunlar)
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(devices)").fetchall()}
        if "type_manual" not in columns:
            conn.execute("ALTER TABLE devices ADD COLUMN type_manual INTEGER DEFAULT 0")
        for key, value in config.DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)", (key, value)
            )
        # Loopback / 127.x sahte cihaz ve uyarılarını temizle
        conn.execute("DELETE FROM devices WHERE ip LIKE '127.%' OR mac LIKE 'ip-127.%'")
        conn.execute("DELETE FROM alerts WHERE mac LIKE 'ip-127.%' OR message LIKE '%127.%'")
        conn.commit()


# --------------------------------------------------------------------------- #
# Ayarlar
# --------------------------------------------------------------------------- #
def get_settings() -> dict[str, str]:
    with _lock, _conn() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    data = dict(config.DEFAULT_SETTINGS)
    data.update({r["key"]: r["value"] for r in rows})
    return data


def get_setting(key: str, default: str = "") -> str:
    with _lock, _conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: Any) -> None:
    with _lock, _conn() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        conn.commit()


def set_settings(values: dict[str, Any]) -> None:
    with _lock, _conn() as conn:
        for key, value in values.items():
            conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )
        conn.commit()


# --------------------------------------------------------------------------- #
# Cihazlar
# --------------------------------------------------------------------------- #
def is_random_mac(mac: str) -> bool:
    """Yerel yönetilen (gizlilik amaçlı rastgele) MAC: ilk baytın 2. biti 1."""
    hexchars = "".join(c for c in (mac or "") if c in "0123456789abcdefABCDEF")
    if len(hexchars) != 12:
        return False
    return bool(int(hexchars[1], 16) & 0x2)


def _is_meaningful_hostname(name: str) -> bool:
    name = (name or "").strip()
    if len(name) < 3:
        return False
    # IP benzeri veya yalnızca sayı olan adlar eşleştirme için güvenilmez
    return not all(c.isdigit() or c in ".-_:" for c in name)


def _row_to_device(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    try:
        d["open_ports"] = json.loads(d.get("open_ports") or "[]")
    except (json.JSONDecodeError, TypeError):
        d["open_ports"] = []
    try:
        d["services"] = json.loads(d.get("services") or "{}")
    except (json.JSONDecodeError, TypeError):
        d["services"] = {}
    try:
        d["schedule"] = json.loads(d["schedule"]) if d.get("schedule") else None
    except (json.JSONDecodeError, TypeError):
        d["schedule"] = None
    d["trusted"] = bool(d.get("trusted"))
    d["blocked"] = bool(d.get("blocked"))
    d["online"] = bool(d.get("online"))
    d["is_self"] = bool(d.get("is_self"))
    d["type_manual"] = bool(d.get("type_manual"))
    d["random_mac"] = is_random_mac(d.get("mac") or "")
    d["paused"] = bool(d.get("pause_until") and d["pause_until"] > iso())
    name = (d.get("name") or "").strip()
    hostname = (d.get("hostname") or "").strip()
    vendor = (d.get("vendor") or "").strip()
    if vendor.lower() == "rastgele mac":
        vendor = ""
    d["display_name"] = name or hostname or vendor or d.get("ip") or d["mac"]
    return d


def list_devices() -> list[dict[str, Any]]:
    with _lock, _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM devices ORDER BY online DESC, trusted ASC, last_seen DESC"
        ).fetchall()
    return [_row_to_device(r) for r in rows]


def get_device(dev_id: int) -> dict[str, Any] | None:
    with _lock, _conn() as conn:
        row = conn.execute("SELECT * FROM devices WHERE id=?", (dev_id,)).fetchone()
    return _row_to_device(row) if row else None


def get_device_by_mac(mac: str) -> dict[str, Any] | None:
    with _lock, _conn() as conn:
        row = conn.execute("SELECT * FROM devices WHERE mac=?", (mac,)).fetchone()
    return _row_to_device(row) if row else None


def find_by_ip(ip: str) -> dict[str, Any] | None:
    with _lock, _conn() as conn:
        row = conn.execute(
            "SELECT * FROM devices WHERE ip=? ORDER BY last_seen DESC LIMIT 1", (ip,)
        ).fetchone()
    return _row_to_device(row) if row else None


def upsert_scan(
    results: Iterable[dict[str, Any]],
    baseline: bool = False,
    merged: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Tarama sonuçlarını kaydeder. Yeni cihazların listesini döndürür.

    `merged` verilirse, MAC adresini değiştirmiş (rastgele MAC) ama aynı ada sahip olduğu için
    eski kaydıyla otomatik eşleştirilen cihazlar bu listeye eklenir.
    """
    now = iso()
    new_devices: list[dict[str, Any]] = []
    results = list(results)
    scan_macs = {(i.get("mac") or "").upper() for i in results}
    with _lock, _conn() as conn:
        for item in results:
            ip = item.get("ip") or ""
            mac = (item.get("mac") or "").upper()
            if not mac or not ip:
                continue
            if ip.startswith(("127.", "169.254.", "0.")) or mac.startswith("IP-127."):
                continue
            row = conn.execute("SELECT * FROM devices WHERE mac=?", (mac,)).fetchone()
            placeholder = f"IP-{ip}"
            if mac != placeholder:
                ph_row = conn.execute("SELECT id FROM devices WHERE mac=?", (placeholder,)).fetchone()
                if ph_row:
                    if row:
                        # Gerçek MAC zaten kayıtlı: geçici "IP-" kaydı artık gereksiz
                        conn.execute("DELETE FROM devices WHERE id=?", (ph_row["id"],))
                    else:
                        # Daha önce MAC'siz görülen cihaz: kaydı (ad/not/güven) koruyarak MAC'e taşı
                        conn.execute("UPDATE devices SET mac=? WHERE id=?", (mac, ph_row["id"]))
                        row = conn.execute("SELECT * FROM devices WHERE mac=?", (mac,)).fetchone()
            hostname = (item.get("hostname") or "").strip()[:120]
            if not row and is_random_mac(mac) and _is_meaningful_hostname(hostname):
                # Telefonlar gizlilik için MAC'ini değiştirebilir. Aynı ada sahip, bu taramada
                # görünmeyen eski bir rastgele-MAC kaydı varsa onu güncelle (ad/not/güven korunur).
                for cand in conn.execute(
                    "SELECT * FROM devices WHERE lower(hostname)=lower(?) AND mac<>? ORDER BY last_seen DESC",
                    (hostname, mac),
                ).fetchall():
                    if cand["mac"] in scan_macs or not is_random_mac(cand["mac"]) or cand["is_self"]:
                        continue
                    conn.execute("UPDATE devices SET mac=? WHERE id=?", (mac, cand["id"]))
                    row = conn.execute("SELECT * FROM devices WHERE mac=?", (mac,)).fetchone()
                    if merged is not None:
                        merged.append({
                            "id": cand["id"], "old_mac": cand["mac"], "mac": mac, "ip": ip,
                            "name": (cand["name"] or "").strip() or hostname,
                        })
                    break
            ports = json.dumps(item.get("open_ports") or [])
            services = json.dumps(item.get("services") or {}, ensure_ascii=False)
            vendor = (item.get("vendor") or "").strip()[:80]
            dtype = item.get("type") or "unknown"
            is_self = 1 if item.get("is_self") else 0
            if row:
                current = _row_to_device(row)
                conn.execute(
                    """UPDATE devices SET ip=?, hostname=COALESCE(NULLIF(?, ''), hostname),
                       vendor=COALESCE(NULLIF(?, ''), vendor), type=?, open_ports=?, services=?,
                       last_seen=?, online=1, is_self=? WHERE mac=?""",
                    (
                        item.get("ip"),
                        hostname,
                        vendor,
                        # Kullanıcının elle seçtiği tür tahminle ezilmez
                        current["type"] if current["type_manual"] or dtype == "unknown" else dtype,
                        ports,
                        services,
                        now,
                        is_self,
                        mac,
                    ),
                )
            else:
                conn.execute(
                    """INSERT INTO devices
                       (mac, ip, hostname, vendor, name, type, trusted, blocked, notes,
                        open_ports, services, first_seen, last_seen, online, is_self)
                       VALUES(?,?,?,?,?,?,?,0,'',?,?,?,?,1,?)""",
                    (
                        mac,
                        item.get("ip"),
                        hostname,
                        vendor,
                        "",
                        dtype,
                        1 if baseline else 0,
                        ports,
                        services,
                        now,
                        now,
                        is_self,
                    ),
                )
                new_devices.append(
                    {
                        "mac": mac,
                        "ip": item.get("ip"),
                        "name": item.get("display_name")
                        or hostname
                        or (vendor if vendor and vendor != "Rastgele MAC" else "")
                        or item.get("ip"),
                        "vendor": vendor,
                        "type": dtype,
                    }
                )
        conn.commit()
    return new_devices


def mark_offline_except(active_macs: set[str]) -> None:
    if not active_macs:
        return
    placeholders = ",".join("?" for _ in active_macs)
    with _lock, _conn() as conn:
        conn.execute(
            f"UPDATE devices SET online=0 WHERE mac NOT IN ({placeholders})",
            tuple(active_macs),
        )
        conn.commit()


def set_online(mac: str, online: bool) -> None:
    with _lock, _conn() as conn:
        if online:
            conn.execute(
                "UPDATE devices SET online=1, last_seen=? WHERE mac=?", (iso(), mac)
            )
        else:
            conn.execute("UPDATE devices SET online=0 WHERE mac=?", (mac,))
        conn.commit()


def update_device(dev_id: int, fields: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"name", "type", "trusted", "blocked", "notes", "hostname", "vendor", "schedule", "pause_until", "type_manual"}
    fields = dict(fields)
    if "type" in fields and "type_manual" not in fields:
        fields["type_manual"] = 1  # arayüzden tür seçildi: taramalar artık değiştirmesin
    sets, values = [], []
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key == "type" and value not in config.DEVICE_TYPES:
            continue
        if key == "type_manual":
            value = 1 if value else 0
        if key == "schedule":
            value = json.dumps(value) if value else None
        if key in {"trusted", "blocked"}:
            value = 1 if value else 0
        sets.append(f"{key}=?")
        values.append(value)
    if not sets:
        return get_device(dev_id)
    values.append(dev_id)
    with _lock, _conn() as conn:
        conn.execute(f"UPDATE devices SET {', '.join(sets)} WHERE id=?", tuple(values))
        conn.commit()
    return get_device(dev_id)


def delete_device(dev_id: int) -> None:
    with _lock, _conn() as conn:
        conn.execute("DELETE FROM devices WHERE id=?", (dev_id,))
        conn.commit()


def merge_devices(src_id: int, dst_id: int) -> dict[str, Any] | None:
    """`src` ile `dst` aynı fiziksel cihaz: `dst` kaydı (ad, not, güven, tür, plan) korunur,
    ağ kimliği (MAC, IP, servisler, son görülme) `src`'den alınır, `src` silinir."""
    if src_id == dst_id:
        return None
    with _lock, _conn() as conn:
        src = conn.execute("SELECT * FROM devices WHERE id=?", (src_id,)).fetchone()
        dst = conn.execute("SELECT * FROM devices WHERE id=?", (dst_id,)).fetchone()
        if not src or not dst:
            return None
        newer = src if (src["last_seen"] or "") >= (dst["last_seen"] or "") else dst
        conn.execute("DELETE FROM devices WHERE id=?", (src_id,))
        conn.execute(
            """UPDATE devices SET mac=?, ip=?, hostname=?, vendor=?, open_ports=?, services=?,
               first_seen=?, last_seen=?, online=?, is_self=?, name=?, notes=?, trusted=?,
               type=?, type_manual=? WHERE id=?""",
            (
                newer["mac"],
                newer["ip"],
                (newer["hostname"] or "").strip() or src["hostname"] or dst["hostname"],
                (newer["vendor"] or "").strip() or src["vendor"] or dst["vendor"],
                newer["open_ports"],
                newer["services"],
                min(src["first_seen"], dst["first_seen"]),
                max(src["last_seen"], dst["last_seen"]),
                1 if (src["online"] or dst["online"]) else 0,
                1 if (src["is_self"] or dst["is_self"]) else 0,
                (dst["name"] or "").strip() or src["name"] or "",
                (dst["notes"] or "").strip() or src["notes"] or "",
                1 if (src["trusted"] or dst["trusted"]) else 0,
                dst["type"] if (dst["type_manual"] or dst["type"] != "unknown") else src["type"],
                1 if (dst["type_manual"] or src["type_manual"]) else 0,
                dst_id,
            ),
        )
        conn.commit()
    return get_device(dst_id)


def clear_devices() -> None:
    with _lock, _conn() as conn:
        conn.execute("DELETE FROM devices")
        conn.execute("DELETE FROM alerts")
        conn.execute("DELETE FROM traffic")
        conn.execute("DELETE FROM latency")
        conn.execute("DELETE FROM outages")
        conn.commit()


# --------------------------------------------------------------------------- #
# Uyarılar
# --------------------------------------------------------------------------- #
def add_alert(
    kind: str,
    severity: str,
    title: str,
    message: str = "",
    mac: str | None = None,
    dedupe_minutes: int = 0,
) -> int:
    with _lock, _conn() as conn:
        if dedupe_minutes and mac:
            cutoff = iso(utcnow() - timedelta(minutes=dedupe_minutes))
            dup = conn.execute(
                "SELECT id FROM alerts WHERE kind=? AND mac=? AND ts>? LIMIT 1",
                (kind, mac, cutoff),
            ).fetchone()
            if dup:
                return dup["id"]
        cur = conn.execute(
            "INSERT INTO alerts(ts, kind, severity, title, message, mac, read) "
            "VALUES(?,?,?,?,?,?,0)",
            (iso(), kind, severity, title, message, mac),
        )
        conn.commit()
        return int(cur.lastrowid)


def list_alerts(limit: int = 100, unread_only: bool = False) -> list[dict[str, Any]]:
    query = "SELECT * FROM alerts"
    params: tuple[Any, ...] = ()
    if unread_only:
        query += " WHERE read=0"
    query += " ORDER BY ts DESC LIMIT ?"
    params = params + (limit,)
    with _lock, _conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) | {"read": bool(r["read"])} for r in rows]


def mark_alerts_read(ids: list[int] | None = None) -> None:
    with _lock, _conn() as conn:
        if ids:
            placeholders = ",".join("?" for _ in ids)
            conn.execute(f"UPDATE alerts SET read=1 WHERE id IN ({placeholders})", tuple(ids))
        else:
            conn.execute("UPDATE alerts SET read=1")
        conn.commit()


def clear_alerts() -> None:
    with _lock, _conn() as conn:
        conn.execute("DELETE FROM alerts")
        conn.commit()


def unread_alert_count() -> int:
    with _lock, _conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM alerts WHERE read=0").fetchone()
    return int(row["c"])


# --------------------------------------------------------------------------- #
# Trafik geçmişi
# --------------------------------------------------------------------------- #
def add_traffic(rx_bps: float, tx_bps: float, ts: str | None = None) -> None:
    with _lock, _conn() as conn:
        conn.execute(
            "INSERT INTO traffic(ts, rx_bps, tx_bps) VALUES(?,?,?)",
            (ts or iso(), round(rx_bps, 1), round(tx_bps, 1)),
        )
        conn.commit()


def traffic_history(minutes: int = 60) -> list[dict[str, Any]]:
    cutoff = iso(utcnow() - timedelta(minutes=max(1, minutes)))
    with _lock, _conn() as conn:
        rows = conn.execute(
            "SELECT ts, rx_bps, tx_bps FROM traffic WHERE ts>=? ORDER BY ts ASC",
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


def recent_traffic(limit: int = 120) -> list[dict[str, Any]]:
    with _lock, _conn() as conn:
        rows = conn.execute(
            "SELECT ts, rx_bps, tx_bps FROM traffic ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


# --------------------------------------------------------------------------- #
# Tarama kayıtları
# --------------------------------------------------------------------------- #
def start_scan(kind: str = "manual") -> int:
    with _lock, _conn() as conn:
        cur = conn.execute(
            "INSERT INTO scans(started, kind) VALUES(?,?)", (iso(), kind)
        )
        conn.commit()
        return int(cur.lastrowid)


def finish_scan(scan_id: int, device_count: int, new_count: int) -> None:
    with _lock, _conn() as conn:
        conn.execute(
            "UPDATE scans SET finished=?, device_count=?, new_count=? WHERE id=?",
            (iso(), device_count, new_count, scan_id),
        )
        conn.commit()


def scan_history(limit: int = 20) -> list[dict[str, Any]]:
    with _lock, _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM scans ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def prune() -> None:
    traffic_cutoff = iso(utcnow() - timedelta(days=31))
    latency_cutoff = iso(utcnow() - timedelta(days=7))
    alert_cutoff = iso(utcnow() - timedelta(days=30))
    outage_cutoff = iso(utcnow() - timedelta(days=365))
    with _lock, _conn() as conn:
        # Trafik satırları kesinti raporunda "izlenen süre" hesabı için 31 gün tutulur
        conn.execute("DELETE FROM traffic WHERE ts<?", (traffic_cutoff,))
        conn.execute("DELETE FROM latency WHERE ts<?", (latency_cutoff,))
        conn.execute("DELETE FROM alerts WHERE read=1 AND ts<?", (alert_cutoff,))
        conn.execute("DELETE FROM outages WHERE started<?", (outage_cutoff,))
        conn.commit()


# --------------------------------------------------------------------------- #
# İnternet kesintileri
# --------------------------------------------------------------------------- #
def start_outage(started: str, cause: str = "unknown") -> int:
    with _lock, _conn() as conn:
        cur = conn.execute("INSERT INTO outages(started, cause) VALUES(?,?)", (started, cause))
        conn.commit()
        return int(cur.lastrowid)


def end_outage(outage_id: int, ended: str | None = None) -> None:
    with _lock, _conn() as conn:
        conn.execute("UPDATE outages SET ended=? WHERE id=? AND ended IS NULL", (ended or iso(), outage_id))
        conn.commit()


def close_open_outages(ended: str) -> int:
    """Uygulama kesinti sırasında kapandıysa açık kalan kaydı son canlılık zamanında kapatır."""
    with _lock, _conn() as conn:
        cur = conn.execute(
            "UPDATE outages SET ended=CASE WHEN ? > started THEN ? ELSE started END WHERE ended IS NULL",
            (ended, ended),
        )
        conn.commit()
        return cur.rowcount


def _duration_s(started: str, ended: str | None) -> int:
    try:
        a = datetime.fromisoformat(started)
        b = datetime.fromisoformat(ended) if ended else utcnow()
        return max(0, int((b - a).total_seconds()))
    except (TypeError, ValueError):
        return 0


def outage_report(days: int = 30) -> dict[str, Any]:
    days = max(1, min(365, int(days)))
    since_dt = utcnow() - timedelta(days=days)
    since = iso(since_dt)
    with _lock, _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM outages WHERE COALESCE(ended, ?) >= ? ORDER BY started DESC",
            (iso(), since),
        ).fetchall()
        # İzlenen süre: uygulama açıkken her dakika bir trafik satırı yazılır
        monitored_min = conn.execute("SELECT COUNT(*) AS c FROM traffic WHERE ts>=?", (since,)).fetchone()["c"]
    outages = []
    for r in rows:
        start = max(r["started"], since)  # pencere başlangıcından önce başlayanı kırp
        outages.append({
            "id": r["id"],
            "started": r["started"],
            "ended": r["ended"],
            "ongoing": r["ended"] is None,
            "cause": r["cause"] or "unknown",
            "duration_s": _duration_s(r["started"], r["ended"]),
            "window_s": _duration_s(start, r["ended"]),
        })
    total = sum(o["window_s"] for o in outages)
    monitored_s = int(monitored_min) * 60
    # Günlük dağılım (yerel saat)
    daily: dict[str, dict[str, int]] = {}
    for i in range(min(days, 31)):
        d = (datetime.now().astimezone() - timedelta(days=i)).strftime("%Y-%m-%d")
        daily[d] = {"down_s": 0, "count": 0}
    for o in outages:
        try:
            d = datetime.fromisoformat(o["started"]).astimezone().strftime("%Y-%m-%d")
        except ValueError:
            continue
        if d in daily:
            daily[d]["down_s"] += o["window_s"]
            daily[d]["count"] += 1
    return {
        "days": days,
        "outages": outages[:200],
        "summary": {
            "count": len(outages),
            "total_s": total,
            "longest_s": max((o["duration_s"] for o in outages), default=0),
            "isp_count": sum(1 for o in outages if o["cause"] == "isp"),
            "local_count": sum(1 for o in outages if o["cause"] == "local"),
            "monitored_s": monitored_s,
            "uptime_pct": round(100 * (1 - total / monitored_s), 2) if monitored_s > 0 else None,
            "ongoing": any(o["ongoing"] for o in outages),
        },
        "daily": [{"date": k, **v} for k, v in sorted(daily.items())],
    }


# --------------------------------------------------------------------------- #
# Gecikme (modem ve internet) — dakikalık özet
# --------------------------------------------------------------------------- #
def add_latency(gw_ms: float | None, inet_ms: float | None, gw_loss: float, inet_loss: float, ts: str | None = None) -> None:
    with _lock, _conn() as conn:
        conn.execute(
            "INSERT INTO latency(ts, gw_ms, inet_ms, gw_loss, inet_loss) VALUES(?,?,?,?,?)",
            (ts or iso(), gw_ms, inet_ms, round(gw_loss, 1), round(inet_loss, 1)),
        )
        conn.commit()


def latency_history(minutes: int = 1440) -> list[dict[str, Any]]:
    cutoff = iso(utcnow() - timedelta(minutes=max(1, minutes)))
    with _lock, _conn() as conn:
        rows = conn.execute(
            "SELECT ts, gw_ms, inet_ms, gw_loss, inet_loss FROM latency WHERE ts>=? ORDER BY ts ASC",
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]
