// ============================================================
// LUCIDE ICON HELPER
// ============================================================

function safeCreateIcons(opts) {
    if (typeof lucide !== "undefined") lucide.createIcons(opts || {});
}


// ============================================================
// DEVICE REGISTRY
// All devices known to the platform.
// GALERT-01 is live; others are demo placeholders.
// ============================================================

// Pre-seeded history for placeholder devices
function genHistory(base, noise, length) {
    return Array.from({ length }, () =>
        Math.max(0, base + (Math.random() - 0.5) * noise * 2)
    );
}

const DEVICES = {

    'GALERT-01': {
        id:       'GALERT-01',
        label:    'Site A — Kumasi Central',
        isLive:   true,
        color:    '#22c55e',
        lat:      6.6885,
        lon:      -1.6244,
        data:     null,          // filled by live API
        alerts:   [],            // filled by live API
        history:  []             // filled by live sensor loop
    },

    'GALERT-02': {
        id:       'GALERT-02',
        label:    'Site B — Obuasi Road',
        isLive:   false,
        color:    '#22c55e',
        lat:      6.7120,
        lon:      -1.6050,
        data: {
            vibration:        0.00,
            activity_detected: false,
            activity_level:   'NORMAL',
            gps_fixed:        true,
            latitude:         6.7120,
            longitude:        -1.6050,
            location_name:    'Obuasi Road, Bekwai, Ashanti Region, Ghana',
            altitude:         312.4,
            satellites:       6,
            alert_sent:       false,
            last_alert_level: null,
            last_alert_time:  null
        },
        alerts:  [],
        history: Array(40).fill(0.0)
    },

    'GALERT-03': {
        id:       'GALERT-03',
        label:    'Site C — Manso Forest',
        isLive:   false,
        color:    '#22c55e',
        lat:      6.6550,
        lon:      -1.6580,
        data: {
            vibration:        0.00,
            activity_detected: false,
            activity_level:   'NORMAL',
            gps_fixed:        true,
            latitude:         6.6550,
            longitude:        -1.6580,
            location_name:    'Manso Nkwanta, Amansie West, Ashanti Region, Ghana',
            altitude:         298.1,
            satellites:       8,
            alert_sent:       false,
            last_alert_level: null,
            last_alert_time:  null
        },
        alerts:  [],
        history: Array(40).fill(0.0)
    }
};

// Load saved custom location labels from localStorage
try {
    const savedLabels = JSON.parse(localStorage.getItem("galert_device_labels") || "{}");
    Object.keys(savedLabels).forEach(id => {
        if (DEVICES[id] && savedLabels[id]) {
            DEVICES[id].label = savedLabels[id];
        }
    });
} catch (e) {
    console.warn("Could not load saved labels from localStorage:", e);
}

// Fetch labels from server as well
fetch("/api/devices/labels")
    .then(r => r.json())
    .then(serverLabels => {
        let changed = false;
        Object.keys(serverLabels).forEach(id => {
            if (DEVICES[id] && serverLabels[id] && !localStorage.getItem("galert_device_labels")) {
                DEVICES[id].label = serverLabels[id];
                changed = true;
            }
        });
        if (changed) renderDeviceSelector();
    })
    .catch(() => {});

let activeDeviceId = 'GALERT-01';

function getActiveDevice()  { return DEVICES[activeDeviceId]; }
function getActiveData()    { return getActiveDevice().data; }


// ============================================================
// TAB / PAGE SWITCHING
// ============================================================

const pages = document.querySelectorAll("[data-page]");
const tabs  = document.querySelectorAll("[data-tab]");

const pageMeta = {
    dashboard: { h1: "Monitoring Dashboard",   sub: "Real-time IoT activity monitoring" },
    sensors:   { h1: "Sensor Status",          sub: "MPU-6050 accelerometer & NEO-6M GPS" },
    activity:  { h1: "Activity Monitor",        sub: "Vibration levels and alert thresholds" },
    map:       { h1: "Live Map",                sub: "Real-time device location" },
    alerts:    { h1: "Alert History",           sub: "Log of all triggered email alerts" }
};

let currentTab = "dashboard";

function switchTab(targetTab) {
    currentTab = targetTab;

    pages.forEach(p => {
        p.style.display = p.dataset.page === targetTab ? "block" : "none";
    });

    tabs.forEach(t => {
        t.classList.toggle("active", t.dataset.tab === targetTab);
    });

    const meta = pageMeta[targetTab];
    if (meta) {
        document.getElementById("pageTitle").textContent    = meta.h1;
        document.getElementById("pageSubtitle").textContent = meta.sub;
    }

    if (targetTab === "dashboard" && map)     setTimeout(() => map.invalidateSize(), 50);
    if (targetTab === "map"       && mapFull) setTimeout(() => mapFull.invalidateSize(), 50);
}

document.addEventListener("click", e => {
    const link = e.target.closest("[data-tab]");
    if (!link) return;
    e.preventDefault();
    switchTab(link.dataset.tab);
    if (window.innerWidth <= 900) {
        closeSidebar();
    }
});


// ============================================================
// SIDEBAR OPEN / CLOSE CONTROLLER
// ============================================================

function invalidateMaps() {
    setTimeout(() => {
        if (map) map.invalidateSize();
        if (mapFull) mapFull.invalidateSize();
    }, 320);
}

function toggleSidebar() {
    if (window.innerWidth <= 900) {
        document.body.classList.toggle("sidebar-open");
    } else {
        document.body.classList.toggle("sidebar-closed");
        const isClosed = document.body.classList.contains("sidebar-closed");
        localStorage.setItem("galert_sidebar_closed", isClosed ? "1" : "0");
    }
    invalidateMaps();
}

function closeSidebar() {
    if (window.innerWidth <= 900) {
        document.body.classList.remove("sidebar-open");
    } else {
        document.body.classList.add("sidebar-closed");
        localStorage.setItem("galert_sidebar_closed", "1");
    }
    invalidateMaps();
}

function openSidebar() {
    if (window.innerWidth <= 900) {
        document.body.classList.add("sidebar-open");
    } else {
        document.body.classList.remove("sidebar-closed");
        localStorage.setItem("galert_sidebar_closed", "0");
    }
    invalidateMaps();
}

// Restore saved preference on desktop
if (window.innerWidth > 900 && localStorage.getItem("galert_sidebar_closed") === "1") {
    document.body.classList.add("sidebar-closed");
}

const sidebarToggleBtn = document.getElementById("sidebarToggleBtn");
if (sidebarToggleBtn) {
    sidebarToggleBtn.addEventListener("click", toggleSidebar);
}

const sidebarCloseBtn = document.getElementById("sidebarCloseBtn");
if (sidebarCloseBtn) {
    sidebarCloseBtn.addEventListener("click", closeSidebar);
}

const sidebarOverlay = document.getElementById("sidebarOverlay");
if (sidebarOverlay) {
    sidebarOverlay.addEventListener("click", closeSidebar);
}

// Esc key closes sidebar
document.addEventListener("keydown", e => {
    if (e.key === "Escape") {
        if (document.body.classList.contains("sidebar-open")) {
            closeSidebar();
        }
    }
});


// ============================================================
// VIBRATION HISTORY
// ============================================================

const HISTORY_MAX = 40;

function pushHistory(deviceId, vibration) {
    const h = DEVICES[deviceId].history;
    h.push(vibration);
    if (h.length > HISTORY_MAX) h.shift();
}

function renderHistory() {
    const chart = document.getElementById("historyChart");
    if (!chart) return;

    const history = getActiveDevice().history;
    const max = Math.max(0.6, ...history);

    chart.innerHTML = history.map(v => {
        const pct = Math.min(100, (v / max) * 100);
        let cls = "bar-normal";
        if (v >= 0.50) cls = "bar-critical";
        else if (v >= 0.15) cls = "bar-high";
        return `<div class="bar-wrap">
            <div class="bar ${cls}" style="height:${pct}%"
                title="${v.toFixed(3)} m/s²"></div>
        </div>`;
    }).join("");
}


// ============================================================
// MAP — MINI (Dashboard)
// ============================================================

const map = L.map("map").setView([6.6885, -1.6244], 11);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors"
}).addTo(map);

let marker     = null;
let mapCentred = false;


// ============================================================
// MAP — FULL (Map page)
// ============================================================

const mapFull = L.map("mapFull").setView([6.6885, -1.6244], 11);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors"
}).addTo(mapFull);

let markerFull     = null;
let mapFullCentred = false;


// ============================================================
// PLACEHOLDER DEVICE MARKERS
// ============================================================

const PLACEHOLDER_IDS = ['GALERT-02', 'GALERT-03'];
const placeholderMapMarkers     = {};
const placeholderMapFullMarkers = {};

function makeDeviceIcon(color, isActive) {
    const size   = isActive ? 16 : 12;
    const border = isActive ? '3px solid white' : '2px solid white';
    return L.divIcon({
        className: "",
        html: `<div style="
            width:${size}px;height:${size}px;
            background:${color};
            border:${border};
            border-radius:50%;
            box-shadow:0 1px 5px rgba(0,0,0,0.5);
            transition:all 0.2s;
        "></div>`,
        iconSize:    [size, size],
        iconAnchor:  [size/2, size/2],
        popupAnchor: [0, -10]
    });
}

function devicePopupHtml(d) {
    const locName   = (d.data && d.data.location_name) ? d.data.location_name : null;
    const level     = d.data ? d.data.activity_level : 'UNKNOWN';
    const vibration = d.data ? d.data.vibration.toFixed(3) : '0.000';
    const levelColor = level === 'CRITICAL' ? '#dc2626' : level === 'HIGH' ? '#f59e0b' : '#16a34a';
    const levelBg    = level === 'CRITICAL' ? '#fef2f2' : level === 'HIGH' ? '#fffbeb' : '#f0fdf4';

    return `<div style="
        font-family:'Segoe UI',Arial,sans-serif;
        min-width:240px;
        max-width:270px;
        border-radius:12px;
        overflow:hidden;
        box-shadow:0 8px 24px rgba(0,0,0,0.18);
    ">
        <!-- Header -->
        <div style="background:#111827;padding:14px 16px 12px;">
            <div style="display:flex;align-items:center;justify-content:space-between;">
                <div>
                    <div style="font-size:15px;font-weight:700;color:#fff;letter-spacing:0.5px;">${d.id}</div>
                    <div style="font-size:11px;color:#9ca3af;margin-top:2px;">${d.label}</div>
                </div>
                <span style="
                    padding:3px 9px;
                    border-radius:20px;
                    font-size:10px;
                    font-weight:700;
                    letter-spacing:0.5px;
                    background:${levelBg};
                    color:${levelColor};
                ">${level}</span>
            </div>
        </div>
        <!-- Body -->
        <div style="background:#fff;padding:12px 16px;">
            ${locName ? `<div style="
                display:flex;align-items:flex-start;gap:6px;
                background:#f0fdf4;
                border:1px solid #bbf7d0;
                border-radius:8px;
                padding:8px 10px;
                margin-bottom:10px;
            ">
                <span style="font-size:13px;line-height:1;">📍</span>
                <span style="font-size:11px;color:#065f46;font-weight:600;line-height:1.4;">${locName}</span>
            </div>` : ''}
            <table style="width:100%;border-collapse:collapse;font-size:12px;">
                <tr style="border-bottom:1px solid #f3f4f6;">
                    <td style="padding:5px 0;color:#6b7280;">Vibration</td>
                    <td style="padding:5px 0;font-weight:600;color:#111827;text-align:right;">${vibration} m/s²</td>
                </tr>
                <tr style="border-bottom:1px solid #f3f4f6;">
                    <td style="padding:5px 0;color:#6b7280;">Latitude</td>
                    <td style="padding:5px 0;font-weight:600;color:#111827;text-align:right;">${d.lat.toFixed(5)}</td>
                </tr>
                <tr>
                    <td style="padding:5px 0;color:#6b7280;">Longitude</td>
                    <td style="padding:5px 0;font-weight:600;color:#111827;text-align:right;">${d.lon.toFixed(5)}</td>
                </tr>
            </table>
            <div style="display:flex;gap:8px;margin-top:10px;">
                <button onclick="openRenameModal('${d.id}', event)"
                    style="flex:1;padding:7px;background:#f9fafb;border:1px solid #e5e7eb;
                    border-radius:8px;cursor:pointer;font-size:11px;font-weight:600;color:#374151;
                    transition:background 0.15s;">
                    ✏ Rename
                </button>
                <button onclick="selectDevice('${d.id}')"
                    style="flex:2;padding:7px;background:#111827;border:none;
                    border-radius:8px;cursor:pointer;font-size:11px;font-weight:700;color:#fff;
                    letter-spacing:0.3px;">
                    Prioritize ${d.id}
                </button>
            </div>
        </div>
    </div>`;
}

function addAllMarkersToMap(targetMap, markerStore) {
    PLACEHOLDER_IDS.forEach(id => {
        const d = DEVICES[id];
        const m = L.marker([d.lat, d.lon], { icon: makeDeviceIcon(d.color, false) })
            .addTo(targetMap)
            .bindPopup(devicePopupHtml(d));
        markerStore[id] = m;
    });
}

addAllMarkersToMap(map,     placeholderMapMarkers);
addAllMarkersToMap(mapFull, placeholderMapFullMarkers);


function updateMaps(lat, lon) {
    if (mapCentred) return;

    const pos    = [lat, lon];
    const allPts = [pos, ...PLACEHOLDER_IDS.map(id => [DEVICES[id].lat, DEVICES[id].lon])];
    const bounds = L.latLngBounds(allPts).pad(0.15);

    // Mini map
    marker = L.marker(pos).addTo(map);
    marker.bindPopup(popupForLive()).openPopup();
    map.fitBounds(bounds);
    mapCentred = true;

    // Full map
    markerFull = L.marker(pos).addTo(mapFull);
    markerFull.bindPopup(popupForLive());
    mapFull.fitBounds(bounds);
    mapFullCentred = true;
}

function popupForLive() {
    const d       = DEVICES['GALERT-01'];
    const locText = (d.data && d.data.location_name) ? d.data.location_name : null;
    const level   = (d.data && d.data.activity_level) ? d.data.activity_level : 'LIVE';
    const vib     = (d.data && d.data.vibration != null) ? d.data.vibration.toFixed(3) : '--';
    const temp    = (d.data && d.data.temperature    != null) ? d.data.temperature.toFixed(1)    + ' °C'  : '--';
    const press   = (d.data && d.data.pressure       != null) ? d.data.pressure.toFixed(1)       + ' hPa' : '--';
    const sats    = (d.data && d.data.satellites != null)     ? d.data.satellites                         : '--';
    const levelColor = level === 'CRITICAL' ? '#dc2626' : level === 'HIGH' ? '#f59e0b' : '#16a34a';
    const levelBg    = level === 'CRITICAL' ? '#fef2f2' : level === 'HIGH' ? '#fffbeb' : '#f0fdf4';

    return `<div style="
        font-family:'Segoe UI',Arial,sans-serif;
        min-width:250px;
        max-width:280px;
        border-radius:12px;
        overflow:hidden;
        box-shadow:0 8px 24px rgba(0,0,0,0.18);
    ">
        <!-- Header -->
        <div style="background:#111827;padding:14px 16px 12px;">
            <div style="display:flex;align-items:center;justify-content:space-between;">
                <div>
                    <div style="display:flex;align-items:center;gap:7px;">
                        <div style="width:8px;height:8px;background:#22c55e;border-radius:50%;box-shadow:0 0 6px #22c55e;"></div>
                        <span style="font-size:15px;font-weight:700;color:#fff;letter-spacing:0.5px;">GALERT-01</span>
                    </div>
                    <div style="font-size:11px;color:#9ca3af;margin-top:3px;padding-left:15px;">${d.label}</div>
                </div>
                <div style="display:flex;flex-direction:column;align-items:flex-end;gap:4px;">
                    <span style="
                        padding:3px 9px;border-radius:20px;
                        font-size:10px;font-weight:700;letter-spacing:0.5px;
                        background:${levelBg};color:${levelColor};
                    ">${level}</span>
                    <span style="font-size:9px;color:#4b5563;background:#1f2937;padding:2px 6px;border-radius:4px;">LIVE HARDWARE</span>
                </div>
            </div>
        </div>
        <!-- Body -->
        <div style="background:#fff;padding:12px 16px;">
            ${locText ? `<div style="
                display:flex;align-items:flex-start;gap:6px;
                background:#f0fdf4;border:1px solid #bbf7d0;
                border-radius:8px;padding:8px 10px;margin-bottom:10px;
            ">
                <span style="font-size:13px;line-height:1;">📍</span>
                <span style="font-size:11px;color:#065f46;font-weight:600;line-height:1.4;">${locText}</span>
            </div>` : ''}
            <table style="width:100%;border-collapse:collapse;font-size:12px;">
                <tr style="border-bottom:1px solid #f3f4f6;">
                    <td style="padding:5px 0;color:#6b7280;">Vibration</td>
                    <td style="padding:5px 0;font-weight:600;color:#111827;text-align:right;">${vib} m/s²</td>
                </tr>
                <tr style="border-bottom:1px solid #f3f4f6;">
                    <td style="padding:5px 0;color:#6b7280;">Temperature</td>
                    <td style="padding:5px 0;font-weight:600;color:#111827;text-align:right;">${temp}</td>
                </tr>
                <tr style="border-bottom:1px solid #f3f4f6;">
                    <td style="padding:5px 0;color:#6b7280;">Pressure</td>
                    <td style="padding:5px 0;font-weight:600;color:#111827;text-align:right;">${press}</td>
                </tr>
                <tr>
                    <td style="padding:5px 0;color:#6b7280;">Satellites</td>
                    <td style="padding:5px 0;font-weight:600;color:#111827;text-align:right;">${sats}</td>
                </tr>
            </table>
            <div style="display:flex;gap:8px;margin-top:10px;">
                <button onclick="openRenameModal('GALERT-01', event)"
                    style="flex:1;padding:7px;background:#f9fafb;border:1px solid #e5e7eb;
                    border-radius:8px;cursor:pointer;font-size:11px;font-weight:600;color:#374151;">
                    ✏ Rename
                </button>
                <button onclick="selectDevice('GALERT-01')"
                    style="flex:2;padding:7px;background:#16a34a;border:none;
                    border-radius:8px;cursor:pointer;font-size:11px;font-weight:700;color:#fff;
                    letter-spacing:0.3px;">
                    Prioritize GALERT-01
                </button>
            </div>
        </div>
    </div>`;
}


// ============================================================
// DEVICE SELECTOR UI
// ============================================================

function renderDeviceSelector() {
    const list       = document.getElementById("deviceList");
    const nameEl     = document.getElementById("currentDevName");
    const locEl      = document.getElementById("currentDevLoc");
    const dotEl      = document.getElementById("currentDevDot");
    const chevronEl  = document.querySelector(".chevron-icon");
    const pillTextEl = document.getElementById("headerPillText");
    const pillDotEl  = document.getElementById("headerPillDot");

    const active = DEVICES[activeDeviceId];
    if (nameEl) nameEl.textContent = active.id;
    if (locEl)  locEl.textContent  = active.label.replace(/^Site [A-Z] — /, '');
    if (dotEl)  dotEl.style.background = active.color;

    if (pillTextEl) pillTextEl.textContent = `${active.id} · ${active.label.replace(/^Site [A-Z] — /, '')}`;
    if (pillDotEl)  pillDotEl.style.background = active.color;

    if (list) {
        list.innerHTML = Object.values(DEVICES).map(d => {
            const isActive  = d.id === activeDeviceId;
            const liveLabel = d.isLive
                ? '<span class="dev-live-badge">LIVE</span>'
                : `<span class="dev-live-badge" style="background:${d.color}">${d.data ? d.data.activity_level : 'DEMO'}</span>`;
            return `<div class="device-list-item-wrap">
                <button class="device-list-item ${isActive ? 'dev-item-active' : ''}"
                    onclick="selectDevice('${d.id}')">
                    <span class="dev-status-dot" style="background:${d.color}"></span>
                    <span class="dev-info">
                        <span class="dev-id">${d.id} ${liveLabel}</span>
                        <span class="dev-label">${d.label}</span>
                    </span>
                    ${isActive ? '<span class="dev-check">✓</span>' : ''}
                </button>
                <button class="device-rename-btn" title="Rename location for ${d.id}"
                    onclick="openRenameModal('${d.id}', event)">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>
                        <path d="m15 5 4 4"/>
                    </svg>
                </button>
            </div>`;
        }).join("");
    }
}

// Toggle dropdown
const toggleBtn = document.getElementById("deviceToggleBtn");
if (toggleBtn) {
    toggleBtn.addEventListener("click", () => {
        const list    = document.getElementById("deviceList");
        const chevron = document.querySelector(".chevron-icon");
        if (!list) return;
        const open    = list.style.display === "none";
        list.style.display = open ? "block" : "none";
        if (chevron) chevron.style.transform = open ? "rotate(180deg)" : "";
    });
}

// Close dropdown when clicking outside
document.addEventListener("click", e => {
    if (!e.target.closest(".platform-section")) {
        const list = document.getElementById("deviceList");
        if (list) list.style.display = "none";
        const c = document.querySelector(".chevron-icon");
        if (c) c.style.transform = "";
    }
});


// ============================================================
// SELECT DEVICE — switches all tabs to that device's data
// ============================================================

function selectDevice(id) {
    if (!DEVICES[id]) return;

    activeDeviceId = id;

    // Close dropdown
    const list = document.getElementById("deviceList");
    if (list) list.style.display = "none";
    const c = document.querySelector(".chevron-icon");
    if (c) c.style.transform = "";

    // Re-render selector and header pill
    renderDeviceSelector();

    // Re-render all pages with new device's data
    const data = getActiveData();
    if (data) {
        renderDashboard(data);
        renderSensors(data);
        renderActivity(data);
        renderMapPage(data);
        renderAlerts(getActiveDevice().alerts);
    }

    // Pan map to selected device
    const dev = DEVICES[id];
    if (dev && dev.lat && dev.lon) {
        if (map) {
            map.panTo([dev.lat, dev.lon]);
            if (id === 'GALERT-01' && marker) marker.openPopup();
            else if (placeholderMapMarkers[id]) placeholderMapMarkers[id].openPopup();
        }
        if (mapFull) {
            mapFull.panTo([dev.lat, dev.lon]);
            if (id === 'GALERT-01' && markerFull) markerFull.openPopup();
            else if (placeholderMapFullMarkers[id]) placeholderMapFullMarkers[id].openPopup();
        }
    }
}


// ============================================================
// RENDER — DASHBOARD
// ============================================================

function renderDashboard(data) {

    document.getElementById("vibration").textContent  = data.vibration.toFixed(2);
    document.getElementById("vibration2").textContent = data.vibration.toFixed(2);

    const statusEl  = document.getElementById("activityStatus");
    const messageEl = document.getElementById("activityMessage");
    const boxEl     = document.getElementById("activityBox");

    if (data.activity_level === "CRITICAL") {
        statusEl.textContent  = "CRITICAL";
        statusEl.className    = "badge-critical";
        messageEl.textContent = "⚠ CRITICAL vibration — possible heavy machinery";
        boxEl.className       = "activity-box box-critical";
    } else if (data.activity_level === "HIGH") {
        statusEl.textContent  = "HIGH";
        statusEl.className    = "badge-high";
        messageEl.textContent = "⚠ HIGH vibration — suspicious activity detected";
        boxEl.className       = "activity-box box-high";
    } else {
        statusEl.textContent  = "NORMAL";
        statusEl.className    = "badge-normal";
        messageEl.textContent = "No suspicious activity detected";
        boxEl.className       = "activity-box";
    }

    const gpsEl = document.getElementById("gpsStatus");
    if (data.gps_fixed) {
        gpsEl.innerHTML = '<i data-lucide="satellite" class="inline-icon"></i> FIXED';
        gpsEl.style.color = "#16a34a";
    } else {
        gpsEl.innerHTML = '<i data-lucide="satellite-off" class="inline-icon"></i> NO FIX';
        gpsEl.style.color = "#dc2626";
    }
    safeCreateIcons({ nodes: [gpsEl] });

    document.getElementById("satellites").textContent = data.satellites;

    const realLocEl = document.getElementById("realLocationName");
    if (realLocEl) {
        if (data.location_name) {
            realLocEl.textContent = data.location_name;
            realLocEl.style.color = "#2dd4bf";
        } else if (data.gps_fixed) {
            realLocEl.textContent = "Resolving...";
            realLocEl.style.color = "#94a3b8";
        } else {
            realLocEl.textContent = "Awaiting GPS Fix";
            realLocEl.style.color = "#ef4444";
        }
    }

    if (data.gps_fixed) {
        document.getElementById("latitude").textContent  = data.latitude.toFixed(6);
        document.getElementById("longitude").textContent = data.longitude.toFixed(6);
        document.getElementById("altitude").textContent  = data.altitude.toFixed(1);
        document.getElementById("sats2").textContent     = data.satellites;
    }

    // BMP280 — Dashboard summary cards
    const tempEl   = document.getElementById("temperature");
    const pressEl  = document.getElementById("pressure");
    const envAltEl = document.getElementById("env-altitude");

    if (tempEl)   tempEl.textContent   = data.temperature           != null ? data.temperature.toFixed(1)           : "--";
    if (pressEl)  pressEl.textContent  = data.pressure              != null ? data.pressure.toFixed(1)              : "--";
    if (envAltEl) envAltEl.textContent = data.environment_altitude  != null ? data.environment_altitude.toFixed(1)  : "--";
}


// ============================================================
// RENDER — SENSORS
// ============================================================

function renderSensors(data) {

    document.getElementById("s-activity-level").textContent = data.activity_level;
    document.getElementById("s-vibration").textContent = data.vibration.toFixed(3) + " m/s²";
    document.getElementById("s-detected").textContent   = data.activity_detected ? "Yes" : "No";

    const fixEl = document.getElementById("s-gps-fixed");
    if (data.gps_fixed) {
        fixEl.innerHTML   = '<i data-lucide="check-circle-2" class="inline-icon"></i> Yes';
        fixEl.style.color = "#16a34a";
    } else {
        fixEl.innerHTML   = '<i data-lucide="x-circle" class="inline-icon"></i> No';
        fixEl.style.color = "#dc2626";
    }
    safeCreateIcons({ nodes: [fixEl] });

    const sRealLocEl = document.getElementById("s-realLocationName");
    if (sRealLocEl) {
        if (data.location_name) {
            sRealLocEl.textContent = data.location_name;
            sRealLocEl.style.color = "#2dd4bf";
        } else if (data.gps_fixed) {
            sRealLocEl.textContent = "Resolving...";
            sRealLocEl.style.color = "#94a3b8";
        } else {
            sRealLocEl.textContent = "Awaiting GPS Fix";
            sRealLocEl.style.color = "#ef4444";
        }
    }

    if (data.gps_fixed) {
        document.getElementById("s-lat").textContent  = data.latitude.toFixed(6);
        document.getElementById("s-lon").textContent  = data.longitude.toFixed(6);
        document.getElementById("s-alt").textContent  = data.altitude.toFixed(1) + " m";
        document.getElementById("s-sats").textContent = data.satellites;
    } else {
        ["s-lat","s-lon","s-alt","s-sats"].forEach(id => {
            document.getElementById(id).textContent = "--";
        });
    }

    // BMP280 — Sensor panel
    const bmpStatus  = document.getElementById("bmp-chip-status");
    const sTempEl    = document.getElementById("s-temperature");
    const sPressEl   = document.getElementById("s-pressure");
    const sEnvAltEl  = document.getElementById("s-env-altitude");

    const bmpAvail = data.temperature != null;

    if (bmpStatus) {
        bmpStatus.textContent = bmpAvail ? "CONNECTED" : "UNAVAILABLE";
        bmpStatus.className   = bmpAvail ? "badge-normal" : "badge-high";
    }

    if (sTempEl)   sTempEl.textContent   = bmpAvail                      ? data.temperature.toFixed(2)           + " °C"  : "--";
    if (sPressEl)  sPressEl.textContent  = data.pressure           != null ? data.pressure.toFixed(2)             + " hPa" : "--";
    if (sEnvAltEl) sEnvAltEl.textContent = data.environment_altitude != null ? data.environment_altitude.toFixed(2) + " m"   : "--";
}


// ============================================================
// RENDER — ACTIVITY
// ============================================================

function renderActivity(data) {

    const v = data.vibration;
    document.getElementById("act-level").textContent     = data.activity_level;
    document.getElementById("act-vibration").textContent = v.toFixed(3);
    document.getElementById("gaugeValue").textContent    = v.toFixed(3);

    const MAX_VIB = 0.6;
    const pct     = Math.min(100, (v / MAX_VIB) * 100);
    const fill    = document.getElementById("gaugeFill");
    fill.style.width      = pct + "%";
    fill.style.background = v >= 0.50 ? "#dc2626" : v >= 0.15 ? "#f59e0b" : "#22c55e";

    document.getElementById("gaugeHigh").style.left     = ((0.15 / MAX_VIB) * 100) + "%";
    document.getElementById("gaugeCritical").style.left = ((0.50 / MAX_VIB) * 100) + "%";

    const lvlEl   = document.getElementById("actLevelDisplay");
    lvlEl.textContent = data.activity_level;
    lvlEl.className   = "activity-level-display level-" + data.activity_level.toLowerCase();

    renderHistory();
}


// ============================================================
// RENDER — MAP PAGE
// ============================================================

function renderMapPage(data) {

    document.getElementById("m-activity").textContent = data.activity_level;
    document.getElementById("m-sats").textContent     = data.satellites;

    const fixEl = document.getElementById("m-fix");
    if (data.gps_fixed) {
        fixEl.innerHTML   = '<i data-lucide="check-circle-2" class="inline-icon"></i> Fixed';
        fixEl.style.color = "#16a34a";
    } else {
        fixEl.innerHTML   = '<i data-lucide="x-circle" class="inline-icon"></i> No fix';
        fixEl.style.color = "#dc2626";
    }
    safeCreateIcons({ nodes: [fixEl] });

    const mRealLocEl = document.getElementById("m-realLocationName");
    if (mRealLocEl) {
        if (data.location_name) {
            mRealLocEl.textContent = data.location_name;
            mRealLocEl.style.color = "#2dd4bf";
        } else if (data.gps_fixed) {
            mRealLocEl.textContent = "Resolving...";
            mRealLocEl.style.color = "#94a3b8";
        } else {
            mRealLocEl.textContent = "Awaiting GPS Fix";
            mRealLocEl.style.color = "#ef4444";
        }
    }

    if (data.gps_fixed) {
        document.getElementById("m-lat").textContent = data.latitude.toFixed(6);
        document.getElementById("m-lon").textContent = data.longitude.toFixed(6);
        document.getElementById("m-alt").textContent = data.altitude.toFixed(1);

        const gmLink   = document.getElementById("mapGoogleLink");
        gmLink.href    = `https://www.google.com/maps?q=${data.latitude},${data.longitude}`;
        gmLink.style.display = "inline-flex";
    }
}


// ============================================================
// RENDER — ALERTS
// ============================================================

function levelBadge(level) {
    const styles = {
        CRITICAL: "background:#fee2e2;color:#991b1b",
        HIGH:     "background:#fef3c7;color:#92400e",
        NORMAL:   "background:#dcfce7;color:#166534"
    };
    const s = styles[level] || styles.NORMAL;
    return `<span class="level-badge" style="${s}">${level}</span>`;
}

function renderAlerts(alerts) {

    const empty     = document.getElementById("alertsEmpty");
    const tableWrap = document.getElementById("alertsTableWrap");
    const tbody     = document.getElementById("alertsBody");
    const counter   = document.getElementById("alertCount");

    counter.textContent = alerts.length === 1 ? "1 alert" : `${alerts.length} alerts`;

    if (alerts.length === 0) {
        empty.style.display     = "block";
        tableWrap.style.display = "none";
        return;
    }

    empty.style.display     = "none";
    tableWrap.style.display = "block";

    const sorted = [...alerts].reverse();

    tbody.innerHTML = sorted.map(a => {
        const mapsUrl      = a.gps_fixed ? `https://www.google.com/maps?q=${a.latitude},${a.longitude}` : null;
        let locationCell   = "";
        if (a.location_name) {
            locationCell = `<div style="max-width:240px;line-height:1.2">
                <span style="font-weight:600;color:var(--accent-teal, #2dd4bf);font-size:12px">📍 ${a.location_name}</span>
                ${mapsUrl ? `<br><a href="${mapsUrl}" target="_blank" class="map-link" style="font-size:11px"><i data-lucide="map-pin" class="inline-icon"></i> View on Map</a>` : ''}
            </div>`;
        } else if (a.gps_fixed) {
            locationCell = `<a href="${mapsUrl}" target="_blank" class="map-link"><i data-lucide="map-pin" class="inline-icon"></i> ${a.latitude.toFixed(4)}, ${a.longitude.toFixed(4)}</a>`;
        } else {
            locationCell = `<span class="no-gps"><i data-lucide="map-pin-off" class="inline-icon"></i> No fix</span>`;
        }
        const emailCell = a.email_sent
            ? `<span class="email-sent"><i data-lucide="mail-check" class="inline-icon"></i> Sent</span>`
            : `<span class="email-fail"><i data-lucide="mail-x" class="inline-icon"></i> Failed</span>`;

        return `<tr class="alert-row-${a.level.toLowerCase()}">
            <td>${a.timestamp}</td>
            <td>${levelBadge(a.level)}</td>
            <td>${a.vibration} m/s²</td>
            <td>${a.gps_fixed ? "Fixed" : "No fix"}</td>
            <td>${a.satellites}</td>
            <td>${emailCell}</td>
            <td>${locationCell}</td>
        </tr>`;
    }).join("");

    safeCreateIcons({ nodes: [tbody] });
}


// ============================================================
// LIVE DATA FETCH  (GALERT-01 only)
// ============================================================

async function getSensorData() {
    try {
        const response = await fetch("/api/data");
        const data     = await response.json();

        // Always cache the live data
        DEVICES['GALERT-01'].data = data;
        pushHistory('GALERT-01', data.vibration);

        // Only render if GALERT-01 is the active device
        if (activeDeviceId === 'GALERT-01') {
            renderDashboard(data);
            renderSensors(data);
            renderActivity(data);
            renderMapPage(data);
        }

        // Always update maps with live GPS
        if (data.gps_fixed) updateMaps(data.latitude, data.longitude);

    } catch (err) {
        console.error("Sensor data error:", err);
    }
}

async function fetchAlerts() {
    try {
        const response = await fetch("/api/alerts");
        const data     = await response.json();

        // Cache in device registry
        DEVICES['GALERT-01'].alerts = data;

        // Only render if GALERT-01 is active
        if (activeDeviceId === 'GALERT-01') renderAlerts(data);

    } catch (err) {
        console.error("Alerts fetch error:", err);
    }
}


// ============================================================
// SIMULATION TICK FOR ACTIVE PLACEHOLDER DEVICE
// ============================================================

function tickActivePlaceholder() {
    if (activeDeviceId === 'GALERT-01') return;

    const dev = DEVICES[activeDeviceId];
    if (!dev || !dev.data) return;

    // Zero mock data: all remote nodes remain strictly at 0.00 m/s² NORMAL
    dev.data.vibration = 0.0;
    dev.data.activity_detected = false;
    dev.data.activity_level = 'NORMAL';
    pushHistory(dev.id, 0.0);

    renderDashboard(dev.data);
    renderSensors(dev.data);
    renderActivity(dev.data);
    renderMapPage(dev.data);
}


// ============================================================
// POLLING
// ============================================================

setInterval(getSensorData, 1000);
setInterval(tickActivePlaceholder, 1000);
setInterval(fetchAlerts,   5000);


// ============================================================
// DEVICE LOCATION RENAMING CONTROLLER
// ============================================================

let renameTargetDeviceId = null;

function showToast(message) {
    const toast = document.getElementById("toastMessage");
    if (!toast) return;
    toast.textContent = message;
    toast.style.display = "block";
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => {
        toast.style.display = "none";
    }, 3000);
}

function openRenameModal(deviceId, event) {
    if (event) {
        event.stopPropagation();
        event.preventDefault();
    }
    const dev = DEVICES[deviceId];
    if (!dev) return;

    renameTargetDeviceId = deviceId;

    const modal = document.getElementById("renameModal");
    const sub   = document.getElementById("renameModalDevId");
    const input = document.getElementById("newLocationInput");

    if (sub)   sub.textContent = `${dev.id} (${dev.isLive ? 'Live Hardware' : 'Stationary Node'})`;
    if (input) input.value     = dev.label;

    if (modal) {
        modal.style.display = "flex";
        setTimeout(() => input && input.focus(), 60);
    }
}

function closeRenameModal() {
    const modal = document.getElementById("renameModal");
    if (modal) modal.style.display = "none";
    renameTargetDeviceId = null;
}

function saveRenameLocation() {
    if (!renameTargetDeviceId || !DEVICES[renameTargetDeviceId]) return;

    const input   = document.getElementById("newLocationInput");
    const newName = input ? input.value.trim() : "";

    if (!newName) {
        alert("Please enter a valid location name.");
        return;
    }

    const dev = DEVICES[renameTargetDeviceId];
    dev.label = newName;

    // Persist to localStorage
    try {
        const savedLabels = JSON.parse(localStorage.getItem("galert_device_labels") || "{}");
        savedLabels[renameTargetDeviceId] = newName;
        localStorage.setItem("galert_device_labels", JSON.stringify(savedLabels));
    } catch (e) {
        console.error("Failed saving labels:", e);
    }

    // Persist to server backend
    fetch("/api/devices/rename", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: renameTargetDeviceId, label: newName })
    }).catch(err => console.warn("Backend rename sync error:", err));

    // Update map popups
    if (renameTargetDeviceId === 'GALERT-01') {
        const liveHtml = popupForLive();
        if (marker) {
            marker.bindPopup(liveHtml);
            if (marker.isPopupOpen && marker.isPopupOpen()) marker.setPopupContent(liveHtml);
        }
        if (markerFull) {
            markerFull.bindPopup(liveHtml);
            if (markerFull.isPopupOpen && markerFull.isPopupOpen()) markerFull.setPopupContent(liveHtml);
        }
    } else {
        const devHtml = devicePopupHtml(dev);
        if (placeholderMapMarkers[renameTargetDeviceId]) {
            const m = placeholderMapMarkers[renameTargetDeviceId];
            m.bindPopup(devHtml);
            if (m.isPopupOpen && m.isPopupOpen()) m.setPopupContent(devHtml);
        }
        if (placeholderMapFullMarkers[renameTargetDeviceId]) {
            const mf = placeholderMapFullMarkers[renameTargetDeviceId];
            mf.bindPopup(devHtml);
            if (mf.isPopupOpen && mf.isPopupOpen()) mf.setPopupContent(devHtml);
        }
    }

    renderDeviceSelector();
    closeRenameModal();
    showToast(`Location updated to "${newName}"`);
}

const saveRenameBtn = document.getElementById("saveRenameBtn");
if (saveRenameBtn) saveRenameBtn.addEventListener("click", saveRenameLocation);

const cancelRenameBtn = document.getElementById("cancelRenameBtn");
if (cancelRenameBtn) cancelRenameBtn.addEventListener("click", closeRenameModal);

const closeRenameModalBtn = document.getElementById("closeRenameModalBtn");
if (closeRenameModalBtn) closeRenameModalBtn.addEventListener("click", closeRenameModal);

const newLocationInput = document.getElementById("newLocationInput");
if (newLocationInput) {
    newLocationInput.addEventListener("keydown", e => {
        if (e.key === "Enter") {
            e.preventDefault();
            saveRenameLocation();
        } else if (e.key === "Escape") {
            closeRenameModal();
        }
    });
}

const renameModal = document.getElementById("renameModal");
if (renameModal) {
    renameModal.addEventListener("click", e => {
        if (e.target === renameModal) closeRenameModal();
    });
}

const headerRenameBtn = document.getElementById("headerRenameBtn");
if (headerRenameBtn) {
    headerRenameBtn.addEventListener("click", e => {
        openRenameModal(activeDeviceId, e);
    });
}


// ============================================================
// INIT
// ============================================================

renderDeviceSelector();
getSensorData();
fetchAlerts();
