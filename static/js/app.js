/* ==========================================================================
   Network Magic — ön uç mantığı
   ========================================================================== */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const TYPE_META = {
  router:   { symbol: "router",   label: "Yönlendirici",    color: "#3ddc97" },
  computer: { symbol: "computer", label: "Bilgisayar",      color: "#22d3ee" },
  laptop:   { symbol: "laptop",   label: "Dizüstü",         color: "#60a5fa" },
  phone:    { symbol: "phone",    label: "Telefon",         color: "#a78bfa" },
  tablet:   { symbol: "tablet",   label: "Tablet",          color: "#c084fc" },
  tv:       { symbol: "tv",       label: "Televizyon",      color: "#f472b6" },
  console:  { symbol: "console",  label: "Oyun Konsolu",    color: "#fb923c" },
  printer:  { symbol: "printer",  label: "Yazıcı",         color: "#fbbf24" },
  nas:      { symbol: "nas",      label: "NAS / Sunucu",   color: "#34d399" },
  camera:   { symbol: "camera",   label: "Kamera",          color: "#f87171" },
  speaker:  { symbol: "speaker",  label: "Akıllı Hoparlör", color: "#e879f9" },
  iot:      { symbol: "iot",      label: "Akıllı Ev",       color: "#94a3b8" },
  unknown:  { symbol: "unknown",  label: "Bilinmeyen",      color: "#64748b" },
};

function icon(name, cls = "ico") {
  return `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-${name}"></use></svg>`;
}

function typeIcon(type, cls = "type-icon") {
  return icon(typeMeta(type).symbol, cls);
}

const PAGE_META = {
  dashboard: ["Genel Bakış", "Ağınızın anlık durumu"],
  map: ["Ağ Haritası", "Cihazlarınızın görsel haritası"],
  devices: ["Cihazlar", "Ağınızdaki tüm cihazlar"],
  internet: ["İnternet & Hız", "Bağlantı kalitesi ve onarım"],
  share: ["Paylaşım", "Dosya ve misafir paylaşımı"],
  parental: ["Ebeveyn Kontrolü", "İnternet erişim planları"],
  alerts: ["Güvenlik & Uyarılar", "Ağ olayları"],
  settings: ["Ayarlar", "Network Magic yapılandırması"],
};

const state = {
  status: null,
  devices: [],
  alerts: [],
  counts: { total: 0, online: 0, untrusted: 0, restricted: 0, alerts: 0 },
  view: "dashboard",
  filter: "all",
  search: "",
  theme: "dark",
  mapFilter: "all",
  mapSearch: "",
  mapZoom: 1,
  mapPan: { x: 0, y: 0 },
  trafficRange: 0,
  trafficSamples: [],
  selectedId: null,
  scheduleDeviceId: null,
  schedule: null,
  speed: null,
  scanning: false,
  scanTimer: null,
  pollTimer: null,
  wifiLoaded: false,
  shareLoaded: false,
  lastScanRunning: false,
  latency: null,
  latencyRange: 60,
  latencyAt: 0,
  outages: null,
  outageRange: 30,
  outagesAt: 0,
};

/* -------------------------------------------------------------------------- */
/* Yardımcılar                                                                */
/* -------------------------------------------------------------------------- */
function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

async function api(url, options = {}) {
  const opts = { ...options, headers: { ...(options.headers || {}) } };
  if (opts.body && !(opts.body instanceof FormData)) {
    opts.headers["Content-Type"] = "application/json";
    if (typeof opts.body !== "string") opts.body = JSON.stringify(opts.body);
  }
  const res = await fetch(url, opts);
  let data = null;
  try { data = await res.json(); } catch { data = null; }
  if (!res.ok || (data && data.ok === false)) {
    const err = new Error((data && data.message) || `İşlem başarısız (${res.status})`);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data || { ok: true };
}

function typeMeta(type) {
  return TYPE_META[type] || TYPE_META.unknown;
}

function fmtBytes(bytes) {
  bytes = Number(bytes) || 0;
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes;
  let i = -1;
  do { value /= 1024; i++; } while (value >= 1024 && i < units.length - 1);
  return `${value.toFixed(value >= 100 ? 0 : value >= 10 ? 1 : 2)} ${units[i]}`;
}

function fmtRate(bps) {
  bps = Number(bps) || 0;
  if (bps >= 1e6) return `${(bps / 1e6).toFixed(2)} Mb/s`;
  if (bps >= 1e3) return `${(bps / 1e3).toFixed(0)} Kb/s`;
  return `${bps.toFixed(0)} b/s`;
}

function fmtMbps(bps) {
  return ((Number(bps) || 0) / 1e6).toFixed(1).replace(".0", "");
}

function relTime(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const diff = (Date.now() - date.getTime()) / 1000;
  if (diff < 10) return "az önce";
  if (diff < 60) return `${Math.floor(diff)} sn önce`;
  if (diff < 3600) return `${Math.floor(diff / 60)} dk önce`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} sa önce`;
  if (diff < 604800) return `${Math.floor(diff / 86400)} gün önce`;
  return date.toLocaleDateString("tr-TR");
}

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("tr-TR", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function fmtClock(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
}

function signalLevel(signal) {
  const s = Number(signal) || 0;
  if (s >= 75) return 4;
  if (s >= 50) return 3;
  if (s >= 25) return 2;
  if (s > 0) return 1;
  return 0;
}

function toast(title, message = "", type = "info", timeout = 4500) {
  const wrap = $("#toasts");
  const node = document.createElement("div");
  node.className = `toast ${type}`;
  const toastIcon = type === "success" ? "check" : type === "error" ? "alert" : "info";
  node.innerHTML = `<span class="t-ico">${icon(toastIcon, "t-svg")}</span><div><b>${esc(title)}</b>${message ? `<small>${esc(message)}</small>` : ""}</div>`;
  wrap.appendChild(node);
  setTimeout(() => {
    node.style.opacity = "0";
    node.style.transform = "translateY(6px)";
    node.style.transition = "0.25s";
    setTimeout(() => node.remove(), 260);
  }, timeout);
}

/* -------------------------------------------------------------------------- */
/* Başlangıç & Tema                                                           */
/* -------------------------------------------------------------------------- */
document.addEventListener("DOMContentLoaded", init);

function initTheme() {
  const saved = localStorage.getItem("netmagic_theme") || "dark";
  setTheme(saved);
  const btn = $("#theme-btn");
  if (btn) {
    btn.addEventListener("click", () => {
      const current = document.documentElement.dataset.theme || "dark";
      setTheme(current === "dark" ? "light" : "dark");
    });
  }
}

function setTheme(theme) {
  state.theme = theme;
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("netmagic_theme", theme);
  const icon = $("#theme-icon use");
  if (icon) {
    icon.setAttribute("href", theme === "dark" ? "#i-sun" : "#i-moon");
  }
  if (state.view === "map") renderMap();
  if (state.view === "dashboard") drawTrafficChart();
}

function viewFromHash() {
  const name = decodeURIComponent((location.hash || "").replace(/^#\/?/, "")).trim();
  return PAGE_META[name] ? name : "dashboard";
}

function registerServiceWorker() {
  // Servis çalışanı yalnızca güvenli bağlamda (https veya localhost) çalışır
  if (!("serviceWorker" in navigator) || !window.isSecureContext) return;
  navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {});
}

async function init() {
  initTheme();
  bindEvents();
  registerServiceWorker();
  // F5 / yer imi: adres çubuğundaki sekmeyi koru (ör. /#map)
  const initialView = viewFromHash();
  activateView(initialView);
  const onRoute = () => {
    const name = viewFromHash();
    if (name !== state.view) showView(name, { updateHash: false });
  };
  window.addEventListener("hashchange", onRoute);
  window.addEventListener("popstate", onRoute);
  await refreshAll();
  // Veriler yüklendi; o anki sekmenin verisini doldur (yükleme sırasında sekme değiştiyse onu koru)
  showView(state.view, { updateHash: false, scroll: false });
  maybeOnboard();
  state.pollTimer = setInterval(poll, 4000);
  setInterval(() => { refreshDevicesAndAlerts(); }, 25000);
  setInterval(() => { if (state.view === "dashboard") { renderAlertsPreview(); renderDeviceStrip(); } }, 30000);
}

function bindEvents() {
  $$(".nav-item").forEach((btn) => btn.addEventListener("click", () => showView(btn.dataset.view)));
  document.addEventListener("click", (e) => {
    const goto = e.target.closest("[data-goto]");
    if (goto) { showView(goto.dataset.goto); return; }
    if (e.target.closest("[data-scan]")) { startScan(); return; }
    const drawerPause = e.target.closest("#device-drawer [data-pause]");
    if (drawerPause) { pauseDevice(state.selectedId, Number(drawerPause.dataset.pause)); return; }
    const parentalPause = e.target.closest("#view-parental [data-pause]");
    if (parentalPause) { pauseDevice(state.scheduleDeviceId, Number(parentalPause.dataset.pause)); return; }
    const preset = e.target.closest("#view-parental [data-preset]");
    if (preset) { applyPreset(preset.dataset.preset); return; }
  });

  $("#scan-btn").addEventListener("click", () => startScan());
  $("#hero-scan").addEventListener("click", () => startScan());
  $("#menu-btn").addEventListener("click", () => setSidebar(!$("#sidebar").classList.contains("open")));
  $$(".tab-item[data-view]").forEach((btn) => btn.addEventListener("click", () => showView(btn.dataset.view)));
  const tabMore = $("#tab-more");
  if (tabMore) tabMore.addEventListener("click", () => setSidebar(true));
  const sbBackdrop = $("#sidebar-backdrop");
  if (sbBackdrop) sbBackdrop.addEventListener("click", () => setSidebar(false));

  $("#traffic-range").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-range]");
    if (!btn) return;
    $$("#traffic-range button").forEach((b) => b.classList.toggle("active", b === btn));
    state.trafficRange = Number(btn.dataset.range);
    loadTraffic();
  });

  $("#device-search").addEventListener("input", (e) => {
    state.search = e.target.value.toLowerCase().trim();
    renderDeviceTable();
  });
  $("#device-filters").addEventListener("click", (e) => {
    const chip = e.target.closest("[data-filter]");
    if (!chip) return;
    state.filter = chip.dataset.filter;
    $$("#device-filters .chip").forEach((c) => c.classList.toggle("active", c === chip));
    renderDeviceTable();
  });

  $("#drawer-close").addEventListener("click", closeDrawer);
  $("#drawer-backdrop").addEventListener("click", closeDrawer);
  $("#drawer-save").addEventListener("click", saveDrawer);
  $("#drawer-trusted").addEventListener("change", (e) => patchDevice(state.selectedId, { trusted: e.target.checked }));
  $("#drawer-blocked").addEventListener("change", (e) => blockDevice(state.selectedId, e.target.checked));
  $("#drawer-delete").addEventListener("click", () => {
    const device = currentDevice();
    if (!device) return;
    confirmDialog(
      "Cihazı kaldır",
      `<b>${esc(device.display_name)}</b> cihazı envanterden kaldırılacak. Ağda görünmeye devam ederse yeniden keşfedilebilir.`,
      "Kaldır",
      async () => {
        await api(`/api/devices/${device.id}`, { method: "DELETE" });
        closeDrawer();
        await refreshDevicesAndAlerts();
        toast("Cihaz kaldırıldı", "", "success");
      },
      true
    );
  });

  $("#speedtest-btn").addEventListener("click", runSpeedtest);
  const segmented = (sel, onPick) => {
    const el = $(sel);
    if (!el) return;
    el.addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-range]");
      if (!btn) return;
      $$(`${sel} button`).forEach((b) => b.classList.toggle("active", b === btn));
      onPick(Number(btn.dataset.range));
    });
  };
  segmented("#latency-range", (v) => { state.latencyRange = v; loadLatency(); });
  segmented("#outage-range", (v) => { state.outageRange = v; loadOutages(); });
  const outageCopy = $("#outage-copy");
  if (outageCopy) outageCopy.addEventListener("click", () => copyText(outageReportText(), "Kesinti raporu"));
  const guestQr = $("#guest-qr");
  if (guestQr) guestQr.addEventListener("click", () => { const l = $("#guest-link").value; if (l) showQr(l, "Misafir bağlantısı"); });

  // Tıkla-kopyala: yakalama aşamasında çalışır ki satırın "ayrıntıyı aç" tıklaması tetiklenmesin
  document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-copy]");
    if (!el || e.button !== 0 || e.ctrlKey || e.metaKey) return;
    if (window.getSelection && String(window.getSelection()).length > 1) return; // metin seçiliyorsa engelleme
    e.preventDefault();
    e.stopPropagation();
    copyText(el.dataset.copy, el.dataset.copyLabel || "");
    flashCopied(el);
  }, true);

  initContextMenu();
  const mergeBtn = $("#drawer-merge-btn");
  if (mergeBtn) mergeBtn.addEventListener("click", mergeSelectedDevice);
  $("#printers-refresh").addEventListener("click", loadPrinters);
  $$("[data-repair]").forEach((btn) => btn.addEventListener("click", () => runRepair(btn.dataset.repair)));

  $("#dropzone").addEventListener("click", (e) => {
    if (e.target.closest("#browse-btn") || !e.target.closest("button")) $("#file-input").click();
  });
  $("#file-input").addEventListener("change", (e) => uploadFiles(e.target.files));
  $("#dropzone").addEventListener("dragover", (e) => { e.preventDefault(); $("#dropzone").classList.add("dragover"); });
  $("#dropzone").addEventListener("dragleave", () => $("#dropzone").classList.remove("dragover"));
  $("#dropzone").addEventListener("drop", (e) => {
    e.preventDefault();
    $("#dropzone").classList.remove("dragover");
    uploadFiles(e.dataTransfer.files);
  });
  $("#guest-apply").addEventListener("click", applyGuest);
  $("#guest-toggle").addEventListener("change", () => { if (!$("#guest-toggle").checked) applyGuest(); });
  $("#guest-copy").addEventListener("click", () => copyText($("#guest-link").value, "Misafir bağlantısı"));
  // Misafir bağlantısı kutusuna tıklayınca tümünü seç ve kopyala
  $("#guest-link").addEventListener("click", (e) => { e.target.select(); copyText(e.target.value, "Misafir bağlantısı"); });

  $("#schedule-save").addEventListener("click", saveSchedule);
  $("#schedule-grid").addEventListener("click", (e) => {
    const cell = e.target.closest(".schedule-cell");
    if (!cell || !state.schedule) return;
    const day = Number(cell.dataset.day);
    const hour = Number(cell.dataset.hour);
    const set = state.schedule.allowed[day];
    if (set.has(hour)) set.delete(hour); else set.add(hour);
    state.schedule.enabled = true;
    renderScheduleGrid();
  });
  $("#parental-devices").addEventListener("click", (e) => {
    const row = e.target.closest("[data-schedule-device]");
    if (!row) return;
    selectScheduleDevice(Number(row.dataset.scheduleDevice));
  });

  $("#alerts-read").addEventListener("click", async () => {
    await api("/api/alerts/read", { method: "POST", body: {} });
    await refreshAlerts();
    toast("Uyarılar okundu olarak işaretlendi", "", "success");
  });
  $("#alerts-clear").addEventListener("click", () => {
    confirmDialog("Uyarıları temizle", "Tüm uyarı kayıtları silinecek. Emin misiniz?", "Temizle", async () => {
      await api("/api/alerts", { method: "DELETE" });
      await refreshAlerts();
      toast("Uyarılar temizlendi", "", "success");
    }, true);
  });

  $("#scan-settings").addEventListener("submit", saveSettings);
  $("#report-btn").addEventListener("click", showReport);
  $("#scan-history-btn").addEventListener("click", showScanHistory);
  $("#reset-btn").addEventListener("click", resetData);
  $("#quit-btn").addEventListener("click", () => {
    confirmDialog("Uygulamayı kapat", "Network Magic sunucusu durdurulacak ve tüm geçici güvenlik duvarı kuralları kaldırılacak.", "Kapat", async () => {
      await api("/api/quit", { method: "POST", body: {} });
      document.body.innerHTML = `<div style="display:grid;place-items:center;height:100vh;color:#94a3b8;font-family:Segoe UI,sans-serif"><div style="text-align:center"><div style="width:64px;height:64px;margin:0 auto 16px;border-radius:20px;display:grid;place-items:center;background:rgba(16,185,129,.14);border:1px solid rgba(16,185,129,.3);color:#34d399"><svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M12 3v9"/><path d="M6.8 6.2a8 8 0 1 0 10.4 0"/></svg></div><h2 style="color:#f8fafc;margin:0 0 6px">Network Magic kapatıldı</h2><p style="margin:0">Bu pencereyi kapatabilirsiniz.</p></div></div>`;
    }, true);
  });

  $("#modal-close").addEventListener("click", hideModal);
  $("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") hideModal(); });

  $("#onboarding-start").addEventListener("click", async () => {
    const name = $("#onboarding-name").value.trim();
    await api("/api/onboarding", { method: "POST", body: { device_name: name } });
    $("#onboarding").classList.add("hidden");
    if (state.status) state.status.settings.onboarded = true;
    startScan();
  });

  $("#map-zoom-in").addEventListener("click", () => setMapZoom(state.mapZoom + 0.15));
  $("#map-zoom-out").addEventListener("click", () => setMapZoom(state.mapZoom - 0.15));
  $("#map-reset").addEventListener("click", () => resetMap());
  const mapFit = $("#map-fit-btn");
  if (mapFit) mapFit.addEventListener("click", () => resetMap());

  const mapFilters = $("#map-category-filters");
  if (mapFilters) {
    mapFilters.addEventListener("click", (e) => {
      const chip = e.target.closest("[data-map-filter]");
      if (!chip) return;
      state.mapFilter = chip.dataset.mapFilter;
      $$("#map-category-filters .chip").forEach((c) => c.classList.toggle("active", c === chip));
      renderMap();
    });
  }

  const mapSearchInput = $("#map-search-input");
  if (mapSearchInput) {
    mapSearchInput.addEventListener("input", (e) => {
      state.mapSearch = e.target.value.toLowerCase().trim();
      renderMap();
    });
  }

  const dashRepair = $("#dash-quick-repair");
  if (dashRepair) {
    dashRepair.addEventListener("click", () => showView("internet"));
  }

  const pingBtn = $("#drawer-ping-btn");
  if (pingBtn) {
    pingBtn.addEventListener("click", pingSelectedDevice);
  }

  const wolBtn = $("#drawer-wol-btn");
  if (wolBtn) {
    wolBtn.addEventListener("click", wakeSelectedDevice);
  }

  const testNotifBtn = $("#test-notification-btn");
  if (testNotifBtn) {
    testNotifBtn.addEventListener("click", testDesktopNotification);
  }

  const wifiAnalyzerBtn = $("#wifi-analyzer-btn");
  if (wifiAnalyzerBtn) {
    wifiAnalyzerBtn.addEventListener("click", async () => {
      await loadWifiAnalyzer(true);
      loadWifi();
    });
  }

  // Harita sürükleme (Pan) desteği
  const svgMap = $("#network-map");
  if (svgMap) {
    svgMap.addEventListener("mousedown", (e) => {
      if (e.target.closest(".map-node") || e.target.closest(".map-center") || e.target.closest(".map-internet")) return;
      state.isPanning = true;
      state.panStart = { x: e.clientX - state.mapPan.x, y: e.clientY - state.mapPan.y };
      svgMap.style.cursor = "grabbing";
    });
    window.addEventListener("mousemove", (e) => {
      if (!state.isPanning) return;
      state.mapPan = { x: e.clientX - state.panStart.x, y: e.clientY - state.panStart.y };
      applyMapZoom();
    });
    window.addEventListener("mouseup", () => {
      state.isPanning = false;
      if (svgMap) svgMap.style.cursor = "grab";
    });
    svgMap.addEventListener("wheel", (e) => {
      e.preventDefault();
      const delta = e.deltaY < 0 ? 0.12 : -0.12;
      setMapZoom(state.mapZoom + delta);
    }, { passive: false });
  }

  const radar = $("#hero-radar");
  if (radar) {
    radar.addEventListener("click", (e) => {
      const node = e.target.closest("[data-hv-device]");
      if (node) { openDrawer(Number(node.dataset.hvDevice)); return; }
      if (e.target.closest("[data-hv-router]")) {
        const gw = state.status && state.status.network && state.status.network.gateway;
        const router = state.devices.find((d) => d.ip === gw) || state.devices.find((d) => d.type === "router");
        if (router) openDrawer(router.id); else showView("map");
        return;
      }
      if (e.target.closest(".hv-inet")) showView("internet");
    });
  }

  window.addEventListener("resize", () => {
    if (state.view === "dashboard") drawTrafficChart();
    if (state.view === "internet") drawLatencyChart();
    if (state.view === "map" && state.mapCompact !== isCompact()) { resetMap(); renderMap(); }
    if (!isCompact() && $("#sidebar").classList.contains("open") && window.innerWidth > 980) setSidebar(false);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { closeDrawer(); hideModal(); setSidebar(false); }
  });
}

async function pingSelectedDevice() {
  const dev = currentDevice();
  const resEl = $("#drawer-ping-result");
  const btn = $("#drawer-ping-btn");
  if (!dev || !dev.ip || !resEl) return;
  resEl.textContent = "Ping gönderiliyor…";
  resEl.className = "ping-pill";
  if (btn) btn.disabled = true;
  try {
    const data = await api(`/api/devices/${dev.id}/ping`, { method: "POST" });
    if (data.ok && data.avg_ms != null) {
      resEl.textContent = `${data.avg_ms} ms (Kayıp: %${data.loss_pct})`;
      resEl.className = "ping-pill good";
    } else {
      resEl.textContent = data.message || "Cihaz yanıt vermedi";
      resEl.className = "ping-pill bad";
    }
  } catch (err) {
    resEl.textContent = "Ulaşılamadı";
    resEl.className = "ping-pill bad";
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function wakeSelectedDevice() {
  const dev = currentDevice();
  const resEl = $("#drawer-ping-result");
  const btn = $("#drawer-wol-btn");
  if (!dev || !dev.mac) {
    toast("Wake-on-LAN", "Bu cihazın MAC adresi kayıtlı değil.", "warning");
    return;
  }
  if (resEl) {
    resEl.textContent = "Magic Packet gönderiliyor…";
    resEl.className = "ping-pill";
  }
  if (btn) btn.disabled = true;
  try {
    const data = await api(`/api/devices/${dev.id}/wake`, { method: "POST" });
    if (data.ok) {
      if (resEl) {
        resEl.textContent = "WoL Gönderildi ✓";
        resEl.className = "ping-pill good";
      }
      toast("Wake-on-LAN", data.message || "Uyandırma paketi ağa iletildi.", "success");
    } else {
      if (resEl) {
        resEl.textContent = "WoL Hatası";
        resEl.className = "ping-pill bad";
      }
      toast("Wake-on-LAN", data.message || "Paket gönderilemedi.", "error");
    }
  } catch (err) {
    if (resEl) {
      resEl.textContent = "Hata";
      resEl.className = "ping-pill bad";
    }
    toast("Wake-on-LAN Hatası", err.message, "error");
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function testDesktopNotification() {
  const btn = $("#test-notification-btn");
  if (btn) btn.disabled = true;
  try {
    if ("Notification" in window && Notification.permission !== "granted") {
      await Notification.requestPermission();
    }
    const data = await api("/api/test-notification", { method: "POST" });
    if (data.ok) {
      toast("Bildirim Testi", "Windows masaüstü bildirim balonu gönderildi!", "success");
      if ("Notification" in window && Notification.permission === "granted") {
        new Notification("Network Magic — Wi-Fi Alarm Testi", {
          body: "Yeni cihaz bildirim sistemi devrede!",
          icon: "/static/img/favicon.svg",
        });
      }
    } else {
      toast("Bildirim", data.message || "Bildirim gönderilemedi.", "warning");
    }
  } catch (err) {
    toast("Bildirim Hatası", err.message, "error");
  } finally {
    if (btn) btn.disabled = false;
  }
}

/* -------------------------------------------------------------------------- */
/* Veri yenileme                                                              */
/* -------------------------------------------------------------------------- */
async function refreshAll() {
  try {
    const [status, devices, alerts] = await Promise.all([
      api("/api/status"),
      api("/api/devices"),
      api("/api/alerts"),
    ]);
    state.status = status;
    state.devices = devices.devices || [];
    state.counts = devices.counts || status.counts;
    state.alerts = alerts.alerts || [];
    state.trafficSamples = (status.stats && status.stats.samples) || [];
    renderAll();
    handleScanState(status.scan);
  } catch (err) {
    toast("Sunucuya ulaşılamadı", err.message, "error");
  }
}

async function refreshDevicesAndAlerts() {
  try {
    const [devices, alerts] = await Promise.all([api("/api/devices"), api("/api/alerts")]);
    state.devices = devices.devices || [];
    state.counts = devices.counts || state.counts;
    state.alerts = alerts.alerts || [];
    renderSidebar();
    renderDeviceTable();
    renderAlertsPreview();
    renderDeviceStrip();
    renderAlertList();
    if (state.view === "dashboard") updateLive();
    if (state.view === "map") renderMap();
    if (drawerIsOpen() && currentDevice()) renderDrawer(currentDevice(), { soft: true });
    if (state.view === "parental" && state.scheduleDeviceId) renderParentalDevices();
  } catch { /* sessiz */ }
}

async function refreshAlerts() {
  const data = await api("/api/alerts");
  state.alerts = data.alerts || [];
  state.counts.alerts = data.unread || 0;
  renderAlertsPreview();
  renderAlertList();
  renderSidebar();
}

async function poll() {
  try {
    const status = await api("/api/status");
    state.status = status;
    state.counts = { ...state.counts, ...(status.counts || {}) };
    renderSidebar();
    renderRibbon();
  updateLive();
    renderScan(status.scan);
    if (status.scan && status.scan.running) {
      handleScanState(status.scan);
    }
    if (state.view === "internet" && !document.hidden) {
      if (Date.now() - state.latencyAt > 10000) loadLatency();
      if (Date.now() - state.outagesAt > 60000) loadOutages();
    }
  } catch { /* sessiz */ }
}

function handleScanState(scan) {
  if (!scan) return;
  renderScan(scan);
  if (scan.running) {
    state.scanning = true;
    startScanPolling();
  } else if (state.scanning) {
    state.scanning = false;
    stopScanPolling();
    const wasNew = scan.new || 0;
    const found = scan.found || 0;
    if (scan.error) toast("Tarama hatası", scan.error, "error", 6500);
    else if (wasNew > 0) toast("Ağ taraması tamamlandı", `${found} cihaz bulundu, ${wasNew} yeni cihaz algılandı.`, "success", 6000);
    refreshAll();
  }
}

function startScanPolling() {
  if (state.scanTimer) return;
  state.scanTimer = setInterval(async () => {
    try {
      const data = await api("/api/scan/status");
      renderScan(data.scan);
      state.devices = data.devices || state.devices;
      state.counts = data.counts || state.counts;
      renderDeviceTable();
      if (!data.scan.running) handleScanState(data.scan);
    } catch { /* sessiz */ }
  }, 900);
}

function stopScanPolling() {
  if (state.scanTimer) { clearInterval(state.scanTimer); state.scanTimer = null; }
}

async function startScan() {
  if (state.scanning) { toast("Tarama sürüyor", "Mevcut taramanın bitmesini bekleyin.", "info", 2500); return; }
  try {
    const data = await api("/api/scan", { method: "POST", body: { deep: true } });
    state.scanning = true;
    renderScan(data.scan);
    startScanPolling();
    toast("Ağ taranıyor", "Cihazlar keşfediliyor, bu birkaç saniye sürebilir.", "info", 3000);
  } catch (err) {
    toast("Tarama başlatılamadı", err.message, "error");
  }
}

/* -------------------------------------------------------------------------- */
/* Render — genel                                                             */
/* -------------------------------------------------------------------------- */
function renderAll() {
  renderRibbon();
  renderSidebar();
  renderDashboard();
  renderMap();
  renderDeviceTable();
  renderAlertsPreview();
  renderDeviceStrip();
  renderAlertList();
}

function renderRibbon() {
  const ribbon = $("#status-ribbon");
  if (!ribbon) return;
  const net = (state.status && state.status.network) || {};
  const wifi = net.wifi || {};
  const counts = state.counts || {};
  const speed = (state.status && state.status.speed) || state.speed || {};
  const isOnline = !!net.internet;

  // İnternet Düğümü
  const intStatus = $("#ribbon-internet-status");
  const intDot = $("#ribbon-internet-dot");
  const intIp = $("#ribbon-internet-ip");
  if (intStatus) {
    intStatus.textContent = isOnline ? "Bağlantı Sağlıklı" : "İnternet Bağlantısı Yok";
    intStatus.style.color = isOnline ? "var(--mint-light)" : "var(--red-light)";
  }
  if (intDot) intDot.className = `rn-status-dot ${isOnline ? "on" : "off"}`;
  if (intIp) {
    intIp.textContent = speed.public_ip ? `Genel IP: ${speed.public_ip}` : (isOnline ? "İnternet Aktif" : "Ağ geçidine ulaşılamıyor");
    setCopy(intIp, speed.public_ip, "Genel IP");
  }

  // Köprü 1 (İnternet -> Yönlendirici)
  const b1 = $("#rb-bridge-1");
  const pingVal = $("#ribbon-ping-val");
  if (b1) b1.classList.toggle("broken", !isOnline);
  if (pingVal) {
    // Canlı internet gecikmesi (10 sn'de bir ölçülür); yoksa son hız testinin ping'i
    const live = net.latency && net.latency.inet_ms;
    const ms = live != null ? live : speed.ping_ms;
    pingVal.textContent = !isOnline ? "Kopuk" : ms != null ? `${Math.round(ms)} ms` : "Aktif";
  }

  // Yönlendirici (Ağ Geçidi)
  const routerDev = state.devices.find((d) => d.ip === net.gateway);
  const rName = $("#ribbon-router-name");
  const rIp = $("#ribbon-router-ip");
  const rDot = $("#ribbon-router-dot");
  if (rName) rName.textContent = routerDev ? routerDev.display_name : (net.gateway ? "Ağ Geçidi" : "Yönlendirici");
  if (rIp) { rIp.textContent = net.gateway ? `IP: ${net.gateway}` : "IP aranıyor…"; setCopy(rIp, net.gateway, "Modem IP"); }
  if (rDot) rDot.className = `rn-status-dot ${net.gateway ? "on" : "off"}`;

  // Köprü 2 (Yönlendirici -> Bilgisayar)
  const wifiVal = $("#ribbon-wifi-val");
  if (wifiVal) {
    if (wifi.connected && wifi.ssid) {
      wifiVal.textContent = `${wifi.ssid}${wifi.signal != null ? ` (%${wifi.signal})` : ""}`;
    } else if (net.name) {
      wifiVal.textContent = "Kablolu Bağlantı";
    } else {
      wifiVal.textContent = "Bağlantı Yok";
    }
  }

  // Bilgisayar & Yerel Ağ
  const pcName = $("#ribbon-pc-name");
  const pcDevs = $("#ribbon-pc-devices");
  const selfDev = state.devices.find((d) => d.is_self);
  if (pcName) {
    pcName.textContent = (selfDev && selfDev.display_name) || (state.status && state.status.app && state.status.app.hostname) || "Bu Bilgisayar";
  }
  if (pcDevs) {
    pcDevs.textContent = `${counts.online || 0} cihaz çevrimiçi (toplam ${counts.total || 0})`;
  }

  // Hızlı onarım butonu
  const repBtn = $("#ribbon-repair-btn");
  if (repBtn && !repBtn._bound) {
    repBtn._bound = true;
    repBtn.addEventListener("click", () => showView("internet"));
  }
}

function renderSidebar() {
  const net = (state.status && state.status.network) || {};
  const ssid = (net.wifi && net.wifi.ssid) || net.name || "Kablolu ağ";
  $("#sidebar-ssid").textContent = ssid;
  $("#sidebar-ip").textContent = net.ip ? `${net.ip}${net.wifi && net.wifi.connected ? " • Wi-Fi" : ""}` : "—";
  setCopy($("#sidebar-ip"), net.ip, "IP adresi");
  $(".net-mini-dot").classList.toggle("offline", !net.internet);
  $("#nav-device-count").textContent = state.counts.total || "";
  const unread = state.counts.alerts || 0;
  const navAlert = $("#nav-alert-count");
  navAlert.textContent = unread || "";
  const tabBadge = $("#tab-more-badge");
  if (tabBadge) tabBadge.textContent = unread ? (unread > 99 ? "99+" : unread) : "";
  const bell = $("#bell-badge");
  bell.textContent = unread || "";
  bell.dataset.zero = unread ? "0" : "1";
  if (state.status) {
    const admin = state.status.app && state.status.app.admin;
    const badge = $("#sidebar-admin");
    badge.textContent = admin ? "Yönetici" : "Sınırlı mod";
    badge.className = `badge ${admin ? "badge-mint" : "badge-muted"}`;
  }
}

function updateLive() {
  if (!state.status) return;
  const counts = state.counts;
  $("#stat-online").textContent = counts.online || 0;
  $("#stat-online-sub").textContent = `toplam ${counts.total || 0} cihaz`;
  $("#stat-trusted").textContent = (counts.total || 0) - (counts.untrusted || 0);
  $("#stat-trusted-sub").textContent = `${counts.untrusted || 0} incelenmeyi bekliyor`;
  const stats = state.status.stats || {};
  $("#stat-rx").innerHTML = `${fmtMbps(stats.rx_bps)} <em>Mb/s</em>`;
  $("#stat-tx").innerHTML = `${fmtMbps(stats.tx_bps)} <em>Mb/s</em>`;
  $("#stat-rx-sub").textContent = `toplam ${fmtBytes(stats.rx_total)}`;
  $("#stat-tx-sub").textContent = `toplam ${fmtBytes(stats.tx_total)}`;

  const net = state.status.network || {};
  const wifi = net.wifi || {};
  const internetOk = net.internet;
  const internetEl = $("#health-internet");
  internetEl.textContent = internetOk ? (wifi.connected ? "Bağlı • Wi-Fi" : "Bağlı • Kablolu") : "Bağlantı yok";
  internetEl.className = `health-value ${internetOk ? "good" : "bad"}`;
  const signalEl = $("#health-signal");
  signalEl.textContent = wifi.signal != null
    ? `%${wifi.signal}${wifi.band ? " • " + wifi.band : ""}`
    : (wifi.connected ? (wifi.ssid || "Bağlı") : "Kablolu bağlantı");
  signalEl.className = "health-value";
  $("#health-gateway").textContent = net.gateway || "—";
  setCopy($("#health-gateway"), net.gateway, "Modem IP");
  $("#health-adapter").textContent = `${net.name || "—"}${net.speed_mbps ? " • " + net.speed_mbps + " Mb/s" : ""}`;
  $("#health-restricted").textContent = counts.restricted ? `${counts.restricted} cihaz` : "Yok";
  $("#health-restricted").className = `health-value ${counts.restricted ? "bad" : "good"}`;
  $("#health-badge").textContent = internetOk ? "Bağlı" : "Çevrimdışı";
  $("#health-badge").className = `badge ${internetOk ? "badge-mint" : "badge-red"}`;
  $("#signal-bars").dataset.level = String(signalLevel(wifi.signal));
  renderHeroRadar();

  if (state.trafficRange === 0) {
    state.trafficSamples = (stats.samples || []).slice(-160);
    drawTrafficChart();
  }
}

function renderScan(scan) {
  if (!scan) return;
  const running = !!scan.running;
  const pill = $("#scan-pill");
  pill.classList.toggle("show", running);
  $("#scan-pill-text").textContent = scan.phase || "Taranıyor…";
  $("#scan-pill-pct").textContent = `${scan.progress || 0}%`;
  const bar = $("#scan-progress");
  bar.classList.toggle("show", running);
  bar.firstElementChild.style.width = `${scan.progress || 0}%`;
  const radar = $("#hero-radar");
  if (radar) {
    radar.classList.toggle("scanning", running);
    if (radar.parentElement) radar.parentElement.classList.toggle("scanning", running);
  }
  const btn = $("#scan-btn");
  btn.classList.toggle("loading", running);
  btn.disabled = running;
  btn.querySelector("span").textContent = running ? "Taranıyor" : "Ağı Tara";
}

/* -------------------------------------------------------------------------- */
/* Genel bakış                                                                */
/* -------------------------------------------------------------------------- */
function renderDashboard() {
  const counts = state.counts;
  const net = (state.status && state.status.network) || {};
  const wifi = net.wifi || {};
  const untrusted = counts.untrusted || 0;

  const title = !counts.total
    ? "Ağınızı keşfetmeye hazır."
    : untrusted
      ? "İncelenmeyi bekleyen cihazlar var."
      : "Ağınız kontrol altında.";
  $("#hero-title").textContent = title;
  $("#hero-sub").textContent = !counts.total
    ? "Ağı tarayarak cihazlarınızı bulun, haritanızı oluşturun ve bağlantınızı izleyin."
    : untrusted
      ? `${untrusted} cihaz henüz güvenilir olarak işaretlenmedi. Ayrıntıları inceleyip karar verin.`
      : `${counts.total} cihaz envanterinizde, ${counts.online} tanesi şu anda çevrimiçi.`;
  $("#hero-eyebrow").textContent = net.internet ? "AĞ DURUMU • BAĞLI" : "AĞ DURUMU • ÇEVRİMDIŞI";

  const chips = [];
  if (wifi.connected && wifi.ssid) chips.push(`<span class="hero-chip">${icon("wifi", "chip-ico")} <b>${esc(wifi.ssid)}</b>${wifi.signal != null ? ` • %${wifi.signal}` : ""}</span>`);
  else if (net.name) chips.push(`<span class="hero-chip">${icon("plug", "chip-ico")} <b>${esc(net.name)}</b></span>`);
  if (net.ip) chips.push(`<span class="hero-chip">IP <b ${copyAttr(net.ip, "IP adresi")}>${esc(net.ip)}</b></span>`);
  if (net.gateway) chips.push(`<span class="hero-chip">Yönlendirici <b ${copyAttr(net.gateway, "Modem IP")}>${esc(net.gateway)}</b></span>`);
  chips.push(`<span class="hero-chip"><i class="chip-dot ${net.internet ? "on" : "off"}"></i> <b>${net.internet ? "İnternet var" : "İnternet yok"}</b></span>`);
  $("#hero-chips").innerHTML = chips.join("");

  renderRibbon();
  updateLive();
  renderAlertsPreview();
  renderDeviceStrip();
  renderHeroRadar();
}

function renderAlertsPreview() {
  const wrap = $("#dash-alerts");
  if (!wrap) return;
  const items = state.alerts.slice(0, 4);
  if (!items.length) {
    wrap.innerHTML = `<div class="empty-state" style="padding:22px"><div class="empty-icon">${icon("shield", "empty-svg")}</div><h2>Ağınız sakin</h2><p>Henüz bir uyarı yok.</p></div>`;
    return;
  }
  wrap.innerHTML = items.map((a) => alertRow(a, true)).join("");
}

function renderDeviceStrip() {
  const wrap = $("#dash-devices");
  if (!wrap) return;
  const devices = state.devices.filter((d) => d.online).slice(0, 7);
  if (!devices.length) {
    wrap.innerHTML = `<p class="muted" style="font-size:12px;padding:8px 0">Henüz çevrimiçi cihaz yok. Ağı tarayın.</p>`;
    return;
  }
  wrap.innerHTML = devices.map((d) => {
    const meta = typeMeta(d.type);
    return `<button class="device-chip" data-device-open="${d.id}">
      <span class="dc-ico" style="background:${meta.color}18;color:${meta.color}">${typeIcon(d.type, "type-icon-sm")}</span>
      <span class="dc-copy"><b>${esc(d.display_name)}</b><small>${esc(d.ip || "")}</small></span>
      <span class="dc-dot online"></span>
    </button>`;
  }).join("");
  wrap.querySelectorAll("[data-device-open]").forEach((el) => el.addEventListener("click", () => openDrawer(Number(el.dataset.deviceOpen))));
}

/* -------------------------------------------------------------------------- */
/* Genel bakış — canlı ağ radarı                                              */
/* -------------------------------------------------------------------------- */
// Yuvarlağa yakın, dengeli radar: viewBox 440x400, modem merkezde, internet tepede
const HV = { cx: 220, cy: 210, max: 16, inner: [100, 92], outer: [172, 146] };

function hvTrafficLevel() {
  const s = (state.status && state.status.stats) || {};
  const total = (Number(s.rx_bps) || 0) + (Number(s.tx_bps) || 0);
  return total > 20e6 ? 3 : total > 2e6 ? 2 : total > 2e5 ? 1 : 0;
}

function hvPositions(count) {
  // Üstteki internet hattına çarpmamak için tepe bölgesi (±32°) boş bırakılır
  // Az cihazda tek halka; fazlasında iç/dış halkaya çevreleriyle orantılı dağıt
  const inner = count <= 5 ? count : Math.max(4, Math.min(7, Math.round(count * 0.4)));
  const outer = count - inner;
  // İç halka (i+0.5)/n, dış halka (i+1)/(n+1): eşit sayıda olsalar bile dış halkadaki
  // cihazlar iç halkanın boşluklarına düşer, etiketler üst üste binmez.
  const place = (n, [rx, ry], frac) => {
    const out = [];
    const start = -90 + 32, span = 360 - 64;
    for (let i = 0; i < n; i++) {
      const ang = ((start + span * frac(i, n)) * Math.PI) / 180;
      out.push({ x: HV.cx + Math.cos(ang) * rx, y: HV.cy + Math.sin(ang) * ry });
    }
    return out;
  };
  return [
    ...place(inner, HV.inner, (i, n) => (i + 0.5) / n),
    ...place(outer, HV.outer, (i, n) => (i + 1) / (n + 1)),
  ];
}

function renderHeroRadar(force = false) {
  const svg = $("#hero-radar");
  if (!svg) return;
  svg.classList.toggle("scanning", !!state.scanning);
  if (svg.parentElement) svg.parentElement.classList.toggle("scanning", !!state.scanning);
  renderHeroCaption();

  const net = (state.status && state.status.network) || {};
  const online = !!net.internet;
  const gateway = net.gateway || "";
  const devices = state.devices
    .filter((d) => d.ip !== gateway && d.type !== "router")
    .sort((a, b) => (b.is_self - a.is_self) || (b.online - a.online) || (a.id - b.id));
  const shown = devices.slice(0, HV.max);
  const level = hvTrafficLevel();
  const signature = JSON.stringify([online, level, shown.map((d) => [d.id, d.online, d.restricted, d.type, d.display_name])]);
  if (!force && svg.dataset.sig === signature) return;
  svg.dataset.sig = signature;

  const { cx, cy } = HV;
  const pos = hvPositions(shown.length);
  const withLabels = shown.length <= 12;
  const pktDur = [3.6, 2.6, 1.8, 1.1][level];

  const links = [];
  const packets = [];
  const nodes = [];
  shown.forEach((d, i) => {
    const p = pos[i];
    const meta = typeMeta(d.type);
    // Hafif kavisli bağlantı: merkezden cihaza
    const mx = (cx + p.x) / 2 + (p.y - cy) * 0.12;
    const my = (cy + p.y) / 2 - (p.x - cx) * 0.12;
    const path = `M ${cx} ${cy} Q ${mx.toFixed(1)} ${my.toFixed(1)} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`;
    const cls = d.restricted ? "blocked" : d.online ? "on" : "off";
    const stroke = d.restricted ? "var(--red)" : d.online ? meta.color : "var(--muted-2)";
    links.push(`<path class="hv-link ${cls}" d="${path}" ${d.online && !d.restricted ? `stroke="${meta.color}" stroke-opacity="0.38"` : ""}/>`);
    if (d.online && !d.restricted) {
      const dur = (pktDur + (i % 3) * 0.35).toFixed(2);
      packets.push(`<circle class="hv-packet" r="2.2" fill="${meta.color}"><animateMotion dur="${dur}s" begin="-${((i * 0.73) % dur).toFixed(2)}s" repeatCount="indefinite" path="${path}"/></circle>`);
      if (level >= 2) {
        // Yoğun trafikte ters yönde (yükleme) ikinci paket
        packets.push(`<circle class="hv-packet" r="1.8" fill="#a78bfa"><animateMotion dur="${(dur * 1.3).toFixed(2)}s" begin="-${((i * 1.1) % dur).toFixed(2)}s" repeatCount="indefinite" keyPoints="1;0" keyTimes="0;1" calcMode="linear" path="${path}"/></circle>`);
      }
    }
    const title = `${d.display_name}${d.ip ? " • " + d.ip : ""} • ${d.restricted ? "Kısıtlı" : d.online ? "Çevrimiçi" : "Çevrimdışı"}`;
    nodes.push(`<g class="hv-node ${d.online ? "on" : "off"}" data-hv-device="${d.id}" transform="translate(${p.x.toFixed(1)},${p.y.toFixed(1)})">
      <title>${esc(title)}</title>
      <circle class="hv-halo" r="19" stroke="${stroke}" style="animation-delay:-${(i * 0.37).toFixed(2)}s"/>
      ${d.is_self ? `<circle r="23" fill="none" stroke="var(--violet)" stroke-width="1.4" stroke-dasharray="3 3"/>` : ""}
      <circle class="hv-body" r="18" stroke="${stroke}"/>
      <circle r="14" fill="${meta.color}" fill-opacity="${d.online ? 0.16 : 0.05}"/>
      <use href="#i-${meta.symbol}" x="-10" y="-10" width="20" height="20" color="${d.online ? meta.color : "var(--muted)"}" stroke="currentColor" fill="none" stroke-width="2"/>
      ${d.restricted ? `<circle cx="13" cy="-13" r="5.5" fill="var(--red)" stroke="var(--panel-solid)" stroke-width="1.5"/>` : d.online ? `<circle cx="13" cy="13" r="4" fill="var(--mint)" stroke="var(--panel-solid)" stroke-width="1.5"/>` : ""}
      ${withLabels ? `<text class="hv-label" y="33">${esc(truncate(d.is_self ? "Bu PC" : d.display_name, 13))}</text>` : ""}
    </g>`);
  });

  // İnternet → modem hattı
  const inetColor = online ? "var(--cyan-light)" : "var(--red)";
  const inetPath = `M ${cx} 41 L ${cx} ${cy - 32}`;
  const inetPackets = online
    ? [0, 1, 2].slice(0, 1 + Math.min(level, 2)).map((k) =>
        `<circle class="hv-packet" r="2.4" fill="var(--cyan-light)"><animateMotion dur="${(pktDur * 0.7).toFixed(2)}s" begin="-${(k * pktDur * 0.7 / 3).toFixed(2)}s" repeatCount="indefinite" path="${inetPath}"/></circle>`).join("")
    : `<g transform="translate(${cx}, ${(41 + cy - 32) / 2})"><circle r="7" fill="var(--panel-solid)" stroke="var(--red)" stroke-width="1.5"/><path d="M-3 -3 3 3M3 -3-3 3" stroke="var(--red)" stroke-width="1.6" stroke-linecap="round"/></g>`;

  const extra = devices.length - shown.length;
  const empty = !shown.length
    ? `<text class="hv-empty" x="${cx}" y="${cy + 105}">${state.scanning ? "Cihazlar aranıyor…" : "Cihazları görmek için ağı tarayın"}</text>`
    : "";

  svg.innerHTML = `
    <defs>
      <linearGradient id="hv-core-grad" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stop-color="var(--mint)"/><stop offset="100%" stop-color="var(--cyan)"/>
      </linearGradient>
    </defs>
    <ellipse class="hv-ring outer" cx="${cx}" cy="${cy}" rx="208" ry="180"/>
    <ellipse class="hv-ring" cx="${cx}" cy="${cy}" rx="${HV.outer[0]}" ry="${HV.outer[1]}"/>
    <ellipse class="hv-ring inner" cx="${cx}" cy="${cy}" rx="${HV.inner[0]}" ry="${HV.inner[1]}"/>
    <path d="${inetPath}" stroke="${inetColor}" stroke-width="1.6" ${online ? 'stroke-opacity="0.5"' : 'stroke-dasharray="4 3"'} fill="none"/>
    ${links.join("")}
    ${packets.join("")}
    ${inetPackets}
    <g class="hv-inet" transform="translate(${cx}, 24)">
      <title>İnternet: ${online ? "Bağlı" : "Bağlantı yok"}</title>
      <circle r="17" fill="var(--panel-solid)" stroke="${inetColor}" stroke-width="1.8"/>
      <use href="#i-globe" x="-10" y="-10" width="20" height="20" color="${inetColor}" stroke="currentColor" fill="none" stroke-width="2"/>
    </g>
    <circle class="hv-pulse" cx="${cx}" cy="${cy}" r="34" stroke-width="1.2"/>
    <circle class="hv-pulse p2" cx="${cx}" cy="${cy}" r="34" stroke-width="1.2"/>
    <g class="hv-core" data-hv-router="1" style="cursor:pointer">
      <title>${esc(net.gateway ? `Yönlendirici • ${net.gateway}` : "Yönlendirici")}</title>
      <rect class="hv-core-body" x="${cx - 31}" y="${cy - 31}" width="62" height="62" rx="18" fill="url(#hv-core-grad)"/>
      <use href="#i-router" x="${cx - 16}" y="${cy - 16}" width="32" height="32" color="#03141f" stroke="currentColor" fill="none" stroke-width="2"/>
    </g>
    ${nodes.join("")}
    ${extra > 0 ? `<text class="hv-label" x="${cx + 200}" y="${cy + 182}" text-anchor="end">+${extra} cihaz</text>` : ""}
    ${empty}
  `;
}

function renderHeroCaption() {
  const cap = $("#hero-radar-caption");
  if (!cap) return;
  const counts = state.counts || {};
  const s = (state.status && state.status.stats) || {};
  cap.innerHTML = `<span><b>${counts.online || 0}</b>/${counts.total || 0} çevrimiçi</span>
    <span class="dn">↓ ${fmtMbps(s.rx_bps)} Mb/s</span>
    <span class="up">↑ ${fmtMbps(s.tx_bps)} Mb/s</span>`;
}

function drawTrafficChart() {
  const canvas = $("#traffic-chart");
  if (!canvas) return;
  const wrap = canvas.parentElement;
  const dpr = window.devicePixelRatio || 1;
  const width = wrap.clientWidth;
  const height = wrap.clientHeight;
  if (!width || !height) return;
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const samples = state.trafficSamples || [];
  const pad = { left: 44, right: 8, top: 10, bottom: 22 };
  const w = width - pad.left - pad.right;
  const h = height - pad.top - pad.bottom;
  const maxVal = Math.max(1, ...samples.map((s) => Math.max(s.rx_bps || 0, s.tx_bps || 0)));
  const niceMax = niceCeil(maxVal);

  ctx.font = "10px Segoe UI, sans-serif";
  ctx.fillStyle = "#64748b";
  ctx.strokeStyle = "rgba(148,163,184,0.09)";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = pad.top + (h * i) / 4;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(width - pad.right, y);
    ctx.stroke();
    const value = niceMax * (1 - i / 4);
    ctx.fillText(fmtAxis(value), 4, y + 3);
  }

  if (samples.length < 2) {
    ctx.fillStyle = "#64748b";
    ctx.textAlign = "center";
    ctx.fillText("Trafik verisi toplanıyor…", width / 2, height / 2);
    ctx.textAlign = "left";
    return;
  }

  const xFor = (i) => pad.left + (w * i) / (samples.length - 1);
  const yFor = (v) => pad.top + h - (Math.min(v, niceMax) / niceMax) * h;

  // İndirme alanı
  const grad = ctx.createLinearGradient(0, pad.top, 0, pad.top + h);
  grad.addColorStop(0, "rgba(61,220,151,0.32)");
  grad.addColorStop(1, "rgba(61,220,151,0.01)");
  ctx.beginPath();
  samples.forEach((s, i) => { const x = xFor(i), y = yFor(s.rx_bps || 0); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
  ctx.lineTo(xFor(samples.length - 1), pad.top + h);
  ctx.lineTo(xFor(0), pad.top + h);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();

  drawLine(ctx, samples, "rx_bps", xFor, yFor, "#3ddc97", 2);
  drawLine(ctx, samples, "tx_bps", xFor, yFor, "#8b5cf6", 1.6);

  ctx.fillStyle = "#64748b";
  const labels = [0, Math.floor(samples.length / 2), samples.length - 1];
  ctx.textAlign = "center";
  labels.forEach((idx) => {
    const s = samples[idx];
    if (s) ctx.fillText(fmtClock(s.ts), Math.min(width - 18, Math.max(pad.left + 14, xFor(idx))), height - 4);
  });
  ctx.textAlign = "left";
}

function drawLine(ctx, samples, key, xFor, yFor, color, lineWidth) {
  ctx.beginPath();
  samples.forEach((s, i) => { const x = xFor(i), y = yFor(s[key] || 0); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
  ctx.strokeStyle = color;
  ctx.lineWidth = lineWidth;
  ctx.lineJoin = "round";
  ctx.stroke();
}

function niceCeil(value) {
  if (value <= 1e3) return 1e3;
  const exp = Math.pow(10, Math.floor(Math.log10(value)));
  const norm = value / exp;
  const nice = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10;
  return nice * exp;
}

function fmtAxis(bps) {
  if (bps >= 1e6) return `${(bps / 1e6).toFixed(bps >= 1e7 ? 0 : 1)} Mb`;
  if (bps >= 1e3) return `${(bps / 1e3).toFixed(0)} Kb`;
  return `${Math.round(bps)} b`;
}

async function loadTraffic() {
  if (state.trafficRange === 0) {
    state.trafficSamples = ((state.status && state.status.stats && state.status.stats.samples) || []).slice(-160);
    drawTrafficChart();
    return;
  }
  try {
    const data = await api(`/api/traffic?minutes=${state.trafficRange}`);
    state.trafficSamples = (data.samples || []).slice(-240);
    drawTrafficChart();
  } catch { /* sessiz */ }
}

/* -------------------------------------------------------------------------- */
/* Ağ haritası                                                                */
/* -------------------------------------------------------------------------- */
/* -------------------------------------------------------------------------- */
/* Ağ haritası — canlı görünüm                                                */
/* -------------------------------------------------------------------------- */
function computeLayout(count, cx, cy) {
  const positions = [];
  if (count <= 0) return positions;

  if (count === 1) {
    positions.push({ x: cx, y: cy + 220, tier: 1 });
    return positions;
  }
  if (count === 2) {
    positions.push({ x: cx - 160, y: cy + 210, tier: 1 });
    positions.push({ x: cx + 160, y: cy + 210, tier: 1 });
    return positions;
  }
  if (count === 3) {
    positions.push({ x: cx - 220, y: cy + 185, tier: 1 });
    positions.push({ x: cx, y: cy + 235, tier: 1 });
    positions.push({ x: cx + 220, y: cy + 185, tier: 1 });
    return positions;
  }
  if (count <= 5) {
    const rx = 300, ry = 225;
    const span = Math.PI * 0.72;
    const start = Math.PI * 0.5 - span / 2;
    for (let i = 0; i < count; i++) {
      const ang = start + (span * i) / (count - 1);
      positions.push({
        x: cx + Math.cos(ang) * rx,
        y: cy + Math.sin(ang) * ry,
        tier: 1,
      });
    }
    return positions;
  }
  if (count <= 12) {
    // İki dengeli ve aralıklı (interleaved) kademe
    const n1 = count <= 7 ? 3 : (count <= 9 ? 4 : 5);
    const n2 = count - n1;
    const r1_x = 250, r1_y = 205;
    const r2_x = 440, r2_y = 365;

    // Kademe 1
    const span1 = Math.PI * 0.58;
    const start1 = Math.PI * 0.5 - span1 / 2;
    for (let i = 0; i < n1; i++) {
      const ang = start1 + (span1 * i) / (n1 - 1);
      positions.push({
        x: cx + Math.cos(ang) * r1_x,
        y: cy + Math.sin(ang) * r1_y,
        tier: 1,
      });
    }

    // Kademe 2 - boşluklara denk gelen açılar
    const span2 = Math.PI * 0.86;
    const start2 = Math.PI * 0.5 - span2 / 2;
    for (let j = 0; j < n2; j++) {
      const ang = start2 + (span2 * j) / (n2 - 1);
      positions.push({
        x: cx + Math.cos(ang) * r2_x,
        y: cy + Math.sin(ang) * r2_y,
        tier: 2,
      });
    }
    return positions;
  }

  // 13+ cihaz: Üç kademeli dağılım
  const n1 = 4;
  const n2 = Math.min(7, Math.ceil((count - n1) * 0.5));
  const n3 = count - n1 - n2;
  const r1_x = 220, r1_y = 175;
  const r2_x = 355, r2_y = 295;
  const r3_x = 475, r3_y = 415;

  const span1 = Math.PI * 0.55;
  const start1 = Math.PI * 0.5 - span1 / 2;
  for (let i = 0; i < n1; i++) {
    const ang = start1 + (span1 * i) / (n1 - 1);
    positions.push({ x: cx + Math.cos(ang) * r1_x, y: cy + Math.sin(ang) * r1_y, tier: 1 });
  }

  const span2 = Math.PI * 0.72;
  const start2 = Math.PI * 0.5 - span2 / 2;
  for (let j = 0; j < n2; j++) {
    const ang = start2 + (span2 * j) / (n2 - 1);
    positions.push({ x: cx + Math.cos(ang) * r2_x, y: cy + Math.sin(ang) * r2_y, tier: 2 });
  }

  const span3 = Math.PI * 0.88;
  const start3 = Math.PI * 0.5 - span3 / 2;
  for (let k = 0; k < n3; k++) {
    const ang = start3 + (span3 * k) / (n3 - 1);
    positions.push({ x: cx + Math.cos(ang) * r3_x, y: cy + Math.sin(ang) * r3_y, tier: 3 });
  }

  return positions;
}

// Telefon: yatay halka yerine dikey ağaç (modem üstte, cihazlar 2 sütun halinde altta)
function computeCompactLayout(count, cx, rY) {
  const positions = [];
  const top = rY + 185;
  const rowGap = 128;
  for (let i = 0; i < count; i++) {
    const row = Math.floor(i / 2);
    const lastAlone = i === count - 1 && count % 2 === 1;
    const x = lastAlone ? cx : cx + (i % 2 === 0 ? -100 : 100);
    positions.push({ x, y: top + row * rowGap, tier: 1 });
  }
  return positions;
}

function renderMap() {
  const svg = $("#network-map");
  if (!svg) return;
  const net = (state.status && state.status.network) || {};
  const gateway = net.gateway || "";
  let routerDevice = state.devices.find((d) => d.ip === gateway);
  if (!routerDevice) routerDevice = state.devices.find((d) => d.type === "router");
  const routerName = routerDevice ? (routerDevice.display_name || routerDevice.name || "Modem") : "Yönlendirici (Modem)";
  const routerId = routerDevice ? routerDevice.id : null;
  const isOnline = !!net.internet;

  const allNodes = state.devices.filter((d) => d !== routerDevice && d.ip !== gateway);

  // Filtre uygulama
  let visibleNodes = allNodes;
  if (state.mapFilter === "online") visibleNodes = allNodes.filter((d) => d.online);
  else if (state.mapFilter === "computer") visibleNodes = allNodes.filter((d) => ["computer", "laptop"].includes(d.type));
  else if (state.mapFilter === "phone") visibleNodes = allNodes.filter((d) => ["phone", "tablet"].includes(d.type));
  else if (state.mapFilter === "printer") visibleNodes = allNodes.filter((d) => d.type === "printer");
  else if (state.mapFilter === "other") visibleNodes = allNodes.filter((d) => !["computer", "laptop", "phone", "tablet", "printer"].includes(d.type));

  const search = (state.mapSearch || "").toLowerCase().trim();

  const compact = isCompact();
  state.mapCompact = compact;
  const rY = 175;
  const W = compact ? 400 : 1040;
  const cx = W / 2;
  const positions = compact
    ? computeCompactLayout(visibleNodes.length, cx, rY)
    : computeLayout(visibleNodes.length, cx, rY);
  const H = compact
    ? (positions.length ? Math.max(...positions.map((p) => p.y)) + 95 : 520)
    : 680;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.style.aspectRatio = compact ? `${W} / ${H}` : "";
  state.mapCenter = { x: W / 2, y: H / 2 };
  const posMap = new Map();
  visibleNodes.forEach((d, i) => { if (positions[i]) posMap.set(d.id, positions[i]); });

  const defs = `<defs>
    <radialGradient id="coreGrad" cx="35%" cy="30%">
      <stop offset="0%" stop-color="#34d399"/><stop offset="100%" stop-color="#059669"/>
    </radialGradient>
    <radialGradient id="netGrad" cx="35%" cy="30%">
      <stop offset="0%" stop-color="#38bdf8"/><stop offset="100%" stop-color="#0284c7"/>
    </radialGradient>
    <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
      <path d="M 40 0 L 0 0 0 40" fill="none" stroke="var(--map-grid)" stroke-width="1"/>
    </pattern>
  </defs>`;

  const rings = [];
  if (compact) {
    // dikey düzende halka yok
  } else if (visibleNodes.length <= 5 && visibleNodes.length > 0) {
    rings.push(`<ellipse class="map-ring" cx="${cx}" cy="${rY}" rx="300" ry="225" />`);
  } else if (visibleNodes.length > 5) {
    rings.push(`<ellipse class="map-ring" cx="${cx}" cy="${rY}" rx="250" ry="205" />`);
    rings.push(`<ellipse class="map-ring" cx="${cx}" cy="${rY}" rx="440" ry="365" />`);
  }

  const links = [];
  // 1. Link: İnternet -> Yönlendirici
  links.push(`<line class="map-link ${isOnline ? "active-link" : ""}" x1="${cx}" y1="88" x2="${cx}" y2="132" stroke="${isOnline ? "var(--mint-light)" : "var(--red)"}" stroke-width="2.5" />`);

  // 2. Linkler: Yönlendirici Hub Tabanı -> Cihaz Üstü (Pürüzsüz Bezier Eğrileri)
  const routerHubBottom = rY + 86;
  visibleNodes.forEach((d) => {
    const pos = posMap.get(d.id);
    if (!pos) return;
    const isLinkActive = d.online && isOnline;
    const strokeColor = d.restricted ? "var(--red)" : (d.online ? "var(--mint)" : "rgba(148, 163, 184, 0.22)");
    const linkClass = d.restricted ? "map-link blocked-link" : (isLinkActive ? "map-link active-link" : "map-link");
    let pathD;
    if (compact) {
      // Dikey düzen: ortadan inen ana hat + cihaza yatay kol (kartların üzerinden geçmez)
      pathD = Math.abs(pos.x - cx) < 1
        ? `M ${cx} ${routerHubBottom} V ${(pos.y - 30).toFixed(1)}`
        : `M ${cx} ${routerHubBottom} V ${pos.y.toFixed(1)} H ${(pos.x + (pos.x < cx ? 30 : -30)).toFixed(1)}`;
    } else {
      const targetY = pos.y - 30;
      const midY = routerHubBottom + (targetY - routerHubBottom) * 0.45;
      pathD = `M ${cx} ${routerHubBottom} C ${cx} ${midY}, ${pos.x.toFixed(1)} ${midY}, ${pos.x.toFixed(1)} ${targetY.toFixed(1)}`;
    }
    links.push(`<path class="${linkClass}" d="${pathD}" stroke="${strokeColor}" />`);
  });

  // 3. İnternet Düğümü (En üstte, tıklanabilir)
  const internetPart = `<g class="map-internet" transform="translate(${cx}, 58)" title="İnternet &amp; Hız Görüntüle">
    <circle class="node-hit" r="44" fill="transparent" />
    <rect class="node-hit" x="-80" y="30" width="160" height="30" rx="8" fill="transparent" />
    <circle r="34" fill="none" stroke="${isOnline ? "var(--cyan-light)" : "var(--red)"}" stroke-opacity="0.22" stroke-width="1.5" />
    <circle class="internet-bg" r="26" fill="var(--panel-solid)" stroke="${isOnline ? "var(--cyan-light)" : "var(--red)"}" stroke-width="2" />
    <circle r="22" fill="url(#netGrad)" fill-opacity="0.22" />
    <use href="#i-globe" x="-13" y="-13" width="26" height="26" color="${isOnline ? "var(--cyan-light)" : "var(--red-light)"}" stroke="currentColor" fill="none" stroke-width="2" />
    <circle cx="18" cy="16" r="5" fill="${isOnline ? "var(--mint)" : "var(--red)"}" stroke="var(--panel-solid)" stroke-width="1.8" />
    <g transform="translate(0, 32)">
      <rect x="-75" y="0" width="150" height="28" rx="8" class="map-label-bg" />
      <text x="0" y="18" class="map-internet-label">İnternet: ${isOnline ? "Çevrimiçi" : "Bağlantı Yok"}</text>
    </g>
  </g>`;

  // 4. Yönlendirici (Ağ Geçidi) Düğümü (Merkez, tıklanabilir)
  const routerPart = `<g class="map-center" data-map-device="${routerId ?? ""}" transform="translate(${cx}, ${rY})" title="Yönlendiriciyi Görüntüle">
    <circle class="node-hit" r="50" fill="transparent" />
    <rect class="node-hit" x="-95" y="42" width="190" height="46" rx="9" fill="transparent" />
    <circle class="center-ripple" r="52" fill="none" stroke="var(--mint)" stroke-opacity="0.2" stroke-width="1.5">
      <animate attributeName="r" values="46;56;46" dur="3s" repeatCount="indefinite"/>
      <animate attributeName="stroke-opacity" values="0.25;0.05;0.25" dur="3s" repeatCount="indefinite"/>
    </circle>
    <circle class="center-outer" r="40" fill="var(--panel-solid)" stroke="var(--mint)" stroke-width="2.5" />
    <circle r="34" fill="url(#coreGrad)" fill-opacity="0.2" />
    <use href="#i-router" x="-16" y="-16" width="32" height="32" color="var(--mint-light)" stroke="currentColor" fill="none" stroke-width="2" />
    <circle cx="26" cy="24" r="6" fill="var(--mint)" stroke="var(--panel-solid)" stroke-width="2" />
    <g transform="translate(0, 44)">
      <rect x="-90" y="0" width="180" height="42" rx="9" class="map-label-bg map-center-card" />
      <text x="0" y="17" class="map-center-label">${esc(truncate(routerName, 18))}</text>
      <text x="0" y="32" class="map-center-sub">${esc(gateway ? `${gateway} • Ağ Geçidi` : "Ağ Geçidi")}</text>
    </g>
  </g>`;

  // 5. Cihaz Düğümleri
  const nodes = [];
  visibleNodes.forEach((d) => {
    const pos = posMap.get(d.id);
    if (!pos) return;
    const meta = typeMeta(d.type);
    const id = d.id;
    const restricted = d.restricted;
    const stroke = restricted ? "var(--red)" : (d.online ? meta.color : "var(--muted-2)");
    const label = truncate(d.display_name, 17);
    const sub = d.ip ? (d.vendor ? `${d.ip} • ${truncate(d.vendor, 8)}` : d.ip) : (d.online ? "Çevrimiçi" : "Çevrimdışı");

    const isMatch = !search ||
      d.display_name.toLowerCase().includes(search) ||
      (d.ip && d.ip.includes(search)) ||
      (d.vendor && d.vendor.toLowerCase().includes(search));

    nodes.push(`<g class="map-node ${isMatch ? (search ? "highlighted" : "") : "dimmed"}" data-map-device="${id}" transform="translate(${pos.x.toFixed(1)},${pos.y.toFixed(1)})">
      <!-- Sabit Fare Temas Alanı (Titremeyi 100% Önler) -->
      <rect class="node-hit" x="-75" y="-34" width="150" height="114" rx="14" fill="transparent" />

      <!-- Çevrimiçi Düğüm Halka Efekti -->
      ${d.online ? `<circle r="34" fill="none" stroke="${meta.color}" stroke-opacity="0.25" stroke-width="1.5"><animate attributeName="r" values="30;38;30" dur="2.8s" repeatCount="indefinite"/><animate attributeName="stroke-opacity" values="0.3;0.05;0.3" dur="2.8s" repeatCount="indefinite"/></circle>` : ""}

      <!-- Düğüm Arka Plan Gövdesi -->
      <circle class="node-bg" r="28" fill="var(--panel-solid)" stroke="${stroke}" stroke-width="${d.online ? "2.2" : "1.4"}"/>
      <circle r="23" fill="${meta.color}" fill-opacity="${d.online ? 0.16 : 0.05}"/>

      <!-- Cihaz İkonu -->
      <use href="#i-${meta.symbol}" x="-12" y="-12" width="24" height="24" color="${d.online ? meta.color : "var(--muted)"}" stroke="currentColor" fill="none" stroke-width="2"/>

      <!-- Durum İndikatörü -->
      ${d.online
        ? `<circle cx="20" cy="18" r="5.5" fill="var(--mint)" stroke="var(--panel-solid)" stroke-width="1.8"/>`
        : `<circle cx="20" cy="18" r="4.5" fill="#64748b" stroke="var(--panel-solid)" stroke-width="1.5"/>`}

      <!-- Rozetler: BU PC & Uyarı -->
      ${d.is_self ? `<g transform="translate(0, -32)"><rect x="-24" y="-7" width="48" height="15" rx="7.5" fill="var(--violet)" stroke="var(--panel-solid)" stroke-width="1"/><text y="4" class="node-badge-text">BU PC</text></g>` : ""}
      ${restricted ? `<g transform="translate(20, -18)"><circle r="7.5" fill="var(--red)" stroke="var(--panel-solid)" stroke-width="1.5"/><text y="3.5" class="node-badge-alert">!</text></g>` : ""}

      <!-- Kristal Netlikte Bilgi Kartı -->
      <g class="node-card" transform="translate(0, 34)">
        <rect x="-70" y="0" width="140" height="38" rx="8" class="map-label-bg"/>
        <text x="0" y="16" class="node-label">${esc(label)}</text>
        <text x="0" y="30" class="node-sub">${esc(sub)}</text>
      </g>
    </g>`);
  });

  let emptyPart = "";
  if (!visibleNodes.length) {
    emptyPart = `<g transform="translate(${cx}, ${H / 2 + 70})">
      <text x="0" y="0" class="map-empty-text">Bu filtreye uygun cihaz bulunamadı.</text>
      <text x="0" y="24" class="node-sub" style="font-size:12px;">Farklı bir kategori seçin veya arama terimini temizleyin.</text>
    </g>`;
  }

  svg.innerHTML = `
    ${defs}
    <rect class="map-bg-grid" width="100%" height="100%" fill="url(#grid)" />
    <g id="map-content">
      ${rings.join("")}
      ${links.join("")}
      ${internetPart}
      ${routerPart}
      ${nodes.join("")}
      ${emptyPart}
    </g>
  `;

  applyMapZoom();

  // Olay Dinleyicileri
  svg.querySelectorAll("[data-map-device]").forEach((node) => {
    const devId = Number(node.dataset.mapDevice);
    if (devId) {
      node.addEventListener("click", () => openDrawer(devId));
    }
  });

  const internetNode = svg.querySelector(".map-internet");
  if (internetNode) {
    internetNode.addEventListener("click", () => showView("internet"));
  }

  $("#map-count").textContent = visibleNodes.length;
  $("#map-subnet").textContent = net.network ? `${net.network}/${net.prefix} • ${net.name}` : "—";

  const types = [...new Set(state.devices.map((d) => d.type))];
  $("#map-legend").innerHTML = types.map((t) => {
    const m = typeMeta(t);
    return `<span><i style="background:${m.color}"></i>${m.label}</span>`;
  }).join("");
}

function truncate(text, max) {
  text = String(text || "");
  return text.length > max ? text.slice(0, max - 1) + "…" : text;
}

function setMapZoom(value) {
  state.mapZoom = Math.max(0.45, Math.min(2.2, value));
  applyMapZoom();
}

function applyMapZoom() {
  const content = $("#map-content");
  if (!content) return;
  const { x: cx, y: cy } = state.mapCenter || { x: 520, y: 340 };
  content.setAttribute(
    "transform",
    `translate(${cx + state.mapPan.x}, ${cy + state.mapPan.y}) scale(${state.mapZoom}) translate(${-cx}, ${-cy})`
  );
}

function resetMap() {
  state.mapZoom = 1;
  state.mapPan = { x: 0, y: 0 };
  applyMapZoom();
}

/* -------------------------------------------------------------------------- */
/* Cihaz tablosu                                                              */
/* -------------------------------------------------------------------------- */
function renderDeviceTable() {
  const tbody = $("#device-tbody");
  if (!tbody) return;
  const filtered = state.devices.filter((d) => {
    if (state.filter === "online" && !d.online) return false;
    if (state.filter === "untrusted" && d.trusted) return false;
    if (state.filter === "restricted" && !d.restricted) return false;
    if (!state.search) return true;
    const haystack = [d.display_name, d.ip, d.mac, d.vendor, d.hostname, typeMeta(d.type).label].join(" ").toLowerCase();
    return haystack.includes(state.search);
  });

  $("#device-empty").classList.toggle("hidden", filtered.length > 0);
  tbody.innerHTML = filtered.map((d) => {
    const meta = typeMeta(d.type);
    const status = d.restricted
      ? `<span class="status-pill restricted"><i></i>Kısıtlı</span>`
      : d.online
        ? `<span class="status-pill online"><i></i>Çevrimiçi</span>`
        : `<span class="status-pill"><i></i>Çevrimdışı</span>`;
    const trust = d.trusted ? `<span class="tag trusted">Güvenilir</span>` : `<span class="tag untrusted">İncelenecek</span>`;
    return `<tr data-device-id="${d.id}">
      <td><div class="dev-name"><div class="dev-avatar ${d.online ? "online" : ""}" style="color:${meta.color}">${typeIcon(d.type)}</div><div><b>${esc(d.display_name)}</b><small>${esc(d.vendor || d.hostname || meta.label)}</small></div></div></td>
      <td class="dev-ip"><b ${d.ip ? copyAttr(d.ip, "IP adresi") : ""}>${esc(d.ip || "—")}</b><small ${d.mac && !isPlaceholderMac(d.mac) ? copyAttr(d.mac, "MAC adresi") : ""}>${esc(d.mac && !isPlaceholderMac(d.mac) ? d.mac : "MAC bilinmiyor")}</small></td>
      <td><span class="tag">${meta.label}</span></td>
      <td>${status}<div style="margin-top:4px">${trust}</div></td>
      <td class="muted">${relTime(d.last_seen)}</td>
      <td><div class="row-actions"><button class="icon-btn" title="Ayrıntılar"><svg viewBox="0 0 24 24"><path d="m9 6 6 6-6 6"/></svg></button></div></td>
    </tr>`;
  }).join("");

  tbody.querySelectorAll("[data-device-id]").forEach((row) => {
    row.addEventListener("click", () => openDrawer(Number(row.dataset.deviceId)));
  });
  $("#nav-device-count").textContent = state.counts.total || "";
}

/* -------------------------------------------------------------------------- */
/* Çekmece                                                                    */
/* -------------------------------------------------------------------------- */
function currentDevice() {
  return state.devices.find((d) => d.id === state.selectedId) || null;
}

function openDrawer(id) {
  state.selectedId = id;
  const device = currentDevice();
  if (!device) return;
  renderDrawer(device);
  $("#device-drawer").classList.add("open");
  $("#drawer-backdrop").classList.add("show");
  $("#device-drawer").setAttribute("aria-hidden", "false");
}

function closeDrawer() {
  $("#device-drawer").classList.remove("open");
  $("#drawer-backdrop").classList.remove("show");
  $("#device-drawer").setAttribute("aria-hidden", "true");
}

function drawerIsOpen() {
  return $("#device-drawer").classList.contains("open");
}

function isPlaceholderMac(mac) {
  return String(mac || "").toLowerCase().startsWith("ip-");
}

// soft: arka plan yenilemesi — kullanıcının yazdığı alanları ve ping sonucunu ezme
function renderDrawer(device, { soft = false } = {}) {
  if (!device) return;
  const meta = typeMeta(device.type);
  const avatar = $("#drawer-avatar");
  avatar.innerHTML = typeIcon(device.type, "avatar-svg");
  avatar.style.color = meta.color;
  avatar.classList.toggle("online", device.online);
  $("#drawer-name").textContent = device.display_name;
  $("#drawer-type").textContent = `${meta.label}${device.vendor ? " • " + device.vendor : ""}`;

  const badges = [];
  badges.push(`<span class="badge ${device.online ? "badge-mint" : "badge-muted"}">${device.online ? "Çevrimiçi" : "Çevrimdışı"}</span>`);
  badges.push(`<span class="badge ${device.trusted ? "badge-mint" : "badge-amber"}">${device.trusted ? "Güvenilir" : "İncelenecek"}</span>`);
  if (device.restricted) badges.push(`<span class="badge badge-red">Kısıtlı</span>`);
  if (device.is_self) badges.push(`<span class="badge badge-violet">Bu bilgisayar</span>`);
  $("#drawer-status").innerHTML = badges.join("");

  const pingRes = $("#drawer-ping-result");
  if (pingRes && !soft) {
    pingRes.textContent = "Test edilmedi";
    pingRes.className = "ping-pill";
  }

  const realMac = device.mac && !isPlaceholderMac(device.mac) ? device.mac : "";
  // [etiket, gösterilen değer, panoya kopyalanacak değer]
  const detail = [
    ["IP adresi", device.ip || "—", device.ip],
    ["MAC adresi", realMac || "Bilinmiyor", realMac],
    ["Üretici", device.vendor || "—", device.vendor && device.vendor !== "Rastgele MAC" ? device.vendor : ""],
    ["Ana bilgisayar", device.hostname || "—", device.hostname],
    ["İlk görülme", fmtDate(device.first_seen), ""],
    ["Son görülme", fmtDate(device.last_seen), ""],
    ["Duraklatma", device.pause_until ? fmtDate(device.pause_until) : "Yok", ""],
    ["Plan", device.schedule ? "Haftalık plan var" : "Yok", ""],
  ];
  $("#drawer-details").innerHTML = detail.map(([k, v, c]) =>
    `<div class="detail-item"><span>${k}</span><b ${c ? copyAttr(c, k) : `title="${esc(v)}"`}>${esc(v)}</b></div>`
  ).join("");

  if (!soft) {
    $("#drawer-edit-name").value = device.name || "";
    $("#drawer-edit-type").innerHTML = Object.entries(TYPE_META).map(([key, m]) => `<option value="${key}" ${key === device.type ? "selected" : ""}>${m.label}</option>`).join("");
    $("#drawer-edit-notes").value = device.notes || "";
  }
  $("#drawer-trusted").checked = !!device.trusted;
  $("#drawer-blocked").checked = !!device.blocked;

  const ports = (device.open_ports || []).map((p) => `<span class="port-pill"><b>${p.port}</b> ${esc(p.service || "")}</span>`);
  $("#drawer-ports").innerHTML = ports.join("") || `<span class="muted" style="font-size:11px">Açık port bulunamadı.</span>`;

  const services = [];
  const svc = device.services || {};
  (svc.mdns || []).forEach((s) => services.push(`<span class="service-pill">${esc(s)}</span>`));
  if (svc.ssdp_name) services.push(`<span class="service-pill">UPnP: ${esc(svc.ssdp_name)}</span>`);
  if (svc.ssdp_model) services.push(`<span class="service-pill">${esc(svc.ssdp_model)}</span>`);
  if (svc.ssdp_manufacturer) services.push(`<span class="service-pill">${esc(svc.ssdp_manufacturer)}</span>`);
  if (svc.mdns_host) services.push(`<span class="service-pill" title="mDNS ters sorgu ile bildirdiği ad">mDNS: ${esc(svc.mdns_host)}</span>`);
  if (svc.netbios) services.push(`<span class="service-pill" title="Windows/NetBIOS adı">NetBIOS: ${esc(svc.netbios)}</span>`);
  if (svc.web_title) services.push(`<span class="service-pill" title="Web arayüzü sayfa başlığı">Web: ${esc(svc.web_title)}</span>`);
  if (!services.length) services.push(`<span class="muted" style="font-size:11px">Servis bilgisi yok.</span>`);
  $("#drawer-services").innerHTML = services.join("");

  const selfOrGateway = device.is_self || (state.status && device.ip === state.status.network.gateway);
  $("#drawer-blocked").disabled = selfOrGateway;
  $$("#device-drawer [data-pause]").forEach((b) => { b.disabled = selfOrGateway; });
  $("#drawer-delete").classList.toggle("hidden", device.is_self);
  renderMergeOptions(device, soft);
}

async function saveDrawer() {
  const device = currentDevice();
  if (!device) return;
  try {
    await api(`/api/devices/${device.id}`, {
      method: "PATCH",
      body: {
        name: $("#drawer-edit-name").value.trim(),
        type: $("#drawer-edit-type").value,
        notes: $("#drawer-edit-notes").value.trim(),
      },
    });
    await refreshDevicesAndAlerts();
    toast("Cihaz güncellendi", "", "success");
  } catch (err) { toast("Güncellenemedi", err.message, "error"); }
}

async function patchDevice(id, fields) {
  try {
    await api(`/api/devices/${id}`, { method: "PATCH", body: fields });
    await refreshDevicesAndAlerts();
    toast("Cihaz güncellendi", "", "success");
  } catch (err) {
    toast("Güncellenemedi", err.message, "error");
    if (state.selectedId === id) renderDrawer(currentDevice(), { soft: true });
  }
}

async function blockDevice(id, blocked) {
  try {
    await api(`/api/devices/${id}/block`, { method: "POST", body: { blocked } });
    await refreshDevicesAndAlerts();
    toast(blocked ? "Cihaz kısıtlandı" : "Kısıtlama kaldırıldı", blocked ? "Yerel erişim engellendi." : "", blocked ? "success" : "info");
  } catch (err) {
    toast("İşlem yapılamadı", err.message, "error", 6000);
    if (state.selectedId === id) renderDrawer(currentDevice(), { soft: true });
  }
}

async function pauseDevice(id, minutes) {
  if (!id) return;
  try {
    const data = await api(`/api/devices/${id}/pause`, { method: "POST", body: { minutes } });
    await refreshDevicesAndAlerts();
    toast(minutes ? "Cihaz duraklatıldı" : "Duraklatma kaldırıldı", minutes ? `${minutes} dakika boyunca yerel erişim kısıtlı.` : "", "success");
    if (state.selectedId === id) renderDrawer(currentDevice(), { soft: true });
    if (state.view === "parental") renderParentalDevices();
    return data;
  } catch (err) { toast("Duraklatılamadı", err.message, "error", 6000); }
}

/* -------------------------------------------------------------------------- */
/* Uyarılar                                                                   */
/* -------------------------------------------------------------------------- */
function alertIcon(kind) {
  const name = ({ new_device: "user", security: "shield", parental: "moon", system: "settings", device: "bolt" })[kind] || "bell";
  return icon(name, "al-icon");
}

function alertRow(alert, compact = false) {
  return `<div class="alert-item ${alert.severity} ${alert.read ? "" : "unread"} ${compact ? "compact" : ""}" data-alert-id="${alert.id}" data-alert-mac="${esc(alert.mac || "")}">
    <div class="ai-icon">${alertIcon(alert.kind)}</div>
    <div class="ai-copy"><b>${esc(alert.title)}</b><p>${esc(alert.message || "")}</p></div>
    <time>${relTime(alert.ts)}</time>
  </div>`;
}

function renderAlertList() {
  const list = $("#alert-list");
  if (!list) return;
  $("#alert-empty").classList.toggle("hidden", state.alerts.length > 0);
  list.innerHTML = state.alerts.map((a) => alertRow(a)).join("");
}

/* -------------------------------------------------------------------------- */
/* Ağ görünümü geçişi                                                         */
/* -------------------------------------------------------------------------- */
function setSidebar(open) {
  const sb = $("#sidebar");
  if (!sb) return;
  sb.classList.toggle("open", !!open);
  const bd = $("#sidebar-backdrop");
  if (bd) bd.classList.toggle("show", !!open);
  document.body.classList.toggle("sidebar-open", !!open);
}

function isCompact() {
  return window.matchMedia("(max-width: 760px)").matches;
}

function activateView(name) {
  if (!PAGE_META[name]) return false;
  state.view = name;
  document.body.dataset.view = name;
  $$(".nav-item, .tab-item[data-view]").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  const more = $("#tab-more");
  if (more) more.classList.toggle("active", (more.dataset.moreViews || "").split(" ").includes(name));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${name}`));
  const [title, sub] = PAGE_META[name];
  $("#page-title").textContent = title;
  $("#page-sub").textContent = sub;
  document.title = name === "dashboard" ? "Network Magic" : `${title} — Network Magic`;
  return true;
}

function showView(name, { updateHash = true, scroll = true } = {}) {
  if (!activateView(name)) return;
  if (updateHash) {
    const hash = name === "dashboard" ? "" : `#${name}`;
    if (location.hash !== hash) {
      history.pushState(null, "", hash || location.pathname + location.search);
    }
  }
  setSidebar(false);
  if (scroll) window.scrollTo({ top: 0, behavior: "smooth" });

  if (name === "map") requestAnimationFrame(renderMap);
  if (name === "dashboard") { requestAnimationFrame(drawTrafficChart); renderDashboard(); }
  if (name === "internet") { loadLatency(); loadOutages(); loadWifi(); loadWifiAnalyzer(); loadSpeeds(); loadPrinters(); }
  if (name === "share") loadShare();
  if (name === "parental") renderParental();
  if (name === "alerts") refreshAlerts();
  if (name === "settings") renderSettings();
}

/* -------------------------------------------------------------------------- */
/* İnternet görünümü                                                          */
/* -------------------------------------------------------------------------- */
async function loadWifi() {
  try {
    const data = await api("/api/wifi");
    state.wifiLoaded = true;
    const wifi = data.status || {};
    const badge = $("#wifi-badge");
    badge.textContent = wifi.connected ? "Bağlı" : "Kablolu";
    badge.className = `badge ${wifi.connected ? "badge-mint" : "badge-muted"}`;
    const current = $("#wifi-current");
    if (wifi.connected) {
      const meta = [wifi.security, wifi.band, wifi.radio].filter(Boolean).map(esc).join(" • ") || "Bağlı ağ";
      const signalBox = wifi.signal != null
        ? `<div class="wifi-signal"><b>%${wifi.signal}</b><small>sinyal</small></div>`
        : "";
      current.innerHTML = `<div class="wc-icon">${icon("wifi", "wc-svg")}</div><div><b>${esc(wifi.ssid || "Wi-Fi")}</b><small>${meta}</small></div>${signalBox}`;
    } else {
      current.innerHTML = `<div class="wc-icon">${icon("plug", "wc-svg")}</div><div><b>Kablolu bağlantı</b><small>Wi-Fi bağlı değil</small></div>`;
    }
    const networks = data.networks || [];
    const restricted = networks.length > 0 && networks.every((n) => !(n.access_points || []).length);
    const emptyText = "Wi-Fi ağı bulunamadı.";
    const rows = networks.slice(0, 15).map((n) => {
      const level = signalLevel(n.signal);
      const parts = [n.auth, (n.bands && n.bands.length ? n.bands.join(" + ") : n.band), n.channel ? `Kanal ${n.channel}` : ""].filter(Boolean);
      if (n.bssids > 1) parts.push(`${n.bssids} yayın noktası`);
      const own = wifi.connected && n.ssid && n.ssid === wifi.ssid;
      return `<div class="wifi-row${own ? " own" : ""}" data-ssid="${esc(n.ssid || "")}"><div class="bars" data-level="${level}"><i></i><i></i><i></i><i></i></div><b ${n.ssid ? copyAttr(n.ssid, "Ağ adı") : ""}>${esc(n.ssid || "(gizli ağ)")}${own ? " <em class=\"muted\">• bağlı</em>" : ""}</b><span class="sec">${parts.map(esc).join(" • ")}</span><small>${(n.access_points || []).length ? `%${n.signal || 0}` : "—"}</small></div>`;
    });
    if (networks.length > 15) rows.push(`<p class="muted" style="font-size:11px;margin-top:6px">+${networks.length - 15} ağ daha</p>`);
    if (restricted) rows.push(`<p class="muted" style="font-size:11px;margin-top:6px">Windows ayrıntılı tarama sonucu vermedi. Konum servisinin ve masaüstü uygulamalarının konum erişiminin açık olduğundan emin olun.</p>`);
    $("#wifi-list").innerHTML = rows.join("") || `<p class="muted" style="font-size:11px">${esc(emptyText)}</p>`;
  } catch (err) { toast("Wi-Fi bilgisi alınamadı", err.message, "error"); }
}

async function loadWifiAnalyzer(refresh = false) {
  const body = $("#wifi-analyzer-body");
  const btn = $("#wifi-analyzer-btn");
  if (!body) return;
  if (btn) btn.disabled = true;
  const recDescEl = $("#analyzer-rec-desc");
  if (recDescEl) recDescEl.textContent = "Çevredeki ağlar taranıyor…";

  try {
    const data = await api(`/api/wifi/analyzer${refresh === true ? "?refresh=1" : ""}`);
    const a = data.analysis || {};
    const recTitle = $("#analyzer-rec-title");
    const recDesc = $("#analyzer-rec-desc");
    const recBox = $("#analyzer-rec");

    if (recTitle && recDesc) {
      if (!a.location_restricted) {
        recTitle.textContent = "Spektrum & Yoğunluk Analizi";
        recDesc.textContent = a.recommendation || `En temiz kanallar: 2.4 GHz'de Kanal ${a.best_24}, 5 GHz'de Kanal ${a.best_5}`;
        if (recBox) recBox.className = "analyzer-rec";
      } else {
        recTitle.textContent = a.status && a.status.connected ? `Bağlı: ${a.status.ssid || "Wi-Fi"}` : "Çevredeki Ağlar Taranamadı";
        recDesc.textContent = a.location_restricted
          ? "Windows Konum İzni kapalı olduğu için komşu ağlar listelenemiyor. Çevredeki kanalları taramak için Windows Ayarlarından Konum Servisini açabilirsiniz."
          : a.recommendation;
        if (recBox) recBox.className = "analyzer-rec warning";
      }
    }

    const current = Number(a.current_channel) || 0;
    const renderBars = (wrap, map, isRec, medMax) => {
      const chs = Object.keys(map || {}).map(Number).sort((x, y) => x - y);
      const maxCount = Math.max(1, ...chs.map((ch) => map[ch] || 0));
      wrap.innerHTML = chs.map((ch) => {
        const count = map[ch] || 0;
        const pct = count ? Math.max(8, Math.round((count / maxCount) * 100)) : 4;
        const heat = count === 0 ? "low" : (count <= medMax ? "med" : "high");
        const mine = ch === current;
        const title = `Kanal ${ch}: ${count} yayın noktası${mine ? " • sizin ağınız bu kanalda" : ""}`;
        return `<div class="spec-col ${isRec(ch) ? "recommended" : ""} ${mine ? "current" : ""}" title="${title}">
          <span class="spec-count">${count > 0 ? count : ""}</span>
          <div class="spec-bar-wrap">
            <div class="spec-bar ${heat}" style="height:${pct}%;"></div>
          </div>
          <span class="spec-ch">${ch}</span>
        </div>`;
      }).join("");
    };

    const wrap24 = $("#spectrum-bars-24");
    if (wrap24) renderBars(wrap24, a.channels_24, (ch) => ch === a.best_24, 2);
    const block5 = a.best_5_block || [a.best_5];
    const wrap5 = $("#spectrum-bars-5");
    if (wrap5) renderBars(wrap5, a.channels_5, (ch) => block5.includes(ch), 1);

    const rec24 = $("#spec-24-rec");
    if (rec24 && !a.location_restricted) rec24.textContent = `Önerilen: Kanal ${a.best_24}`;
    const rec5 = $("#spec-5-rec");
    if (rec5 && !a.location_restricted) rec5.textContent = `Önerilen: ${block5[0]}–${block5[block5.length - 1]}`;
  } catch (err) {
    toast("Wi-Fi Analiz Hatası", err.message, "error");
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function loadPrinters() {
  const wrap = $("#printer-list");
  wrap.innerHTML = `<p class="muted" style="font-size:11.5px">Yükleniyor…</p>`;
  try {
    const data = await api("/api/printers");
    const printers = data.printers || [];
    wrap.innerHTML = printers.map((p) => `<div class="printer-row"><div class="p-ico">${icon("printer", "p-svg")}</div><div><b>${esc(p.name)}</b><small>${esc(p.driver || p.port || "")}</small></div><span class="badge ${p.shared ? "badge-mint" : "badge-muted"}">${p.shared ? "Paylaşımlı" : "Yerel"}</span></div>`).join("") || `<p class="muted" style="font-size:11.5px">Yazıcı bulunamadı.</p>`;
  } catch (err) {
    wrap.innerHTML = `<p class="muted" style="font-size:11.5px">Yazıcılar listelenemedi.</p>`;
  }
}

async function loadSpeeds() {
  try {
    const data = await api("/api/speedtest");
    if (data.result) { state.speed = data.result; renderSpeed(); }
  } catch { /* sessiz */ }
}

async function runSpeedtest() {
  const btn = $("#speedtest-btn");
  btn.disabled = true;
  $(".speed-card").classList.add("speed-running");
  $("#speed-status").textContent = "Test ediliyor…";
  $("#speed-status").className = "badge badge-amber";
  try {
    const data = await api("/api/speedtest/run", { method: "POST", body: {} });
    state.speed = data.result;
    renderSpeed();
    toast("Hız testi tamamlandı", `${data.result.download_mbps ?? "—"} Mb/s indirme`, "success");
  } catch (err) {
    toast("Hız testi başarısız", err.message, "error", 6000);
    $("#speed-status").textContent = "Hata";
    $("#speed-status").className = "badge badge-red";
  } finally {
    btn.disabled = false;
    $(".speed-card").classList.remove("speed-running");
  }
}

function renderSpeed() {
  const s = state.speed;
  if (!s) return;
  const dl = s.download_mbps;
  $("#speed-download").textContent = dl != null ? dl : "—";
  $("#speed-dl").textContent = dl != null ? dl : "—";
  $("#speed-ul").textContent = s.upload_mbps != null ? s.upload_mbps : "—";
  $("#speed-ping").textContent = s.ping_ms != null ? s.ping_ms : "—";
  $("#speed-jitter").textContent = s.jitter_ms != null ? s.jitter_ms : "—";
  $("#speed-ip").textContent = `Genel IP: ${s.public_ip || "—"}`;
  setCopy($("#speed-ip"), s.public_ip, "Genel IP");
  $("#speed-time").textContent = s.tested_at ? `${fmtDate(s.tested_at)} tarihinde test edildi` : "";
  $("#speed-status").textContent = dl != null ? "Tamamlandı" : "Kısmi";
  $("#speed-status").className = `badge ${dl != null ? "badge-mint" : "badge-amber"}`;
  const pct = dl != null ? Math.max(2, Math.min(100, (dl / 500) * 100)) : 0;
  $("#speed-gauge").style.setProperty("--pct", pct.toFixed(1));
}

async function runRepair(action) {
  const out = $("#repair-output");
  out.classList.remove("hidden");
  out.textContent = "İşlem çalıştırılıyor…";
  try {
    const data = await api("/api/repair", { method: "POST", body: { action } });
    out.textContent = `${data.message}\n\n${data.output || ""}`.trim();
    toast(data.ok ? "İşlem tamamlandı" : "İşlem başarısız", data.message, data.ok ? "success" : "error", 6000);
  } catch (err) {
    out.textContent = err.message;
    toast("İşlem başarısız", err.message, "error");
  }
}

/* -------------------------------------------------------------------------- */
/* Bağlantı kalitesi (Wi-Fi mı, sağlayıcı mı?) & kesinti geçmişi              */
/* -------------------------------------------------------------------------- */
function fmtDuration(seconds) {
  seconds = Math.max(0, Math.round(Number(seconds) || 0));
  if (seconds < 60) return `${seconds} sn`;
  const m = Math.floor(seconds / 60), s = seconds % 60;
  if (m < 60) return s && m < 10 ? `${m} dk ${s} sn` : `${m} dk`;
  const h = Math.floor(m / 60), mm = m % 60;
  if (h < 24) return mm ? `${h} sa ${mm} dk` : `${h} sa`;
  const d = Math.floor(h / 24), hh = h % 24;
  return hh ? `${d} gün ${hh} sa` : `${d} gün`;
}

function fmtMs(v) {
  return v == null ? "—" : `${Number(v) < 10 ? Number(v).toFixed(1).replace(".0", "") : Math.round(v)} ms`;
}

async function loadLatency() {
  state.latencyAt = Date.now();
  try {
    const data = await api(`/api/latency?minutes=${state.latencyRange || 60}`);
    state.latency = data;
    renderLatency();
  } catch { /* sessiz */ }
}

function renderLatency() {
  const data = state.latency;
  if (!data) return;
  const v = data.verdict || {};
  const box = $("#latency-verdict");
  if (box) box.className = `verdict ${v.code || ""}`;
  const title = $("#latency-verdict-title");
  if (title) title.textContent = v.title || "—";
  const text = $("#latency-verdict-text");
  if (text) text.textContent = v.text || "";
  const rec = data.recent || {};
  const sum = data.summary || {};
  const describe = (s) => {
    if (!s || !s.count) return "Veri yok";
    const parts = [];
    if (s.avg != null) parts.push(`ort. ${fmtMs(s.avg)}`);
    if (s.p95 != null) parts.push(`%95: ${fmtMs(s.p95)}`);
    if (s.jitter != null) parts.push(`titreşim ${fmtMs(s.jitter)}`);
    parts.push(`kayıp %${s.loss ?? 0}`);
    return parts.join(" • ");
  };
  const last = (key) => {
    const arr = data.samples || [];
    for (let i = arr.length - 1; i >= 0; i--) if (arr[i][key] != null) return arr[i][key];
    return null;
  };
  const gwNow = rec.gw && rec.gw.avg != null ? rec.gw.avg : last("gw_ms");
  const inetNow = rec.inet && rec.inet.avg != null ? rec.inet.avg : last("inet_ms");
  $("#lat-gw-now").textContent = fmtMs(gwNow);
  $("#lat-inet-now").textContent = fmtMs(inetNow);
  $("#lat-gw-sum").textContent = describe(sum.gw);
  $("#lat-inet-sum").textContent = describe(sum.inet);
  drawLatencyChart();
}

function drawLatencyChart() {
  const canvas = $("#latency-chart");
  const data = state.latency;
  if (!canvas || !data) return;
  const wrap = canvas.parentElement;
  const dpr = window.devicePixelRatio || 1;
  const width = wrap.clientWidth, height = wrap.clientHeight;
  if (!width || !height) return;
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const samples = data.samples || [];
  const pad = { left: 44, right: 8, top: 10, bottom: 24 };
  const w = width - pad.left - pad.right, h = height - pad.top - pad.bottom;
  const vals = samples.flatMap((s) => [s.gw_ms, s.inet_ms]).filter((v) => v != null).sort((a, b) => a - b);
  // Tek bir uç değer tüm grafiği ezmesin: %98'lik dilime göre ölçekle
  const ref = vals.length ? vals[Math.min(vals.length - 1, Math.floor(vals.length * 0.98))] : 10;
  const steps = [4, 8, 20, 40, 80, 200, 400, 800, 2000]; // 4'e bölünebilir: eksen değerleri tam sayı
  const maxMs = steps.find((s) => s >= ref * 1.15) || 2000;

  ctx.font = "10px Segoe UI, sans-serif";
  ctx.strokeStyle = "rgba(148,163,184,0.10)";
  ctx.fillStyle = "#64748b";
  for (let i = 0; i <= 4; i++) {
    const y = pad.top + (h * i) / 4;
    ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(width - pad.right, y); ctx.stroke();
    ctx.fillText(`${Math.round(maxMs * (1 - i / 4))} ms`, 2, y + 3);
  }
  if (samples.length < 2) {
    ctx.textAlign = "center";
    ctx.fillText("Gecikme ölçümleri toplanıyor…", width / 2, height / 2);
    ctx.textAlign = "left";
    return;
  }
  const xFor = (i) => pad.left + (w * i) / (samples.length - 1);
  const yFor = (v) => pad.top + h - (Math.min(v, maxMs) / maxMs) * h;
  const series = (key, color, lw) => {
    ctx.beginPath();
    let drawing = false;
    samples.forEach((s, i) => {
      const v = s[key];
      if (v == null) { drawing = false; return; }
      const x = xFor(i), y = yFor(v);
      if (drawing) ctx.lineTo(x, y); else { ctx.moveTo(x, y); drawing = true; }
    });
    ctx.strokeStyle = color; ctx.lineWidth = lw; ctx.lineJoin = "round"; ctx.stroke();
  };
  series("gw_ms", "#38bdf8", 1.6);
  series("inet_ms", "#34d399", 2);
  // Yanıt alınamayan ölçümler (veya dakikalık kayıp) kırmızı çizgiyle
  ctx.fillStyle = "rgba(244,63,94,0.85)";
  samples.forEach((s, i) => {
    const lost = s.inet_ms == null || s.gw_ms == null || (s.inet_loss || 0) > 0 || (s.gw_loss || 0) > 0;
    if (lost) ctx.fillRect(xFor(i) - 1, pad.top + h - 4, 2.5, 6);
  });
  ctx.fillStyle = "#64748b";
  ctx.textAlign = "center";
  const multiDay = (state.latencyRange || 60) > 1440;
  [0, Math.floor(samples.length / 2), samples.length - 1].forEach((idx) => {
    const s = samples[idx];
    if (!s) return;
    const d = new Date(s.ts);
    const label = multiDay ? d.toLocaleDateString("tr-TR", { day: "2-digit", month: "short" }) : fmtClock(s.ts);
    ctx.fillText(label, Math.min(width - 22, Math.max(pad.left + 16, xFor(idx))), height - 6);
  });
  ctx.textAlign = "left";
}

async function loadOutages() {
  state.outagesAt = Date.now();
  try {
    state.outages = await api(`/api/outages?days=${state.outageRange || 30}`);
    renderOutages();
  } catch { /* sessiz */ }
}

const CAUSE_LABEL = {
  isp: ["Servis sağlayıcı", "badge-amber", "Modeme erişim vardı, internete çıkılamadı"],
  local: ["Wi-Fi / yerel ağ", "badge-violet", "Modeme de ulaşılamadı"],
  unknown: ["Bilinmiyor", "badge-muted", ""],
};

function renderOutages() {
  const data = state.outages;
  if (!data) return;
  const s = data.summary || {};
  const tiles = [
    ["Kesinti", `${s.count || 0}`, s.count ? `${s.isp_count || 0} sağlayıcı • ${s.local_count || 0} yerel` : "Bu dönemde kesinti yok"],
    ["Toplam süre", fmtDuration(s.total_s), s.ongoing ? "Şu an kesinti sürüyor" : `son ${data.days} gün`],
    ["En uzun", s.longest_s ? fmtDuration(s.longest_s) : "—", s.longest_s ? "tek kesinti" : "kesinti yok"],
    ["Erişilebilirlik", s.uptime_pct == null ? "—" : `%${s.uptime_pct}`, s.monitored_s ? `${fmtDuration(s.monitored_s)} izlendi` : "henüz izleme verisi yok"],
  ];
  $("#outage-stats").innerHTML = tiles.map(([label, value, sub], i) =>
    `<div class="o-stat ${i === 0 && s.count ? "warn" : ""} ${i === 3 && s.uptime_pct != null && s.uptime_pct < 99 ? "warn" : ""}"><span>${label}</span><strong>${esc(value)}</strong><small>${esc(sub)}</small></div>`
  ).join("");

  const days = data.daily || [];
  const maxDown = Math.max(1, ...days.map((d) => d.down_s));
  $("#outage-days").innerHTML = days.map((d) => {
    const pct = d.down_s ? Math.max(14, Math.round((d.down_s / maxDown) * 100)) : 100;
    const date = new Date(`${d.date}T12:00:00`);
    const label = date.toLocaleDateString("tr-TR", { day: "2-digit", month: "short", weekday: "short" });
    const title = d.count ? `${label}: ${d.count} kesinti, ${fmtDuration(d.down_s)}` : `${label}: kesinti yok`;
    return `<div class="o-day ${d.count ? "bad" : "ok"}" title="${esc(title)}"><i style="height:${pct}%"></i></div>`;
  }).join("");

  const list = data.outages || [];
  if (!list.length) {
    $("#outage-list").innerHTML = `<div class="outage-empty">${icon("check", "o-empty-ico")}<div><b>Kesinti kaydedilmedi</b><small>Network Magic açıkken internet bağlantınız ${data.days} gün boyunca hiç kopmadı. Kesintiler 15 saniyede bir yapılan kontrollerle algılanır.</small></div></div>`;
    return;
  }
  $("#outage-list").innerHTML = list.slice(0, 25).map((o) => {
    const [label, cls, hint] = CAUSE_LABEL[o.cause] || CAUSE_LABEL.unknown;
    const start = new Date(o.started);
    const end = o.ended ? new Date(o.ended) : null;
    const when = start.toLocaleString("tr-TR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
    const until = end ? end.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" }) : "sürüyor";
    return `<div class="outage-row ${o.ongoing ? "ongoing" : ""}">
      <div class="o-when"><b>${esc(when)}</b><small>– ${esc(until)}</small></div>
      <div class="o-dur">${esc(fmtDuration(o.duration_s))}</div>
      <span class="badge ${cls}" title="${esc(hint)}">${esc(label)}</span>
    </div>`;
  }).join("");
}

function outageReportText() {
  const data = state.outages;
  if (!data) return "";
  const s = data.summary || {};
  const fmt = (iso) => new Date(iso).toLocaleString("tr-TR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
  const from = new Date(Date.now() - data.days * 86400000).toLocaleDateString("tr-TR");
  const to = new Date().toLocaleDateString("tr-TR");
  const lines = [
    "İNTERNET KESİNTİ RAPORU",
    `Dönem: ${from} – ${to} (son ${data.days} gün)`,
    `Toplam kesinti: ${s.count || 0} (servis sağlayıcı kaynaklı: ${s.isp_count || 0}, yerel ağ kaynaklı: ${s.local_count || 0})`,
    `Toplam kesinti süresi: ${fmtDuration(s.total_s)} • En uzun kesinti: ${s.longest_s ? fmtDuration(s.longest_s) : "—"}`,
  ];
  if (s.uptime_pct != null) lines.push(`Erişilebilirlik: %${s.uptime_pct} (izlenen süre: ${fmtDuration(s.monitored_s)})`);
  const lat = state.latency && state.latency.summary;
  if (lat && lat.inet && lat.inet.avg != null) {
    lines.push(`İnternet gecikmesi: ortalama ${fmtMs(lat.inet.avg)}, %95: ${fmtMs(lat.inet.p95)}, paket kaybı %${lat.inet.loss}`);
  }
  const isp = (data.outages || []).filter((o) => o.cause === "isp");
  if (isp.length) {
    lines.push("", "Servis sağlayıcı kaynaklı kesintiler (modeme erişim varken internete çıkılamadı):");
    isp.slice(0, 50).forEach((o) => {
      lines.push(`- ${fmt(o.started)} → ${o.ended ? fmt(o.ended) : "devam ediyor"} (${fmtDuration(o.duration_s)})`);
    });
  }
  const local = (data.outages || []).filter((o) => o.cause !== "isp");
  if (local.length) {
    lines.push("", "Diğer kesintiler (yerel ağ / Wi-Fi / bilinmeyen):");
    local.slice(0, 30).forEach((o) => {
      lines.push(`- ${fmt(o.started)} → ${o.ended ? fmt(o.ended) : "devam ediyor"} (${fmtDuration(o.duration_s)})`);
    });
  }
  lines.push("", "Ölçüm: Network Magic, 15 saniyede bir internet erişim kontrolü ve 10 saniyede bir modem/internet gecikme ölçümü.");
  return lines.join("\n");
}

/* -------------------------------------------------------------------------- */
/* Cihaz birleştirme (rastgele MAC)                                           */
/* -------------------------------------------------------------------------- */
function renderMergeOptions(device, soft) {
  const section = $("#drawer-merge-section");
  const select = $("#drawer-merge-select");
  if (!section || !select) return;
  const gw = state.status && state.status.network && state.status.network.gateway;
  const others = state.devices
    .filter((d) => d.id !== device.id && !d.is_self && d.ip !== gw)
    .sort((a, b) => (b.random_mac - a.random_mac) || (a.online - b.online) || String(a.display_name).localeCompare(String(b.display_name), "tr"));
  const hide = device.is_self || device.ip === gw || !others.length;
  section.classList.toggle("hidden", hide);
  if (hide) return;
  const keep = soft ? select.value : "";
  select.innerHTML = `<option value="">Kayıt seçin…</option>` + others.map((d) => {
    const status = d.online ? "çevrimiçi" : `çevrimdışı, ${relTime(d.last_seen)}`;
    const tag = d.random_mac ? " • rastgele MAC" : "";
    return `<option value="${d.id}">${esc(truncate(d.display_name, 26))} • ${esc(d.ip || "—")} • ${esc(status)}${tag}</option>`;
  }).join("");
  if (keep && others.some((d) => String(d.id) === keep)) select.value = keep;
}

function mergeSelectedDevice() {
  const device = currentDevice();
  const select = $("#drawer-merge-select");
  const intoId = Number(select && select.value);
  if (!device || !intoId) { toast("Kayıt seçin", "Birleştirilecek eski kaydı listeden seçin.", "info"); return; }
  const target = state.devices.find((d) => d.id === intoId);
  if (!target) return;
  confirmDialog(
    "Kayıtları birleştir",
    `<b>${esc(device.display_name)}</b> (${esc(device.ip || "—")}) ile <b>${esc(target.display_name)}</b> aynı cihaz olarak işaretlenecek.<br><br>
     <b>${esc(target.display_name)}</b> kaydının adı, notu, güven durumu ve ebeveyn kontrolü ayarları korunur; MAC/IP bilgisi güncel olanla değiştirilir. Diğer kayıt silinir.`,
    "Birleştir",
    async () => {
      const data = await api(`/api/devices/${device.id}/merge`, { method: "POST", body: { into: intoId } });
      await refreshDevicesAndAlerts();
      if (data.device) openDrawer(data.device.id);
      toast("Kayıtlar birleştirildi", data.device ? data.device.display_name : "", "success");
    }
  );
}

/* -------------------------------------------------------------------------- */
/* Paylaşım                                                                   */
/* -------------------------------------------------------------------------- */
async function loadShare() {
  try {
    const data = await api("/api/share");
    state.shareLoaded = true;
    renderShare(data);
  } catch (err) { toast("Paylaşım bilgisi alınamadı", err.message, "error"); }
}

function renderShare(data) {
  const files = data.files || [];
  const usage = data.usage || {};
  const url = data.url || "";
  state.shareBase = url.replace(/\/share$/, "");
  $("#share-url-badge").textContent = state.shareBase || "—";
  setCopy($("#share-url-badge"), state.shareBase, "Adres");
  $("#share-address").textContent = state.shareBase;
  setCopy($("#share-address"), state.shareBase, "Adres");
  $("#share-file-count").textContent = `${files.length} dosya • ${fmtBytes(usage.bytes || 0)}`;
  $("#share-usage").innerHTML = `<div style="flex:1"><div style="display:flex;justify-content:space-between"><span>Kullanılan alan</span><b>${fmtBytes(usage.bytes || 0)}</b></div><div class="usage-bar"><i style="width:${Math.min(100, ((usage.bytes || 0) / (usage.disk_total || 1)) * 100)}%"></i></div></div><div>Boş alan: <b>${fmtBytes(usage.disk_free || 0)}</b></div>`;

  $("#share-empty").classList.toggle("hidden", files.length > 0);
  $("#share-tbody").innerHTML = files.map((f) => `<tr data-share-file="${esc(f.name)}">
    <td><div class="dev-name"><div class="dev-avatar">${icon("document")}</div><div><b ${copyAttr(shareLink(f.name), "Dosya bağlantısı")}>${esc(f.name)}</b><small>${esc(f.name.split(".").pop().toUpperCase())}</small></div></div></td>
    <td>${fmtBytes(f.size)}</td>
    <td class="muted">${fmtDate(f.modified)}</td>
    <td><div class="row-actions">
      <button class="icon-btn" data-share-copy="${esc(f.name)}" title="Bağlantıyı kopyala"><svg viewBox="0 0 24 24"><path d="M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1"/><path d="M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1"/></svg></button>
      <button class="icon-btn" data-share-qr="${esc(f.name)}" title="QR kod — telefonla okutup indirin"><svg viewBox="0 0 24 24"><rect x="3.5" y="3.5" width="6" height="6" rx="1"/><rect x="14.5" y="3.5" width="6" height="6" rx="1"/><rect x="3.5" y="14.5" width="6" height="6" rx="1"/><path d="M14.5 14.5h2.5v2.5M20.5 14.5v.01M14.5 20.5h.01M17.5 20.5h3v-3"/></svg></button>
      <a class="icon-btn" href="/share/${encodeURIComponent(f.name)}" title="İndir"><svg viewBox="0 0 24 24"><path d="M12 3v12m0 0 4-4m-4 4-4-4"/><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/></svg></a>
      <button class="icon-btn" data-share-delete="${esc(f.name)}" title="Sil"><svg viewBox="0 0 24 24"><path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m-9 0 1 13h10l1-13"/></svg></button>
    </div></td>
  </tr>`).join("");

  $$("[data-share-delete]").forEach((btn) => btn.addEventListener("click", () => deleteSharedFile(btn.dataset.shareDelete)));
  $$("[data-share-copy]").forEach((btn) => btn.addEventListener("click", () => copyText(shareLink(btn.dataset.shareCopy), "Dosya bağlantısı")));
  $$("[data-share-qr]").forEach((btn) => btn.addEventListener("click", () => showQr(shareLink(btn.dataset.shareQr), btn.dataset.shareQr)));

  applyGuestState(data.guest || {}, state.shareBase);
}

// Ağdaki diğer cihazların açabileceği tam adres (LAN IP'si ile)
function shareLink(name) {
  const base = state.shareBase || location.origin;
  return `${base}/share/${encodeURIComponent(name)}`;
}

function deleteSharedFile(name) {
  confirmDialog("Dosyayı sil", `<b>${esc(name)}</b> kalıcı olarak silinecek.`, "Sil", async () => {
    await api(`/api/share/${encodeURIComponent(name)}`, { method: "DELETE" });
    await loadShare();
    toast("Dosya silindi", "", "success");
  }, true);
}

async function showQr(text, title = "") {
  openModal(title ? `QR kod — ${truncate(title, 32)}` : "QR kod", `<div class="qr-modal"><div class="qr-box qr-lg"><span class="muted">Hazırlanıyor…</span></div>
    <p>Telefonun kamerasıyla okutun; bağlantı aynı Wi-Fi ağındaki cihazda açılır.</p>
    <code ${copyAttr(text, "Bağlantı")}>${esc(text)}</code></div>`, [
    { label: "Bağlantıyı kopyala", className: "btn-ghost", onClick: () => copyText(text, "Bağlantı") },
    { label: "Kapat", className: "btn-primary", onClick: hideModal },
  ]);
  try {
    const data = await api(`/api/qr?text=${encodeURIComponent(text)}`);
    const box = $("#modal-body .qr-box");
    if (box) box.innerHTML = data.qr ? `<img src="${data.qr}" alt="QR kod">` : "QR oluşturulamadı.";
  } catch (err) {
    const box = $("#modal-body .qr-box");
    if (box) box.textContent = err.message;
  }
}

async function uploadFiles(fileList) {
  if (!fileList || !fileList.length) return;
  const form = new FormData();
  Array.from(fileList).forEach((f) => form.append("files", f));
  toast("Dosyalar yükleniyor", `${fileList.length} dosya aktarılıyor…`, "info", 2500);
  try {
    await api("/api/share/upload", { method: "POST", body: form });
    await loadShare();
    toast("Yükleme tamamlandı", "", "success");
  } catch (err) { toast("Yükleme başarısız", err.message, "error"); }
  $("#file-input").value = "";
}

function applyGuestState(guest, base = "") {
  $("#guest-toggle").checked = !!guest.enabled;
  const result = $("#guest-result");
  if (guest.enabled && guest.token) {
    const link = `${base || location.origin}/guest/${guest.token}`;
    result.classList.remove("hidden");
    $("#guest-link").value = link;
    $("#guest-expires").textContent = `Son geçerlilik: ${fmtDate(guest.expires)}`;
    fetch(`/api/qr?text=${encodeURIComponent(link)}`).then((r) => r.json()).then((d) => {
      $("#guest-qr").innerHTML = d.qr ? `<img src="${d.qr}" alt="QR">` : "";
    }).catch(() => {});
  } else {
    result.classList.add("hidden");
  }
}

async function applyGuest() {
  const enabled = $("#guest-toggle").checked;
  const hours = Number($("#guest-hours").value) || 24;
  try {
    const data = await api("/api/guest", { method: "POST", body: { enabled, hours } });
    applyGuestState(data.guest, data.link ? data.link.replace(/\/guest\/.*$/, "") : "");
    if (enabled) {
      $("#guest-link").value = data.link;
      $("#guest-qr").innerHTML = data.qr ? `<img src="${data.qr}" alt="QR">` : "";
      $("#guest-expires").textContent = `Son geçerlilik: ${fmtDate(data.guest.expires)}`;
      toast("Misafir bağlantısı hazır", "Bağlantıyı kopyalayarak paylaşabilirsiniz.", "success");
    } else {
      toast("Misafir erişimi kapatıldı", "", "info");
    }
  } catch (err) { toast("İşlem başarısız", err.message, "error"); }
}

/* -------------------------------------------------------------------------- */
/* Tıkla-kopyala                                                              */
/* -------------------------------------------------------------------------- */
// HTML şablonları için: <b ${copyAttr(ip, "IP adresi")}>…</b>
function copyAttr(value, label = "") {
  if (value == null || value === "") return "";
  return `class="copyable" data-copy="${esc(value)}" data-copy-label="${esc(label)}" title="Kopyalamak için tıklayın"`;
}

// Statik öğeler için: görünen metinden bağımsız olarak panoya gidecek değeri ayarlar
function setCopy(el, value, label = "") {
  if (!el) return;
  if (value) {
    el.classList.add("copyable");
    el.dataset.copy = value;
    el.dataset.copyLabel = label;
    el.title = "Kopyalamak için tıklayın";
  } else {
    el.classList.remove("copyable");
    delete el.dataset.copy;
    el.removeAttribute("title");
  }
}

function flashCopied(el) {
  if (!el) return;
  el.classList.remove("copied");
  void el.offsetWidth; // animasyonu yeniden başlat
  el.classList.add("copied");
  setTimeout(() => el.classList.remove("copied"), 900);
}

function copyText(text, label = "") {
  if (!text) return;
  const done = () => toast(label ? `${label} kopyalandı` : "Kopyalandı", truncate(String(text), 60), "success", 1800);
  const fallback = () => {
    // LAN adresinden (http) açıldığında navigator.clipboard yoktur
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch { ok = false; }
    ta.remove();
    if (ok) done(); else toast("Kopyalanamadı", "Bağlantıyı elle seçip kopyalayın.", "error");
  };
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(done).catch(fallback);
  } else {
    fallback();
  }
}

/* -------------------------------------------------------------------------- */
/* Ebeveyn kontrolü                                                           */
/* -------------------------------------------------------------------------- */
function renderParental() {
  const admin = state.status && state.status.app && state.status.app.admin;
  const badge = $("#parental-admin");
  badge.textContent = admin ? "Yönetici etkin" : "Yönetici gerekli";
  badge.className = `badge ${admin ? "badge-mint" : "badge-amber"}`;
  $("#parental-notice").classList.toggle("hidden", !!admin);
  renderParentalDevices();
  const candidates = parentalCandidates();
  const existing = candidates.find((d) => d.id === state.scheduleDeviceId);
  if (!existing) {
    const first = candidates[0];
    if (first) selectScheduleDevice(first.id);
    else { state.scheduleDeviceId = null; state.schedule = null; $("#schedule-title").textContent = "Haftalık Plan"; }
  } else {
    selectScheduleDevice(state.scheduleDeviceId);
  }
}

// Bu bilgisayar ve yönlendirici kısıtlanamaz; listede gösterme
function parentalCandidates() {
  const gw = state.status && state.status.network && state.status.network.gateway;
  return state.devices.filter((d) => !d.is_self && d.ip !== gw);
}

function renderParentalDevices() {
  const wrap = $("#parental-devices");
  const devices = parentalCandidates();
  if (!devices.length) {
    wrap.innerHTML = `<p class="muted" style="font-size:11.5px">Cihaz bulunamadı. Önce ağı tarayın.</p>`;
    return;
  }
  wrap.innerHTML = devices.map((d) => {
    const meta = typeMeta(d.type);
    const flags = [];
    if (d.blocked) flags.push(`<span>Engelli</span>`);
    if (d.schedule) flags.push(`<span>Planlı</span>`);
    return `<div class="p-device ${d.id === state.scheduleDeviceId ? "active" : ""}" data-schedule-device="${d.id}">
      <div class="dev-avatar ${d.online ? "online" : ""}" style="color:${meta.color}">${typeIcon(d.type)}</div>
      <div><b>${esc(d.display_name)}</b><small>${esc(d.ip || "")}</small></div>
      <div class="flags">${flags.join("")}</div>
    </div>`;
  }).join("");
}

function selectScheduleDevice(id) {
  state.scheduleDeviceId = id;
  const device = state.devices.find((d) => d.id === id);
  if (!device) return;
  const allowed = [];
  for (let day = 0; day < 7; day++) {
    if (device.schedule && device.schedule[String(day)]) allowed.push(new Set(device.schedule[String(day)]));
    else allowed.push(new Set([...Array(24).keys()]));
  }
  state.schedule = { deviceId: id, enabled: !!device.schedule, allowed };
  $("#schedule-title").textContent = `${device.display_name} — Haftalık Plan`;
  renderParentalDevices();
  renderScheduleGrid();
  $$("#view-parental [data-pause]").forEach((b) => b.disabled = !!device.is_self || device.ip === (state.status && state.status.network.gateway));
}

function renderScheduleGrid() {
  const grid = $("#schedule-grid");
  if (!grid || !state.schedule) return;
  const days = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"];
  $("#schedule-hours").innerHTML = [...Array(24).keys()].map((h) => `<span>${h}</span>`).join("");
  grid.innerHTML = days.map((day, di) => `<div class="schedule-row"><span>${day}</span><div class="cells">${
    [...Array(24).keys()].map((h) => `<button class="schedule-cell ${state.schedule.allowed[di].has(h) ? "" : "blocked"}" data-day="${di}" data-hour="${h}" title="${day} ${String(h).padStart(2, "0")}:00"></button>`).join("")
  }</div></div>`).join("");
}

function applyPreset(preset) {
  if (!state.schedule) return;
  const all = () => new Set([...Array(24).keys()]);
  if (preset === "all" || preset === "off") {
    state.schedule.allowed = [...Array(7)].map(all);
    state.schedule.enabled = false;
  } else if (preset === "night") {
    state.schedule.allowed = [...Array(7)].map(() => new Set([...Array(24).keys()].filter((h) => h >= 7 && h < 22)));
    state.schedule.enabled = true;
  } else if (preset === "school") {
    state.schedule.allowed = [...Array(7)].map((_, day) => new Set([...Array(24).keys()].filter((h) => (day >= 5 ? true : h < 8 || h >= 16))));
    state.schedule.enabled = true;
  }
  renderScheduleGrid();
}

async function saveSchedule() {
  if (!state.schedule) return;
  const payload = {};
  if (state.schedule.enabled) {
    for (let day = 0; day < 7; day++) payload[String(day)] = [...state.schedule.allowed[day]].sort((a, b) => a - b);
  }
  try {
    await api(`/api/devices/${state.schedule.deviceId}/schedule`, { method: "POST", body: { schedule: state.schedule.enabled ? payload : null } });
    await refreshDevicesAndAlerts();
    toast("Plan kaydedildi", state.schedule.enabled ? "Kısıtlı saatlerde cihazın yerel erişimi kısıtlanacak." : "Kısıtlama kaldırıldı.", "success");
    const device = state.devices.find((d) => d.id === state.scheduleDeviceId);
    if (device) { state.schedule.enabled = !!device.schedule; }
    renderParentalDevices();
  } catch (err) { toast("Plan kaydedilemedi", err.message, "error", 6000); }
}

/* -------------------------------------------------------------------------- */
/* Ayarlar                                                                    */
/* -------------------------------------------------------------------------- */
function renderSettings() {
  if (!state.status) return;
  const settings = state.status.settings || {};
  const form = $("#scan-settings");
  form.device_name.value = settings.device_name || "";
  form.auto_scan.checked = !!settings.auto_scan;
  form.scan_interval_minutes.value = settings.scan_interval_minutes || 10;
  form.subnet_override.value = settings.subnet_override || "";
  form.notify_new.checked = !!settings.notify_new;
  form.allow_lan_control.checked = !!settings.allow_lan_control;
  $("#about-url").textContent = (state.status.app && state.status.app.lan_url) || "—";
  setCopy($("#about-url"), state.status.app && state.status.app.lan_url, "Sunucu adresi");
  $("#about-admin").textContent = state.status.app && state.status.app.admin ? "Evet" : "Hayır";
}

async function saveSettings(e) {
  e.preventDefault();
  const form = e.target;
  try {
    await api("/api/settings", {
      method: "PUT",
      body: {
        device_name: form.device_name.value.trim(),
        auto_scan: form.auto_scan.checked,
        scan_interval_minutes: Number(form.scan_interval_minutes.value),
        subnet_override: form.subnet_override.value.trim(),
        notify_new: form.notify_new.checked,
        allow_lan_control: form.allow_lan_control.checked,
      },
    });
    toast("Ayarlar kaydedildi", "", "success");
    await refreshAll();
  } catch (err) { toast("Ayarlar kaydedilemedi", err.message, "error"); }
}

async function showReport() {
  const out = $("#report-output");
  out.classList.remove("hidden");
  out.textContent = "Rapor hazırlanıyor…";
  try {
    const data = await api("/api/report");
    const traffic = data.traffic_24h || {};
    const types = Object.entries(data.by_type || {}).map(([k, v]) => `${typeMeta(k).label}: ${v}`).join("\n");
    const vendors = (data.top_vendors || []).map(([k, v]) => `${k}: ${v}`).join("\n");
    out.textContent = `NETWORK MAGIC — 24 SAATLİK RAPOR\n${fmtDate(data.generated_at)}\n\nCihazlar: ${data.counts.total} (çevrimiçi ${data.counts.online})\nGüvenilmeyen: ${data.counts.untrusted}\nKısıtlı: ${data.counts.restricted}\nUyarılar: ${data.counts.alerts}\n\nTrafik (24 sa):\n  İndirme: ${fmtBytes(traffic.rx_bytes)} • Yükleme: ${fmtBytes(traffic.tx_bytes)}\n\nCihaz türleri:\n${types || "—"}\n\nÜreticiler:\n${vendors || "—"}`;
  } catch (err) { out.textContent = err.message; }
}

async function showScanHistory() {
  const out = $("#report-output");
  out.classList.remove("hidden");
  try {
    const data = await api("/api/scan/history");
    out.textContent = (data.history || []).map((s) => `${fmtDate(s.started)}  •  ${s.kind === "auto" ? "Otomatik" : "Elle"}  •  ${s.device_count} cihaz  •  ${s.new_count} yeni`).join("\n") || "Henüz tarama kaydı yok.";
  } catch (err) { out.textContent = err.message; }
}

function resetData() {
  const body = `<p>Tüm cihazlar, uyarılar ve trafik geçmişi silinecek. Onaylamak için aşağıya <b>SIFIRLA</b> yazın.</p>
    <label class="field" style="margin-top:12px"><span>Onay</span><input id="reset-confirm" type="text" placeholder="SIFIRLA"></label>`;
  openModal("Tüm verileri sıfırla", body, [
    { label: "Vazgeç", className: "btn-ghost", onClick: hideModal },
    {
      label: "Sıfırla", className: "btn-danger", onClick: async () => {
        const value = ($("#reset-confirm") || {}).value || "";
        if (value.trim().toUpperCase() !== "SIFIRLA") { toast("Onay hatalı", "SIFIRLA yazmalısınız.", "error"); return; }
        try {
          await api("/api/reset", { method: "POST", body: { confirm: "SIFIRLA" } });
          hideModal();
          state.scheduleDeviceId = null;
          await refreshAll();
          toast("Veriler sıfırlandı", "", "success");
        } catch (err) { toast("Sıfırlanamadı", err.message, "error"); }
      },
    },
  ]);
}

/* -------------------------------------------------------------------------- */
/* Modal                                                                      */
/* -------------------------------------------------------------------------- */
function openModal(title, bodyHTML, buttons = []) {
  $("#modal-title").textContent = title;
  $("#modal-body").innerHTML = bodyHTML;
  const foot = $("#modal-foot");
  foot.innerHTML = "";
  buttons.forEach((btn) => {
    const el = document.createElement("button");
    el.className = `btn ${btn.className || "btn-ghost"}`;
    el.textContent = btn.label;
    el.addEventListener("click", btn.onClick);
    foot.appendChild(el);
  });
  $("#modal").classList.remove("hidden");
}

function hideModal() { $("#modal").classList.add("hidden"); }

function confirmDialog(title, message, confirmLabel, onConfirm, danger = false) {
  openModal(title, message, [
    { label: "Vazgeç", className: "btn-ghost", onClick: hideModal },
    {
      label: confirmLabel,
      className: danger ? "btn-danger" : "btn-primary",
      onClick: async () => {
        try { await onConfirm(); hideModal(); }
        catch (err) { toast("İşlem başarısız", err.message, "error"); }
      },
    },
  ]);
}

/* -------------------------------------------------------------------------- */
/* İlk kurulum                                                                */
/* -------------------------------------------------------------------------- */
function maybeOnboard() {
  if (!state.status) return;
  const settings = state.status.settings || {};
  if (!settings.onboarded) {
    $("#onboarding-name").value = settings.device_name || "";
    $("#onboarding").classList.remove("hidden");
  }
}

/* -------------------------------------------------------------------------- */
/* Sağ tık menüsü                                                             */
/* -------------------------------------------------------------------------- */
const CTX_ICONS = {
  open: '<path d="M4 12h16M14 6l6 6-6 6"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h8"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1"/><path d="M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1"/>',
  qr: '<rect x="3.5" y="3.5" width="6" height="6" rx="1"/><rect x="14.5" y="3.5" width="6" height="6" rx="1"/><rect x="3.5" y="14.5" width="6" height="6" rx="1"/><path d="M14.5 14.5h2.5v2.5M17.5 20.5h3v-3"/>',
  ping: '<path d="M13 2.5 4.5 14H11l-1 7.5L19.5 9H13l0-6.5Z"/>',
  power: '<path d="M12 3v8"/><path d="M6.3 6.8a8 8 0 1 0 11.4 0"/>',
  shield: '<path d="M12 3 4.5 6v5.2c0 4.6 3.2 8.1 7.5 9.8 4.3-1.7 7.5-5.2 7.5-9.8V6L12 3Z"/><path d="M9.5 12.2l1.7 1.7 3.4-3.6"/>',
  block: '<circle cx="12" cy="12" r="8.5"/><path d="M6 6l12 12"/>',
  pause: '<rect x="6.5" y="5" width="3.5" height="14" rx="1"/><rect x="14" y="5" width="3.5" height="14" rx="1"/>',
  play: '<path d="M7 5v14l11-7L7 5Z"/>',
  external: '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
  map: '<circle cx="12" cy="5" r="2.4"/><circle cx="5" cy="18" r="2.4"/><circle cx="19" cy="18" r="2.4"/><path d="M12 7.4v4.2M12 11.6 6.4 15.9M12 11.6l5.6 4.3"/>',
  trash: '<path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m-9 0 1 13h10l1-13"/>',
  download: '<path d="M12 3v12m0 0 4-4m-4 4-4-4"/><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/>',
  scan: '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
  speed: '<path d="M12 14l4-6"/><path d="M4.5 18a9 9 0 1 1 15 0"/>',
  theme: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M18.7 5.3l-1.4 1.4M6.7 17.3l-1.4 1.4"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  device: '<rect x="2.5" y="4" width="19" height="12.5" rx="2"/><path d="M8 20h8M12 16.5V20"/>',
  wifi: '<path d="M3.5 9a13 13 0 0 1 17 0M6.5 12.5a8.5 8.5 0 0 1 11 0M9.5 16a4.2 4.2 0 0 1 5 0"/>',
  bell: '<path d="M18 9a6 6 0 1 0-12 0c0 6-2 7-2 7h16s-2-1-2-7Z"/><path d="M10.3 20a2 2 0 0 0 3.4 0"/>',
  home: '<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/>',
  upload: '<path d="M12 21V9m0 0 4 4m-4-4-4 4"/><path d="M4 7V5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v2"/>',
};

const ctx = { el: null, items: [], index: -1 };

function initContextMenu() {
  const el = document.createElement("div");
  el.className = "ctx-menu";
  el.id = "ctx-menu";
  el.setAttribute("role", "menu");
  el.hidden = true;
  document.body.appendChild(el);
  ctx.el = el;

  document.addEventListener("contextmenu", (e) => {
    // Shift + sağ tık: tarayıcının kendi menüsü (geliştirici araçları vb. için)
    if (e.shiftKey) return;
    const t = e.target;
    // Yazı alanlarında yapıştır/kes gibi yerel işlemler kalsın
    if (t.closest("input, textarea, select, [contenteditable='true']")) return;
    const items = buildContextItems(t);
    if (!items.length) return;
    e.preventDefault();
    openContextMenu(e.clientX, e.clientY, items);
  });
  document.addEventListener("mousedown", (e) => { if (!ctx.el.hidden && !ctx.el.contains(e.target)) closeContextMenu(); }, true);
  document.addEventListener("touchstart", (e) => { if (!ctx.el.hidden && !ctx.el.contains(e.target)) closeContextMenu(); }, { passive: true, capture: true });
  window.addEventListener("blur", closeContextMenu);
  window.addEventListener("resize", closeContextMenu);
  document.addEventListener("scroll", closeContextMenu, true);
  document.addEventListener("keydown", (e) => {
    if (ctx.el.hidden) return;
    const enabled = ctx.items.map((it, i) => (!it.sep && !it.disabled && !it.header ? i : -1)).filter((i) => i >= 0);
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeContextMenu(); }
    else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const pos = enabled.indexOf(ctx.index);
      const next = e.key === "ArrowDown" ? enabled[(pos + 1) % enabled.length] : enabled[(pos - 1 + enabled.length) % enabled.length];
      focusContextItem(next);
    } else if (e.key === "Enter" || e.key === " ") {
      if (ctx.index >= 0) { e.preventDefault(); runContextItem(ctx.index); }
    }
  }, true);
}

function openContextMenu(x, y, items) {
  ctx.items = items;
  ctx.index = -1;
  ctx.el.innerHTML = items.map((it, i) => {
    if (it.sep) return `<div class="ctx-sep" role="separator"></div>`;
    if (it.header) return `<div class="ctx-header">${it.headerIcon ? `<span class="ctx-hico">${it.headerIcon}</span>` : ""}<div><b>${esc(it.header)}</b>${it.sub ? `<small>${esc(it.sub)}</small>` : ""}</div></div>`;
    const ico = CTX_ICONS[it.icon] ? `<svg viewBox="0 0 24 24">${CTX_ICONS[it.icon]}</svg>` : "<svg viewBox='0 0 24 24'></svg>";
    return `<button type="button" class="ctx-item ${it.danger ? "danger" : ""}" role="menuitem" data-ctx="${i}" ${it.disabled ? "disabled" : ""}>
      ${ico}<span>${esc(it.label)}</span>${it.hint ? `<kbd>${esc(it.hint)}</kbd>` : ""}</button>`;
  }).join("");
  ctx.el.querySelectorAll("[data-ctx]").forEach((btn) => {
    btn.addEventListener("click", () => runContextItem(Number(btn.dataset.ctx)));
    btn.addEventListener("mouseenter", () => focusContextItem(Number(btn.dataset.ctx), false));
  });
  ctx.el.hidden = false;
  // Ekrana sığdır: sağa/alta taşacaksa ters yöne aç
  const rect = ctx.el.getBoundingClientRect();
  const vw = window.innerWidth, vh = window.innerHeight;
  const left = x + rect.width + 8 > vw ? Math.max(8, x - rect.width) : x;
  const top = y + rect.height + 8 > vh ? Math.max(8, y - rect.height) : y;
  ctx.el.style.left = `${left}px`;
  ctx.el.style.top = `${top}px`;
  ctx.el.classList.remove("show");
  void ctx.el.offsetWidth;
  ctx.el.classList.add("show");
}

function focusContextItem(i, focus = true) {
  ctx.index = i;
  ctx.el.querySelectorAll("[data-ctx]").forEach((b) => b.classList.toggle("active", Number(b.dataset.ctx) === i));
  const btn = ctx.el.querySelector(`[data-ctx="${i}"]`);
  if (btn && focus) btn.focus({ preventScroll: true });
}

function closeContextMenu() {
  if (!ctx.el || ctx.el.hidden) return;
  ctx.el.hidden = true;
  ctx.el.classList.remove("show");
  ctx.items = [];
  ctx.index = -1;
}

function runContextItem(i) {
  const it = ctx.items[i];
  closeContextMenu();
  if (it && !it.disabled && typeof it.action === "function") {
    Promise.resolve().then(it.action).catch((err) => toast("İşlem başarısız", err.message, "error"));
  }
}

function buildContextItems(target) {
  const items = [];
  const selection = String(window.getSelection ? window.getSelection() : "").trim();

  // 1) Cihaz (tablo satırı, harita, radar, cihaz kartı, ebeveyn listesi)
  const devEl = target.closest("[data-device-id], [data-map-device], [data-hv-device], [data-device-open], [data-schedule-device]");
  if (devEl) {
    const id = Number(devEl.dataset.deviceId || devEl.dataset.mapDevice || devEl.dataset.hvDevice || devEl.dataset.deviceOpen || devEl.dataset.scheduleDevice);
    const d = state.devices.find((x) => x.id === id);
    if (d) items.push(...deviceContextItems(d));
  } else if (target.closest("[data-hv-router]")) {
    const gw = state.status && state.status.network && state.status.network.gateway;
    const router = state.devices.find((x) => x.ip === gw) || state.devices.find((x) => x.type === "router");
    if (router) items.push(...deviceContextItems(router));
  }

  // 2) Paylaşılan dosya
  const fileEl = !items.length && target.closest("[data-share-file]");
  if (fileEl) {
    const name = fileEl.dataset.shareFile;
    const link = shareLink(name);
    items.push(
      { header: name, sub: "Paylaşılan dosya", headerIcon: `<svg viewBox="0 0 24 24">${CTX_ICONS.download}</svg>` },
      { label: "Bağlantıyı kopyala", icon: "link", action: () => copyText(link, "Dosya bağlantısı") },
      { label: "QR kod ile telefona gönder", icon: "qr", action: () => showQr(link, name) },
      { label: "İndir", icon: "download", action: () => { window.location.href = `/share/${encodeURIComponent(name)}`; } },
      { sep: true },
      { label: "Sil", icon: "trash", danger: true, action: () => deleteSharedFile(name) },
    );
  }

  // 3) Uyarı
  const alertEl = !items.length && target.closest("[data-alert-id]");
  if (alertEl) {
    const a = state.alerts.find((x) => String(x.id) === alertEl.dataset.alertId);
    if (a) {
      const dev = a.mac && state.devices.find((x) => x.mac === a.mac);
      items.push(
        { header: a.title, sub: relTime(a.ts) },
        { label: "Metni kopyala", icon: "copy", action: () => copyText(`${a.title}\n${a.message || ""}`.trim(), "Uyarı") },
        { label: "Okundu işaretle", icon: "check", disabled: a.read, action: async () => { await api("/api/alerts/read", { method: "POST", body: { ids: [a.id] } }); await refreshAlerts(); } },
        { label: dev ? `Cihazı aç: ${truncate(dev.display_name, 22)}` : "İlgili cihaz yok", icon: "device", disabled: !dev, action: () => dev && openDrawer(dev.id) },
      );
    }
  }

  // 4) Wi-Fi ağı
  const wifiEl = !items.length && target.closest(".wifi-row[data-ssid]");
  if (wifiEl && wifiEl.dataset.ssid) {
    items.push(
      { header: wifiEl.dataset.ssid, sub: "Çevredeki Wi-Fi ağı" },
      { label: "Ağ adını kopyala", icon: "copy", action: () => copyText(wifiEl.dataset.ssid, "Ağ adı") },
    );
  }

  // 5) Tıkla-kopyala değeri
  const copyEl = !items.length && target.closest("[data-copy]");
  if (copyEl) {
    items.push({ label: `${copyEl.dataset.copyLabel || "Değeri"} kopyala`, icon: "copy", hint: truncate(copyEl.dataset.copy, 22), action: () => { copyText(copyEl.dataset.copy, copyEl.dataset.copyLabel); flashCopied(copyEl); } });
  }

  // Seçili metin
  if (selection) {
    if (items.length) items.push({ sep: true });
    items.push({ label: "Seçili metni kopyala", icon: "copy", hint: "Ctrl+C", action: () => copyText(selection) });
  }

  // 6) Genel işlemler: bir öğeye tıklandıysa kısa liste, boş alanda tam menü
  if (items.length) {
    items.push({ sep: true }, ...generalContextItems().slice(0, 2));
  } else {
    items.push(...generalContextItems());
  }
  return items;
}

function deviceContextItems(d) {
  const gw = state.status && state.status.network && state.status.network.gateway;
  const protectedDev = d.is_self || d.ip === gw;
  const realMac = d.mac && !isPlaceholderMac(d.mac) ? d.mac : "";
  const ports = (d.open_ports || []).map((p) => (typeof p === "object" ? p.port : p));
  const web = [[443, "https"], [8443, "https"], [80, "http"], [8080, "http"], [81, "http"]].find(([p]) => ports.includes(p));
  const meta = typeMeta(d.type);
  const items = [
    { header: d.display_name, sub: [meta.label, d.ip, d.online ? "çevrimiçi" : "çevrimdışı"].filter(Boolean).join(" • "), headerIcon: typeIcon(d.type, "ctx-type") },
    { label: "Ayrıntıları aç", icon: "open", action: () => openDrawer(d.id) },
    { label: "IP adresini kopyala", icon: "copy", hint: d.ip || "", disabled: !d.ip, action: () => copyText(d.ip, "IP adresi") },
    { label: "MAC adresini kopyala", icon: "copy", disabled: !realMac, action: () => copyText(realMac, "MAC adresi") },
    { label: "Adını kopyala", icon: "copy", action: () => copyText(d.display_name, "Cihaz adı") },
    { sep: true },
    { label: "Ping at", icon: "ping", disabled: !d.ip, action: () => pingDeviceById(d.id) },
  ];
  if (web) items.push({ label: "Yönetim sayfasını aç", icon: "external", hint: `:${web[0]}`, action: () => window.open(`${web[1]}://${d.ip}${[80, 443].includes(web[0]) ? "" : `:${web[0]}`}/`, "_blank", "noopener") });
  if (!d.is_self && realMac && ["computer", "laptop", "nas", "unknown"].includes(d.type)) {
    items.push({ label: "Uyandır (Wake-on-LAN)", icon: "power", action: () => wakeDeviceById(d.id) });
  }
  items.push({ label: "Haritada göster", icon: "map", action: () => showOnMap(d) });
  if (!protectedDev) {
    items.push(
      { sep: true },
      { label: d.trusted ? "Güvenilir işaretini kaldır" : "Güvenilir olarak işaretle", icon: "shield", action: () => patchDevice(d.id, { trusted: !d.trusted }) },
      d.paused
        ? { label: "Duraklatmayı kaldır", icon: "play", action: () => pauseDevice(d.id, 0) }
        : { label: "30 dakika duraklat", icon: "pause", action: () => pauseDevice(d.id, 30) },
      { label: d.blocked ? "Engeli kaldır" : "İletişimi engelle", icon: "block", danger: !d.blocked, action: () => blockDevice(d.id, !d.blocked) },
    );
  }
  if (!d.is_self) {
    items.push({ label: "Listeden kaldır", icon: "trash", danger: true, disabled: d.blocked, action: () => confirmDialog(
      "Cihazı kaldır",
      `<b>${esc(d.display_name)}</b> cihazı envanterden kaldırılacak. Ağda görünmeye devam ederse yeniden keşfedilebilir.`,
      "Kaldır",
      async () => { await api(`/api/devices/${d.id}`, { method: "DELETE" }); if (state.selectedId === d.id) closeDrawer(); await refreshDevicesAndAlerts(); toast("Cihaz kaldırıldı", "", "success"); },
      true,
    ) });
  }
  return items;
}

function generalContextItems() {
  const go = (view, label, icon) => ({ label, icon, disabled: state.view === view, action: () => showView(view) });
  return [
    { label: state.scanning ? "Tarama sürüyor…" : "Ağı tara", icon: "scan", hint: "", disabled: state.scanning, action: () => startScan() },
    { label: "Verileri yenile", icon: "scan", action: async () => { await refreshAll(); if (state.view === "internet") { loadLatency(); loadOutages(); } toast("Yenilendi", "", "success", 1500); } },
    { label: "Hız testi", icon: "speed", action: () => { showView("internet"); setTimeout(runSpeedtest, 200); } },
    { sep: true },
    go("dashboard", "Genel Bakış", "home"),
    go("map", "Ağ Haritası", "map"),
    go("devices", "Cihazlar", "device"),
    go("internet", "İnternet & Hız", "wifi"),
    go("share", "Paylaşım", "upload"),
    go("alerts", "Güvenlik & Uyarılar", "bell"),
    { sep: true },
    { label: state.theme === "dark" ? "Açık temaya geç" : "Koyu temaya geç", icon: "theme", action: () => setTheme(state.theme === "dark" ? "light" : "dark") },
    { label: "Sunucu adresini kopyala", icon: "link", disabled: !(state.status && state.status.app && state.status.app.lan_url), action: () => copyText(state.status.app.lan_url, "Sunucu adresi") },
  ];
}

async function pingDeviceById(id) {
  const d = state.devices.find((x) => x.id === id);
  if (!d) return;
  toast(`${d.display_name}`, "Ping gönderiliyor…", "info", 1500);
  try {
    const data = await api(`/api/devices/${id}/ping`, { method: "POST" });
    if (data.avg_ms != null) toast(`${d.display_name}: ${data.avg_ms} ms`, `Kayıp %${data.loss_pct}`, "success");
    else toast(`${d.display_name}`, data.message || "Cihaz yanıt vermedi", "error");
  } catch (err) { toast(`${d.display_name}`, `Ulaşılamadı: ${err.message}`, "error"); }
}

async function wakeDeviceById(id) {
  const d = state.devices.find((x) => x.id === id);
  if (!d) return;
  try {
    const data = await api(`/api/devices/${id}/wake`, { method: "POST" });
    toast("Wake-on-LAN", data.message || "Uyandırma paketi gönderildi.", "success");
  } catch (err) { toast("Wake-on-LAN hatası", err.message, "error"); }
}

function showOnMap(d) {
  showView("map");
  const input = $("#map-search-input");
  const q = d.ip || d.display_name;
  if (input) input.value = q;
  state.mapSearch = String(q).toLowerCase();
  if (state.mapFilter !== "all") {
    state.mapFilter = "all";
    $$("#map-category-filters .chip").forEach((c) => c.classList.toggle("active", c.dataset.mapFilter === "all"));
  }
  requestAnimationFrame(renderMap);
}
