"""Arka plan izleyici: trafik, varlık kontrolü, kural uygulama, otomatik tarama."""
from __future__ import annotations

import atexit
import socket
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Callable

import psutil

from . import actions, db, discovery, netinfo


def _is_placeholder_mac(mac: Any) -> bool:
    return str(mac or "").lower().startswith("ip-")


class Monitor:
    def __init__(self, scan_runner: Callable[[str], None], is_scanning: Callable[[], bool]) -> None:
        self.scan_runner = scan_runner
        self.is_scanning = is_scanning
        self.samples: deque[dict[str, Any]] = deque(maxlen=200)
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.iface = netinfo.primary_interface().get("name", "")
        self.prev_counters: tuple[int, int, float] | None = None
        self.last_rx = 0.0
        self.last_tx = 0.0
        self.rx_total = 0
        self.tx_total = 0
        self.internet = True
        self.accum: list[tuple[float, float]] = []
        self.last_db_flush = time.time()
        self.last_presence = 0.0
        self.last_enforce = 0.0
        self.last_connectivity = 0.0
        self.last_scan_check = time.time()
        self.last_prune = time.time()
        self.blocked_state: dict[str, bool] = {}
        self.blocked_ip: dict[str, str] = {}
        # Gecikme ölçümü (modem ↔ internet) — 10 sn'lik örnekler, ~70 dk bellekte
        self.latency: deque[dict[str, Any]] = deque(maxlen=420)
        self.lat_accum: list[tuple[float | None, float | None]] = []
        self.last_latency = 0.0
        # Kesinti takibi
        self.fail_count = 0
        self.first_fail_iso: str | None = None
        self.outage_id: int | None = None
        self.outage_cause = "unknown"
        self._started = False
        atexit.register(self.cleanup)

    # ------------------------------------------------------------------ #
    # Yaşam döngüsü
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        if self._started:
            return
        self._started = True
        try:
            actions.firewall_cleanup_all()
        except Exception:
            pass
        try:
            # Önceki çalışmada kesinti sürerken kapatıldıysa, kaydı son canlılık anında kapat
            heartbeat = db.get_setting("_heartbeat", "") or db.iso()
            db.close_open_outages(heartbeat)
        except Exception:
            pass
        self.thread = threading.Thread(target=self._loop, name="netmagic-monitor", daemon=True)
        self.thread.start()

    def cleanup(self) -> None:
        try:
            actions.firewall_cleanup_all()
        except Exception:
            pass

    def stop(self) -> None:
        self.stop_event.set()
        self.cleanup()

    def record_block(self, mac: str, ip: str | None, blocked: bool | None) -> None:
        """Güvenlik duvarında uygulanan son durumu (ve kuralın IP'sini) hatırlar."""
        if blocked is None:
            self.blocked_state.pop(mac, None)
            self.blocked_ip.pop(mac, None)
            return
        self.blocked_state[mac] = blocked
        if blocked and ip:
            self.blocked_ip[mac] = ip
        else:
            self.blocked_ip.pop(mac, None)

    def forget_all(self) -> None:
        self.blocked_state.clear()
        self.blocked_ip.clear()

    # ------------------------------------------------------------------ #
    # Örnekleme
    # ------------------------------------------------------------------ #
    def _sample_traffic(self) -> None:
        try:
            if not self.iface or self.iface not in psutil.net_io_counters(pernic=True):
                self.iface = netinfo.primary_interface().get("name", "")
            counters = psutil.net_io_counters(pernic=True).get(self.iface)
            if not counters:
                return
            now = time.time()
            self.rx_total, self.tx_total = counters.bytes_recv, counters.bytes_sent
            if self.prev_counters:
                prev_rx, prev_tx, prev_time = self.prev_counters
                delta = max(0.2, now - prev_time)
                # *_bps alanları bit/saniyedir (arayüz Mb/s gösterir, rapor /8 ile bayta çevirir)
                self.last_rx = max(0.0, (counters.bytes_recv - prev_rx) * 8 / delta)
                self.last_tx = max(0.0, (counters.bytes_sent - prev_tx) * 8 / delta)
                with self.lock:
                    self.samples.append(
                        {
                            "ts": db.iso(),
                            "rx_bps": round(self.last_rx, 1),
                            "tx_bps": round(self.last_tx, 1),
                        }
                    )
                    self.accum.append((self.last_rx, self.last_tx))
            self.prev_counters = (counters.bytes_recv, counters.bytes_sent, now)
        except Exception:
            pass

    def _flush_traffic(self) -> None:
        if not self.accum:
            return
        with self.lock:
            values = self.accum[:]
            self.accum.clear()
        rx = sum(v[0] for v in values) / len(values)
        tx = sum(v[1] for v in values) / len(values)
        db.add_traffic(rx, tx)
        self._flush_latency()
        db.set_setting("_heartbeat", db.iso())
        self.last_db_flush = time.time()

    def _flush_latency(self) -> None:
        with self.lock:
            values = self.lat_accum[:]
            self.lat_accum.clear()
        if not values:
            return
        gw = [g for g, _ in values if g is not None]
        inet = [i for _, i in values if i is not None]
        db.add_latency(
            round(sum(gw) / len(gw), 1) if gw else None,
            round(sum(inet) / len(inet), 1) if inet else None,
            100 * (1 - len(gw) / len(values)),
            100 * (1 - len(inet) / len(values)),
        )

    # ------------------------------------------------------------------ #
    # Gecikme: modeme (yerel ağ/Wi-Fi) ve internete (sağlayıcı) ayrı ayrı
    # ------------------------------------------------------------------ #
    def _latency_sample(self) -> None:
        self.last_latency = time.time()
        gw_ip = netinfo.default_gateway()
        gw = discovery.ping_rtt(gw_ip, 800) if gw_ip else None
        inet = discovery.ping_rtt("1.1.1.1", 1000)
        if inet is None:
            # Bazı ağlar ICMP'yi engeller: TCP bağlantı süresiyle yedekle
            inet = discovery.tcp_rtt("1.1.1.1", 443, 1.5)
        sample = {"ts": db.iso(), "gw_ms": gw, "inet_ms": inet}
        with self.lock:
            self.latency.append(sample)
            self.lat_accum.append((gw, inet))

    def latency_samples(self, minutes: int = 60) -> list[dict[str, Any]]:
        cutoff = db.iso(db.utcnow() - timedelta(minutes=minutes))
        with self.lock:
            return [s for s in self.latency if s["ts"] >= cutoff]

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            samples = list(self.samples)
            last_lat = self.latency[-1] if self.latency else {}
        return {
            "latency": {"gw_ms": last_lat.get("gw_ms"), "inet_ms": last_lat.get("inet_ms"), "ts": last_lat.get("ts")},
            "outage": {"ongoing": self.outage_id is not None, "since": self.first_fail_iso if self.outage_id else None, "cause": self.outage_cause if self.outage_id else None},
            "rx_bps": round(self.last_rx, 1),
            "tx_bps": round(self.last_tx, 1),
            "rx_total": self.rx_total,
            "tx_total": self.tx_total,
            "samples": samples,
            "internet": self.internet,
            "iface": self.iface,
        }

    # ------------------------------------------------------------------ #
    # Varlık kontrolü
    # ------------------------------------------------------------------ #
    def _presence_check(self) -> None:
        devices = [d for d in db.list_devices() if d.get("ip") and not _is_placeholder_mac(d.get("mac"))]
        if not devices:
            return

        def check(device: dict[str, Any]) -> tuple[dict[str, Any], bool]:
            if discovery.ping_host(device["ip"], timeout_ms=500):
                return device, True
            # ICMP'ye yanıt vermeyen cihazlar (ör. iPhone, güvenlik duvarlı PC) için
            # taramada bulunan açık portlardan birine TCP ile dokun.
            for entry in (device.get("open_ports") or [])[:3]:
                port = entry.get("port") if isinstance(entry, dict) else entry
                try:
                    with socket.create_connection((device["ip"], int(port)), timeout=0.6):
                        return device, True
                except (OSError, ValueError, TypeError):
                    continue
            return device, False

        with ThreadPoolExecutor(max_workers=min(24, len(devices))) as pool:
            for device, online in pool.map(check, devices[:150]):
                db.set_online(device["mac"], online)
        self.last_presence = time.time()

    # ------------------------------------------------------------------ #
    # Ebeveyn kontrolü / engelleme
    # ------------------------------------------------------------------ #
    @staticmethod
    def _schedule_allows(device: dict[str, Any], now: datetime) -> bool:
        schedule = device.get("schedule")
        if not schedule:
            return True
        day = str(now.weekday())
        hours = schedule.get(day)
        if hours is None:
            return True
        return now.hour in hours

    def _desired_block(self, device: dict[str, Any], now: datetime) -> bool:
        if device.get("is_self"):
            return False
        if device.get("blocked"):
            return True
        pause = device.get("pause_until")
        if pause:
            try:
                if datetime.fromisoformat(pause) > now:
                    return True
            except ValueError:
                pass
        return not self._schedule_allows(device, now)

    def enforce_rules(self, force: bool = False) -> list[dict[str, Any]]:
        if not actions.is_admin():
            return []
        now = datetime.now().astimezone()
        changes: list[dict[str, Any]] = []
        for device in db.list_devices():
            if not device.get("ip") or _is_placeholder_mac(device.get("mac")):
                continue
            if device.get("is_self") or device["ip"] == netinfo.default_gateway():
                continue
            desired = self._desired_block(device, now)
            current = self.blocked_state.get(device["mac"])
            # Engelli cihaz DHCP'den yeni IP aldıysa kuralı yeni IP ile yeniden yaz
            ip_changed = bool(
                desired
                and current
                and self.blocked_ip.get(device["mac"]) not in (None, device["ip"])
            )
            if force or current is None or desired != current or ip_changed:
                result = actions.firewall_set_block(device["mac"], device["ip"], desired)
                if result["ok"]:
                    self.record_block(device["mac"], device["ip"], desired)
                    changes.append(
                        {
                            "mac": device["mac"],
                            "name": device.get("display_name"),
                            "blocked": desired,
                        }
                    )
                    if desired and current is not True:
                        reason = "Ebeveyn kontrolü" if not device.get("blocked") else "Kullanıcı isteği"
                        db.add_alert(
                            "parental" if not device.get("blocked") else "security",
                            "warning",
                            f"{device.get('display_name')} için yerel erişim kısıtlandı",
                            f"{reason} nedeniyle cihazın bu bilgisayarla iletişimi engellendi.",
                            device["mac"],
                            dedupe_minutes=10,
                        )
                else:
                    db.add_alert(
                        "system",
                        "warning",
                        "Engelleme uygulanamadı",
                        result["message"],
                        device["mac"],
                        dedupe_minutes=30,
                    )
            # Süresi dolan molaları temizle
            pause = device.get("pause_until")
            if pause:
                try:
                    if datetime.fromisoformat(pause) <= now and not device.get("blocked"):
                        db.update_device(device["id"], {"pause_until": None})
                except ValueError:
                    pass
        self.last_enforce = time.time()
        return changes

    # ------------------------------------------------------------------ #
    # İnternet kontrolü
    # ------------------------------------------------------------------ #
    @staticmethod
    def _internet_reachable() -> bool:
        # Yalnızca internetteki hedefler: ağ geçidine ulaşmak internetin olduğu anlamına gelmez.
        for target in (("1.1.1.1", 443), ("8.8.8.8", 53), ("9.9.9.9", 443)):
            try:
                with socket.create_connection(target, timeout=2):
                    return True
            except OSError:
                continue
        return False

    def _connectivity_check(self) -> None:
        """İnterneti 15 sn'de bir yoklar. Tek bir başarısızlık kesinti sayılmaz: art arda
        2 başarısız denemede (≈5 sn arayla) kesinti başlatılır; başlangıç zamanı ilk hatadır.
        Kesinti sırasında modeme ulaşılabiliyorsa sebep servis sağlayıcı, ulaşılamıyorsa
        yerel ağ / Wi-Fi olarak kaydedilir."""
        self.last_connectivity = time.time()
        if self._internet_reachable():
            self.fail_count = 0
            self.first_fail_iso = None
            if self.outage_id is not None:
                outage_id, cause = self.outage_id, self.outage_cause
                self.outage_id = None
                db.end_outage(outage_id)
                duration = _fmt_duration(self._outage_seconds(outage_id))
                where = {"isp": "Servis sağlayıcı kaynaklı", "local": "Yerel ağ / Wi-Fi kaynaklı"}.get(cause, "")
                db.add_alert(
                    "system", "info", "İnternet bağlantısı geri geldi",
                    f"Kesinti {duration} sürdü.{(' ' + where + '.') if where else ''}",
                )
            self.internet = True
            return

        self.fail_count += 1
        if self.fail_count == 1:
            self.first_fail_iso = db.iso()
            return  # ~5 sn sonra tekrar denenecek
        if self.outage_id is None:
            gw_ip = netinfo.default_gateway()
            gw_ok = bool(gw_ip) and discovery.ping_rtt(gw_ip, 800) is not None
            self.outage_cause = "isp" if gw_ok else "local"
            self.outage_id = db.start_outage(self.first_fail_iso or db.iso(), self.outage_cause)
            self.internet = False
            if gw_ok:
                msg = "Modeme ulaşılabiliyor ama internete çıkılamıyor: sorun büyük olasılıkla servis sağlayıcıda."
            else:
                msg = "Modeme de ulaşılamıyor: Wi-Fi bağlantısını, kabloyu veya modemin açık olduğunu kontrol edin."
            db.add_alert("system", "critical", "İnternet bağlantısı kesildi", msg)

    @staticmethod
    def _outage_seconds(outage_id: int) -> int:
        try:
            for o in db.outage_report(2)["outages"]:
                if o["id"] == outage_id:
                    return o["duration_s"]
        except Exception:
            pass
        return 0

    # ------------------------------------------------------------------ #
    # Ana döngü
    # ------------------------------------------------------------------ #
    def _loop(self) -> None:
        time.sleep(1.0)
        while not self.stop_event.is_set():
            try:
                self._sample_traffic()
                now = time.time()
                if now - self.last_db_flush >= 60:
                    self._flush_traffic()
                if now - self.last_presence >= 75 and not self.is_scanning():
                    self._presence_check()
                if now - self.last_enforce >= 30:
                    self.enforce_rules()
                # Normalde 15 sn; şüpheli bir hatadan sonra veya kesinti sürerken 5 sn
                conn_interval = 5 if self.fail_count else 15
                if now - self.last_connectivity >= conn_interval:
                    self._connectivity_check()
                if now - self.last_latency >= 10:
                    self._latency_sample()
                if now - self.last_scan_check >= 30:
                    self._scan_check()
                if now - self.last_prune >= 3600:
                    db.prune()
                    try:
                        netinfo.invalidate_caches()
                        self.iface = netinfo.primary_interface().get("name", "")
                    except Exception:
                        pass
                    self.last_prune = now
            except Exception:
                pass
            self.stop_event.wait(3.0)

    def _scan_check(self) -> None:
        self.last_scan_check = time.time()
        settings = db.get_settings()
        if settings.get("auto_scan") != "1":
            return
        if settings.get("onboarded") != "1":
            return
        if self.is_scanning():
            return
        try:
            interval = max(2, int(settings.get("scan_interval_minutes", "10")))
        except ValueError:
            interval = 10
        history = db.scan_history(1)
        if not history:
            # İlk tarama kullanıcı tarafından başlatılmalı.
            return
        try:
            last = datetime.fromisoformat(history[0]["started"]).timestamp()
        except (ValueError, TypeError, KeyError):
            return
        if time.time() - last >= interval * 60:
            self.scan_runner("auto")


def _fmt_duration(seconds: int) -> str:
    seconds = int(seconds or 0)
    if seconds < 60:
        return f"{seconds} sn"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} dk" + (f" {sec} sn" if sec and minutes < 10 else "")
    hours, minutes = divmod(minutes, 60)
    return f"{hours} sa {minutes} dk"


def summarize_latency(values: list[float | None]) -> dict[str, Any]:
    """Ortalama, p95, titreşim (jitter) ve kayıp yüzdesi."""
    total = len(values)
    ok = sorted(v for v in values if v is not None)
    if not total:
        return {"avg": None, "p95": None, "jitter": None, "loss": None, "count": 0}
    if not ok:
        return {"avg": None, "p95": None, "jitter": None, "loss": 100.0, "count": total}
    avg = sum(ok) / len(ok)
    p95 = ok[min(len(ok) - 1, int(round(0.95 * (len(ok) - 1))))]
    seq = [v for v in values if v is not None]
    jitter = sum(abs(a - b) for a, b in zip(seq, seq[1:])) / (len(seq) - 1) if len(seq) > 1 else 0.0
    return {
        "avg": round(avg, 1),
        "p95": round(p95, 1),
        "jitter": round(jitter, 1),
        "loss": round(100 * (1 - len(ok) / total), 1),
        "count": total,
    }


def latency_verdict(gw: dict[str, Any], inet: dict[str, Any]) -> dict[str, str]:
    """Modem ve internet gecikmesini karşılaştırarak sorunun nerede olduğunu söyler."""
    if (gw.get("count") or 0) < 3 and (inet.get("count") or 0) < 3:
        return {"code": "measuring", "title": "Ölçülüyor", "text": "Birkaç ölçüm daha toplanıyor…"}
    g_avg, g_p95, g_loss = gw.get("avg"), gw.get("p95"), gw.get("loss") or 0
    i_avg, i_p95, i_loss = inet.get("avg"), inet.get("p95"), inet.get("loss") or 0

    if g_loss >= 100 and (i_loss or 0) >= 100:
        return {"code": "down", "title": "Bağlantı yok",
                "text": "Ne modeme ne internete ulaşılabiliyor. Wi-Fi bağlantısını veya kabloyu kontrol edin."}
    local_bad = g_loss > 5 or (g_avg is not None and g_avg > 30) or (g_p95 is not None and g_p95 > 80)
    if local_bad:
        detail = f"Modeme gecikme ortalama {g_avg:g} ms" if g_avg is not None else "Modem yanıt vermiyor"
        return {"code": "local", "title": "Sorun Wi-Fi / yerel ağda",
                "text": f"{detail}, kayıp %{g_loss:g}. Modeme yaklaşmayı, 5 GHz ağı kullanmayı veya "
                        "Wi-Fi kanalını değiştirmeyi deneyin. Kablolu bağlantıda kabloyu kontrol edin."}
    isp_bad = i_loss > 3 or (i_avg is not None and i_avg > 100) or (i_p95 is not None and i_p95 > 200)
    if isp_bad:
        g_txt = f"{g_avg:g} ms" if g_avg is not None else "—"
        i_txt = f"{i_avg:g} ms" if i_avg is not None else "yanıt yok"
        return {"code": "isp", "title": "Sorun servis sağlayıcıda",
                "text": f"Modeme bağlantınız iyi ({g_txt}) ama internete gecikme {i_txt}, kayıp %{i_loss:g}. "
                        "Sorun sürerse servis sağlayıcınızla iletişime geçin."}
    g_txt = f"{g_avg:g} ms" if g_avg is not None else "—"
    i_txt = f"{i_avg:g} ms" if i_avg is not None else "—"
    return {"code": "ok", "title": "Bağlantı sağlıklı",
            "text": f"Modem {g_txt}, internet {i_txt}. Hem yerel ağınız hem servis sağlayıcınız normal çalışıyor."}
