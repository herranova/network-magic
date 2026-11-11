"""Network Magic çekirdek birim testleri.

Çalıştırma:
    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

# Testler gerçek veritabanına dokunmasın diye geçici veri klasörü kullan.
_TMP = tempfile.mkdtemp(prefix="netmagic-test-")
os.environ["NETMAGIC_DATA"] = _TMP

from netmagic import actions, config, db, discovery, netinfo  # noqa: E402


class TestMacAndNetworkHelpers(unittest.TestCase):
    def test_normalize_mac(self):
        self.assertEqual(netinfo.normalize_mac("aa-bb-cc-dd-ee-ff"), "AA:BB:CC:DD:EE:FF")
        self.assertEqual(netinfo.normalize_mac("aabb.ccdd.eeff"), "AA:BB:CC:DD:EE:FF")
        # Geçersiz uzunluk olduğu gibi (büyük harfle) döner
        self.assertEqual(netinfo.normalize_mac("abc"), "ABC")

    def test_mask_to_prefix(self):
        self.assertEqual(netinfo.mask_to_prefix("255.255.255.0"), 24)
        self.assertEqual(netinfo.mask_to_prefix("255.255.0.0"), 16)
        self.assertEqual(netinfo.mask_to_prefix("bozuk"), 24)

    def test_hosts_in_subnet(self):
        hosts = discovery.hosts_in_subnet("192.168.1.10", 24)
        self.assertEqual(len(hosts), 254)
        self.assertIn("192.168.1.1", hosts)
        self.assertIn("192.168.1.254", hosts)
        self.assertNotIn("192.168.1.0", hosts)
        self.assertNotIn("192.168.1.255", hosts)
        # 127.0.0.1 (loopback) asla taranmamalı
        self.assertEqual(discovery.hosts_in_subnet("127.0.0.1", 24), [])

    def test_hosts_in_subnet_limits_huge_network(self):
        hosts = discovery.hosts_in_subnet("10.0.0.5", 8)
        self.assertTrue(hosts)
        self.assertTrue(all(ip.startswith("10.0.0.") for ip in hosts))

    def test_parse_subnet_override(self):
        self.assertEqual(len(discovery.parse_subnet_override("192.168.0.0/24")), 254)
        self.assertEqual(discovery.parse_subnet_override("bozuk"), [])
        self.assertEqual(discovery.parse_subnet_override("10.0.0.0/8"), [])

    def test_is_random_mac(self):
        self.assertTrue(discovery._is_random_mac("DA:A1:19:00:00:01"))
        self.assertFalse(discovery._is_random_mac("3C:5A:37:11:22:33"))
        self.assertFalse(discovery._is_random_mac("ip-192.168.1.4"))


class TestDeviceTypeGuess(unittest.TestCase):
    def test_gateway_is_router(self):
        self.assertEqual(
            discovery.guess_type("192.168.1.1", "192.168.1.1", "", "", [80], []),
            "router",
        )

    def test_self_is_computer(self):
        self.assertEqual(
            discovery.guess_type("192.168.1.5", "192.168.1.1", "", "MSI", [], [], is_self=True),
            "computer",
        )

    def test_printer_by_port(self):
        self.assertEqual(
            discovery.guess_type("192.168.1.20", "192.168.1.1", "", "", [9100], []),
            "printer",
        )

    def test_camera_by_vendor(self):
        self.assertEqual(
            discovery.guess_type("192.168.1.21", "192.168.1.1", "Shanghai Imilab", "", [], []),
            "camera",
        )

    def test_unknown_stays_unknown(self):
        self.assertEqual(
            discovery.guess_type("192.168.1.22", "192.168.1.1", "", "", [], []),
            "unknown",
        )

    def test_tv_by_chromecast(self):
        self.assertEqual(
            discovery.guess_type("192.168.1.23", "192.168.1.1", "", "", [8009], []),
            "tv",
        )

    def test_vendor_cleanup(self):
        self.assertEqual(discovery._clean_vendor("Apple, Inc."), "Apple")
        self.assertEqual(discovery._clean_vendor("TP-LINK TECHNOLOGIES CO.,LTD."), "TP-Link")
        self.assertEqual(discovery._clean_vendor(""), "")


class TestNameParsing(unittest.TestCase):
    def test_read_dns_name(self):
        packet = b"\x03nas\x05local\x00"
        name, offset = discovery._read_name(packet, 0)
        self.assertEqual(name, "nas.local")
        self.assertEqual(offset, len(packet))

    def test_read_dns_name_with_pointer(self):
        packet = b"\x03nas\x05local\x00" + b"\xc0\x00"
        name, offset = discovery._read_name(packet, len(packet) - 2)
        self.assertEqual(name, "nas.local")
        self.assertEqual(offset, len(packet))

    def test_clean_instance(self):
        self.assertEqual(discovery._clean_instance("Deniz\\032s MacBook"), "Deniz s MacBook")
        self.assertEqual(discovery._clean_instance("Yazici"), "Yazici")


class TestFileSafety(unittest.TestCase):
    def test_safe_filename_strips_paths(self):
        self.assertEqual(actions.safe_filename("../../etc/passwd"), "passwd")
        self.assertEqual(actions.safe_filename("C:\\Windows\\notepad.exe"), "notepad.exe")

    def test_safe_filename_replaces_invalid_chars(self):
        self.assertEqual(actions.safe_filename('rapor<01>.txt'), "rapor_01_.txt")
        self.assertEqual(actions.safe_filename("   "), "dosya")

    def test_safe_filename_keeps_extension_when_truncating(self):
        name = actions.safe_filename("a" * 200 + ".pdf")
        self.assertLessEqual(len(name), 120)
        self.assertTrue(name.endswith(".pdf"))

    def test_qr_data_uri(self):
        uri = actions.qr_data_uri("http://192.168.1.5:8765/guest/test")
        self.assertTrue(uri.startswith("data:image/svg+xml;base64,"))


class TestDatabase(unittest.TestCase):
    def setUp(self):
        config.DATA_DIR = Path(_TMP)
        config.SHARE_DIR = Path(_TMP) / "share"
        config.DB_PATH = Path(_TMP) / "test.db"
        db.init_db()
        db.clear_devices()

    def test_baseline_scan_marks_trusted_and_detects_new(self):
        devices = [
            {"mac": "AA:BB:CC:DD:EE:01", "ip": "192.168.1.10", "vendor": "Test", "type": "phone", "is_self": False},
            {"mac": "AA:BB:CC:DD:EE:02", "ip": "192.168.1.11", "vendor": "Test", "type": "tv", "is_self": False},
        ]
        new = db.upsert_scan(devices, baseline=True)
        self.assertEqual(len(new), 2)
        stored = db.list_devices()
        self.assertEqual(len(stored), 2)
        self.assertTrue(all(d["trusted"] for d in stored))

        extra = {"mac": "AA:BB:CC:DD:EE:03", "ip": "192.168.1.12", "vendor": "", "type": "unknown", "is_self": False}
        new2 = db.upsert_scan([extra], baseline=False)
        self.assertEqual(len(new2), 1)
        self.assertEqual(new2[0]["mac"], "AA:BB:CC:DD:EE:03")
        untrusted = [d for d in db.list_devices() if not d["trusted"]]
        self.assertEqual(len(untrusted), 1)

    def test_update_and_alerts(self):
        db.upsert_scan([{"mac": "AA:BB:CC:DD:EE:04", "ip": "192.168.1.13", "type": "computer", "is_self": False}], baseline=True)
        device = db.list_devices()[0]
        updated = db.update_device(device["id"], {"name": "Salon PC", "trusted": False, "notes": "deneme"})
        self.assertEqual(updated["name"], "Salon PC")
        self.assertFalse(updated["trusted"])
        alert_id = db.add_alert("security", "warning", "Test uyarısı", "mesaj", device["mac"])
        self.assertGreater(alert_id, 0)
        self.assertEqual(db.unread_alert_count(), 1)
        db.mark_alerts_read([alert_id])
        self.assertEqual(db.unread_alert_count(), 0)

    def test_mark_offline_except(self):
        db.upsert_scan(
            [
                {"mac": "AA:BB:CC:DD:EE:05", "ip": "192.168.1.14", "type": "phone", "is_self": False},
                {"mac": "AA:BB:CC:DD:EE:06", "ip": "192.168.1.15", "type": "phone", "is_self": False},
            ],
            baseline=True,
        )
        db.mark_offline_except({"AA:BB:CC:DD:EE:05"})
        online = {d["mac"]: d["online"] for d in db.list_devices()}
        self.assertTrue(online["AA:BB:CC:DD:EE:05"])
        self.assertFalse(online["AA:BB:CC:DD:EE:06"])

    def test_ping_device_invalid_ip(self):
        res = actions.ping_device("invalid.ip")
        self.assertFalse(res["ok"])
        self.assertEqual(res["loss_pct"], 100)

    def test_wake_on_lan_validation(self):
        # Geçersiz MAC
        res = actions.wake_on_lan("123")
        self.assertFalse(res["ok"])
        # Geçerli MAC
        res = actions.wake_on_lan("90:DE:80:D6:8F:3F")
        self.assertTrue(res["ok"])
        self.assertIn("Magic Packet", res["message"])

    def test_wifi_channel_analysis(self):
        analysis = netinfo.wifi_channel_analysis()
        self.assertIn("best_24", analysis)
        self.assertIn("best_5", analysis)
        self.assertIn("recommendation", analysis)
        self.assertIn("channels_24", analysis)

    def test_parse_wifi_networks_bssid(self):
        sample = """Interface name : Wi-Fi
There are 2 networks currently visible.

SSID 1 :
    Network type            : Infrastructure
    Authentication          : WPA2-Personal
    Encryption              : CCMP
    BSSID 1                 : fa:79:28:90:b2:ad
         Signal             : 5%
         Radio type         : 802.11ax
         Band               : 5 GHz
         Channel            : 128
    BSSID 2                 : 26:c0:13:4f:3d:6e
         Signal             : 40%
         Radio type         : 802.11ax
         Band               : 2.4 GHz
         Channel            : 6
         Bss Load:
             Connected Stations:         0
             Channel Utilization:        6 (2 %)
             Medium Available Capacity:  31250 (1000000 us/s)

SSID 2 : Komsu
    Network type            : Infrastructure
    Authentication          : WPA3-Personal
    Encryption              : CCMP
"""
        nets = netinfo.parse_wifi_networks(sample)
        self.assertEqual(len(nets), 2)
        hidden = next(n for n in nets if n["ssid"] == "")
        self.assertEqual(hidden["bssids"], 2)
        # Kanal/sinyal en güçlü yayın noktasından alınmalı; "Channel Utilization" sinyal sanılmamalı
        self.assertEqual(hidden["signal"], 40)
        self.assertEqual(hidden["channel"], "6")
        self.assertEqual(hidden["band"], "2.4 GHz")
        self.assertEqual(hidden["bands"], ["2.4 GHz", "5 GHz"])
        komsu = next(n for n in nets if n["ssid"] == "Komsu")
        self.assertEqual(komsu["auth"], "WPA3-Personal")
        self.assertEqual(komsu["access_points"], [])


class TestDeviceIdentification(unittest.TestCase):
    def test_ptr_name_roundtrip(self):
        self.assertEqual(discovery.reverse_ptr_name("192.168.1.30"), "30.1.168.192.in-addr.arpa")
        self.assertEqual(discovery.ip_from_ptr_name("30.1.168.192.in-addr.arpa"), "192.168.1.30")
        self.assertEqual(discovery.ip_from_ptr_name("30.1.168.192.in-addr.arpa."), "192.168.1.30")
        self.assertEqual(discovery.ip_from_ptr_name("_http._tcp.local"), "")
        self.assertEqual(discovery.ip_from_ptr_name("999.1.168.192.in-addr.arpa"), "")

    def test_clean_hostname(self):
        self.assertEqual(discovery._clean_hostname("Android_B8PDKN3Q.local"), "Android_B8PDKN3Q")
        self.assertEqual(discovery._clean_hostname("Salon\\032TV.local."), "Salon TV")

    def test_mdns_reverse_response_parsing(self):
        import struct
        # 30.1.168.192.in-addr.arpa PTR -> Android_B8PDKN3Q.local yanıtı
        name = discovery._encode_name("30.1.168.192.in-addr.arpa")
        target = discovery._encode_name("Android_B8PDKN3Q.local")
        packet = struct.pack(">HHHHHH", 0, 0x8400, 0, 1, 0, 0) + name + struct.pack(">HHIH", 12, 1, 120, len(target)) + target
        parsed = discovery._parse_dns(packet)
        self.assertEqual(parsed["ptr"], [("30.1.168.192.in-addr.arpa", "Android_B8PDKN3Q.local")])

    def test_parse_nbstat(self):
        import struct
        def entry(name, suffix, flags):
            return name.ljust(15).encode("ascii") + bytes([suffix]) + struct.pack(">H", flags)
        rdata = bytes([3]) + entry("WORKGROUP", 0x00, 0x8400) + entry("SALON-PC", 0x20, 0x0400) + entry("SALON-PC", 0x00, 0x0400)
        rdata += b"\x00" * 6  # MAC
        packet = (
            b"\x13\x37\x84\x00\x00\x00\x00\x01\x00\x00\x00\x00"
            + b"\x20" + b"CKAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" + b"\x00"
            + struct.pack(">HHIH", 0x21, 1, 0, len(rdata)) + rdata
        )
        # Grup adı (WORKGROUP) atlanmalı, sonek 0x00'lı benzersiz ad seçilmeli
        self.assertEqual(discovery.parse_nbstat(packet), "SALON-PC")
        self.assertEqual(discovery.parse_nbstat(b"\x00" * 20), "")

    def test_nbstat_query_encodes_wildcard(self):
        self.assertEqual(len(discovery._NBSTAT_QUERY), 50)
        self.assertIn(b"CKAAAA", discovery._NBSTAT_QUERY)

    def test_clean_web_title(self):
        self.assertEqual(discovery.clean_web_title("  Tapo C200 &amp; Kamera "), "Tapo C200 & Kamera")
        self.assertEqual(discovery.clean_web_title("Login"), "")
        self.assertEqual(discovery.clean_web_title("192.168.1.1"), "")
        self.assertEqual(discovery.clean_web_title("404 Not Found"), "")

    def test_random_mac_without_services_is_phone(self):
        self.assertEqual(discovery.guess_type("192.168.1.30", "192.168.1.1", "Rastgele MAC", "", [], []), "phone")
        # Rastgele MAC'li ama SMB açık bir cihaz bilgisayardır
        self.assertEqual(discovery.guess_type("192.168.1.31", "192.168.1.1", "Rastgele MAC", "", [445], []), "computer")

    def test_parse_ping_rtt(self):
        self.assertEqual(discovery.parse_ping_rtt(b"Reply from 1.1.1.1: bytes=32 time=20ms TTL=59"), 20.0)
        self.assertEqual(discovery.parse_ping_rtt(b"Reply from 192.168.1.1: bytes=32 time<1ms TTL=64"), 1.0)
        self.assertEqual(discovery.parse_ping_rtt("1.1.1.1 yanıtı: bayt=32 süre=14ms TTL=57".encode("cp857")), 14.0)
        self.assertIsNone(discovery.parse_ping_rtt(b"Request timed out."))


class TestRandomMacMerging(unittest.TestCase):
    def setUp(self):
        db.clear_devices()

    def test_auto_merge_same_hostname_new_random_mac(self):
        old = {"mac": "DA:11:22:33:44:55", "ip": "192.168.1.30", "hostname": "Android_B8PDKN3Q", "type": "phone"}
        db.upsert_scan([old], baseline=True)
        dev = db.get_device_by_mac("DA:11:22:33:44:55")
        db.update_device(dev["id"], {"name": "Ayşe'nin telefonu", "trusted": True})
        merged: list = []
        new = db.upsert_scan(
            [{"mac": "6E:AA:BB:CC:DD:EE", "ip": "192.168.1.41", "hostname": "Android_B8PDKN3Q", "type": "phone"}],
            baseline=False, merged=merged,
        )
        self.assertEqual(new, [], "aynı ada sahip rastgele-MAC cihaz yeni sayılmamalı")
        self.assertEqual(len(merged), 1)
        devices = db.list_devices()
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["mac"], "6E:AA:BB:CC:DD:EE")
        self.assertEqual(devices[0]["name"], "Ayşe'nin telefonu")
        self.assertTrue(devices[0]["trusted"])

    def test_no_auto_merge_for_universal_mac_or_present_device(self):
        db.upsert_scan([{"mac": "DA:11:22:33:44:55", "ip": "192.168.1.30", "hostname": "Telefon"}], baseline=True)
        # Eski kayıt bu taramada da görünüyorsa iki ayrı cihazdır
        new = db.upsert_scan([
            {"mac": "DA:11:22:33:44:55", "ip": "192.168.1.30", "hostname": "Telefon"},
            {"mac": "6E:AA:BB:CC:DD:EE", "ip": "192.168.1.41", "hostname": "Telefon"},
        ], baseline=False)
        self.assertEqual(len(new), 1)
        # Evrensel (üretici) MAC'ler hiçbir zaman otomatik eşleştirilmez
        new2 = db.upsert_scan([{"mac": "90:DE:80:11:22:33", "ip": "192.168.1.42", "hostname": "Telefon"}], baseline=False)
        self.assertEqual(len(new2), 1)

    def test_manual_merge_keeps_target_settings(self):
        db.upsert_scan([
            {"mac": "DA:11:22:33:44:55", "ip": "192.168.1.30", "hostname": ""},
            {"mac": "6E:AA:BB:CC:DD:EE", "ip": "192.168.1.41", "hostname": "Android_X"},
        ], baseline=True)
        old = db.get_device_by_mac("DA:11:22:33:44:55")
        new = db.get_device_by_mac("6E:AA:BB:CC:DD:EE")
        db.update_device(old["id"], {"name": "Ali'nin telefonu", "notes": "mavi kılıf", "schedule": {"0": [8, 9]}})
        result = db.merge_devices(new["id"], old["id"])
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], old["id"])
        self.assertEqual(result["name"], "Ali'nin telefonu")
        self.assertEqual(result["notes"], "mavi kılıf")
        self.assertEqual(result["schedule"], {"0": [8, 9]})
        self.assertEqual(result["ip"], "192.168.1.41")
        self.assertEqual(result["hostname"], "Android_X")
        self.assertIsNone(db.get_device(new["id"]))
        self.assertIsNone(db.merge_devices(old["id"], old["id"]))

    def test_manual_type_survives_scan(self):
        db.upsert_scan([{"mac": "AA:BB:CC:00:00:01", "ip": "192.168.1.50", "type": "phone"}], baseline=True)
        dev = db.get_device_by_mac("AA:BB:CC:00:00:01")
        db.update_device(dev["id"], {"type": "tv"})
        db.upsert_scan([{"mac": "AA:BB:CC:00:00:01", "ip": "192.168.1.50", "type": "phone"}])
        self.assertEqual(db.get_device(dev["id"])["type"], "tv")


class TestOutagesAndLatency(unittest.TestCase):
    def setUp(self):
        db.clear_devices()

    def test_outage_report(self):
        from datetime import timedelta
        now = db.utcnow()
        for minutes in range(0, 600):  # 10 saatlik izleme verisi
            db.add_traffic(0, 0, db.iso(now - timedelta(minutes=minutes)))
        oid = db.start_outage(db.iso(now - timedelta(hours=2)), "isp")
        db.end_outage(oid, db.iso(now - timedelta(hours=2) + timedelta(minutes=12)))
        db.start_outage(db.iso(now - timedelta(minutes=3)), "local")  # sürüyor
        rep = db.outage_report(7)
        s = rep["summary"]
        self.assertEqual(s["count"], 2)
        self.assertEqual(s["isp_count"], 1)
        self.assertEqual(s["local_count"], 1)
        self.assertTrue(s["ongoing"])
        self.assertGreaterEqual(s["longest_s"], 12 * 60)
        self.assertGreater(s["uptime_pct"], 96)
        self.assertLess(s["uptime_pct"], 100)
        self.assertEqual(len(rep["daily"]), 7)

    def test_close_open_outages_on_restart(self):
        from datetime import timedelta
        now = db.utcnow()
        db.start_outage(db.iso(now - timedelta(minutes=10)), "isp")
        self.assertEqual(db.close_open_outages(db.iso(now - timedelta(minutes=4))), 1)
        o = db.outage_report(1)["outages"][0]
        self.assertFalse(o["ongoing"])
        self.assertAlmostEqual(o["duration_s"], 360, delta=2)

    def test_latency_summary_and_verdict(self):
        from netmagic import monitor
        good_gw = monitor.summarize_latency([2, 3, 2, 4, 3, 2])
        good_inet = monitor.summarize_latency([18, 20, 22, 19, 21, 20])
        self.assertEqual(good_gw["loss"], 0)
        self.assertEqual(monitor.latency_verdict(good_gw, good_inet)["code"], "ok")
        # Modem iyi, internet kötü -> sağlayıcı
        bad_inet = monitor.summarize_latency([180, None, 220, 190, None, 200])
        self.assertEqual(monitor.latency_verdict(good_gw, bad_inet)["code"], "isp")
        # Modeme gecikme yüksek -> Wi-Fi / yerel
        bad_gw = monitor.summarize_latency([60, 85, None, 70, 90, 75])
        self.assertEqual(monitor.latency_verdict(bad_gw, bad_inet)["code"], "local")
        # Hiçbir şeye ulaşılamıyor
        dead = monitor.summarize_latency([None] * 6)
        self.assertEqual(monitor.latency_verdict(dead, dead)["code"], "down")
        self.assertEqual(monitor.latency_verdict(monitor.summarize_latency([]), monitor.summarize_latency([]))["code"], "measuring")


class TestRequestSecurity(unittest.TestCase):
    """Tarayıcı kaynaklı saldırılara (CSRF, DNS rebinding) ve ağdan sızıntıya karşı korumalar."""

    @classmethod
    def setUpClass(cls):
        import app as app_module

        cls.client = app_module.app.test_client()

    def test_foreign_host_header_rejected(self):
        # DNS rebinding: saldırganın alan adı 127.0.0.1'e çözülse bile Host başlığı ele verir
        res = self.client.get("/api/alerts", headers={"Host": "evil.example:8765"})
        self.assertEqual(res.status_code, 403)

    def test_ip_and_localhost_hosts_allowed(self):
        for host in ("127.0.0.1:8765", "localhost:8765", "192.168.1.20:8765", "[::1]:8765"):
            res = self.client.get("/api/alerts", headers={"Host": host})
            self.assertEqual(res.status_code, 200, host)

    def test_cross_origin_write_rejected(self):
        res = self.client.post(
            "/api/alerts/read",
            headers={"Host": "127.0.0.1:8765", "Origin": "http://evil.example"},
        )
        self.assertEqual(res.status_code, 403)
        res = self.client.post(
            "/api/alerts/read",
            headers={"Host": "127.0.0.1:8765", "Sec-Fetch-Site": "cross-site"},
        )
        self.assertEqual(res.status_code, 403)

    def test_same_origin_write_allowed(self):
        res = self.client.post(
            "/api/alerts/read",
            headers={"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765"},
        )
        self.assertEqual(res.status_code, 200)
        # Tarayıcı dışı istemciler (Origin yok) çalışmaya devam eder
        res = self.client.post("/api/alerts/read", headers={"Host": "127.0.0.1:8765"})
        self.assertEqual(res.status_code, 200)

    def test_guest_token_hidden_from_lan_clients(self):
        state = actions.set_guest_access(True, 1)
        self.assertTrue(state["token"])
        try:
            local = self.client.get("/api/guest").get_json()
            self.assertEqual(local["guest"]["token"], state["token"])
            self.assertIn(state["token"], local["link"])
            remote = {"REMOTE_ADDR": "203.0.113.9"}
            for path in ("/api/guest", "/api/share"):
                body = self.client.get(path, environ_base=remote).get_data(as_text=True)
                self.assertNotIn(state["token"], body, path)
        finally:
            actions.set_guest_access(False)

    def test_upnp_location_must_point_to_responder(self):
        ok = discovery.upnp_location_allowed
        self.assertTrue(ok("http://192.168.1.30:49152/desc.xml", "192.168.1.30"))
        self.assertFalse(ok("file:///C:/Windows/win.ini", "192.168.1.30"))
        self.assertFalse(ok("http://127.0.0.1:8765/api/status", "192.168.1.30"))
        self.assertFalse(ok("http://example.com/desc.xml", "192.168.1.30"))
        self.assertFalse(ok("", "192.168.1.30"))

    def test_notification_text_strips_control_chars(self):
        self.assertEqual(actions._notification_text("Ad\x00\r\n’; calc; ‘", 60), "Ad’; calc; ‘")
        self.assertEqual(len(actions._notification_text("x" * 500, 60)), 60)


if __name__ == "__main__":
    unittest.main(verbosity=2)
