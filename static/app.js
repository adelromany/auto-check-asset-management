/**
 * Snipe-IT Onboarding — Phase 3
 *
 * Flow:
 *  1. Page loads → request a session code from the server
 *  2. Show the one-liner commands for Windows / macOS / Linux
 *  3. Poll /api/session/{code}/data every 2 s
 *  4. When agent data arrives, render hardware + software + activation panels
 *  5. Merge with browser-side data (GPU, screen, battery, network)
 *  6. Auto-trigger Snipe-IT lookup using the serial from the agent
 */

"use strict";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let sessionCode   = null;
let pollTimer     = null;
let agentReceived = false;

// ---------------------------------------------------------------------------
// Entry
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", async () => {
  startClock();
  checkSnipeITHealth();

  // Collect browser-side data immediately (doesn't need the agent)
  const browserData = await collectBrowserData();
  renderBrowserSections(browserData);

  // Start the agent session
  await initSession();
});

async function checkSnipeITHealth() {
  const indicator = document.getElementById("snipeit-api-status");
  if (!indicator) return;

  try {
    const resp = await fetch("/api/snipeit/health");
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const result = await resp.json();
    const connected = result.connected === true;
    indicator.classList.remove("api-status-checking");
    indicator.classList.toggle("api-status-online", connected);
    indicator.classList.toggle("api-status-offline", !connected);
    const label = connected ? "Snipe-IT API connected" : "Snipe-IT API unavailable";
    indicator.title = label;
    indicator.setAttribute("aria-label", label);
  } catch (_) {
    indicator.classList.remove("api-status-checking", "api-status-online");
    indicator.classList.add("api-status-offline");
    indicator.title = "Snipe-IT API health check failed";
    indicator.setAttribute("aria-label", "Snipe-IT API health check failed");
  }
}

// ---------------------------------------------------------------------------
// Session lifecycle
// ---------------------------------------------------------------------------

async function initSession() {
  try {
    const resp = await fetch("/api/session/new");
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const { code, ttl_seconds } = await resp.json();
    sessionCode = code;

    renderAgentPanel(code, ttl_seconds);
    startPolling(code);
  } catch (e) {
    showAgentError(`Could not create session: ${e.message}`);
  }
}

function startPolling(code) {
  pollTimer = setInterval(async () => {
    if (agentReceived) { clearInterval(pollTimer); return; }
    try {
      const resp = await fetch(`/api/session/${code}/data`);
      if (resp.status === 202) return;           // still waiting
      if (!resp.ok) { clearInterval(pollTimer); return; }
      const body = await resp.json();
      if (body.status === "ready" && body.data) {
        agentReceived = true;
        clearInterval(pollTimer);
        onAgentData(body.data);
      }
    } catch (_) { /* network blip — keep polling */ }
  }, 2000);
}

function onAgentData(data) {
  // Mark agent panel as complete
  const panel = document.getElementById("agent-panel");
  if (panel) panel.classList.add("agent-done");

  const waiting = document.getElementById("agent-waiting");
  if (waiting) {
    waiting.innerHTML =
      '<span class="badge-ok">Agent connected</span> All data received.';
  }

  // Render hardware sections (left column)
  renderAgentSections(data);

  // Render software inventory + Windows activation (right column)
  if (data.software_checks || data.windows_activation) {
    renderSoftwareSection(data);
  }

  // Auto-lookup Snipe-IT if we have a serial
  if (data.serial) {
    lookupAndRenderSnipeIT(data.serial);
  }
}

// ---------------------------------------------------------------------------
// Browser-side collectors (unchanged from Phase 1)
// ---------------------------------------------------------------------------

async function collectBrowserData() {
  const [uach, battery, gpu] = await Promise.allSettled([
    collectUACH(), collectBattery(), collectGPU(),
  ]);
  return {
    uach:    uach.value    ?? {},
    battery: battery.value ?? {},
    gpu:     gpu.value     ?? {},
  };
}

async function collectUACH() {
  const nav = navigator, result = {};
  result.userAgent          = nav.userAgent;
  result.language           = nav.language;
  result.platform           = nav.platform;
  result.cookieEnabled      = nav.cookieEnabled;
  result.doNotTrack         = nav.doNotTrack ?? "unset";
  result.hardwareConcurrency = nav.hardwareConcurrency ?? null;

  if (nav.userAgentData?.getHighEntropyValues) {
    try {
      const h = await nav.userAgentData.getHighEntropyValues([
        "architecture","bitness","model","platform","platformVersion",
        "uaFullVersion","fullVersionList","mobile",
      ]);
      result.brand           = h.brands?.map(b => `${b.brand} ${b.version}`).join(", ");
      result.fullVersionList = h.fullVersionList?.map(b => `${b.brand} ${b.version}`).join(", ");
      result.platform_ch     = h.platform;
      result.platformVersion = h.platformVersion;
      result.architecture    = h.architecture;
      result.bitness         = h.bitness;
      result.model           = h.model || null;
      result.mobile          = h.mobile;
      result.uaFullVersion   = h.uaFullVersion;
    } catch (_) { result.chError = "Client Hints blocked or unavailable"; }
  } else {
    result.chError = "UA Client Hints not supported (non-Chromium)";
  }
  return result;
}

async function collectBattery() {
  if (!navigator.getBattery) return { supported: false };
  try {
    const b = await navigator.getBattery();
    return {
      supported: true,
      level:     Math.round(b.level * 100),
      charging:  b.charging,
      chargingTime:    b.chargingTime    === Infinity ? null : b.chargingTime,
      dischargingTime: b.dischargingTime === Infinity ? null : b.dischargingTime,
    };
  } catch (_) { return { supported: false }; }
}

function collectGPU() {
  try {
    const canvas = document.createElement("canvas");
    const gl = canvas.getContext("webgl") || canvas.getContext("experimental-webgl");
    if (!gl) return Promise.resolve({ supported: false });
    const dbg = gl.getExtension("WEBGL_debug_renderer_info");
    return Promise.resolve({
      supported: true,
      vendor:   dbg ? gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL)   : gl.getParameter(gl.VENDOR),
      renderer: dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER),
      version:  gl.getParameter(gl.VERSION),
    });
  } catch (_) { return Promise.resolve({ supported: false }); }
}

// ---------------------------------------------------------------------------
// Snipe-IT lookup
// ---------------------------------------------------------------------------

async function lookupAndRenderSnipeIT(serial) {
  const container = document.getElementById("snipeit-section");
  if (!container) return;

  const spinner = el("p", { className: "snipeit-looking" },
    `Looking up serial ${serial} in Snipe-IT…`);
  container.appendChild(spinner);

  let result;
  try {
    const resp = await fetch(`/api/snipeit/device?serial=${encodeURIComponent(serial)}`);
    result = resp.ok ? await resp.json() : { error: (await resp.json().catch(() => ({}))).detail ?? `HTTP ${resp.status}` };
  } catch (e) {
    result = { error: e.message };
  }

  spinner.remove();
  renderSnipeITResult(container, result);
}

function renderSnipeITResult(container, result) {
  container.querySelectorAll(".snipeit-result,.snipeit-error").forEach(e => e.remove());

  if (!result || result.error) {
    container.appendChild(
      el("div", { className: "snipeit-error" },
        el("span", { className: "error-icon" }, "✕"),
        ` ${result?.error ?? "Unknown error"}`)
    );
    return;
  }

  const rows = [
    ["Asset tag",    result.asset_tag],
    ["Name",         result.name],
    ["Serial",       result.serial],
    ["Status",       result.status],
    ["Model",        result.model],
    ["Category",     result.category],
    ["Manufacturer", result.manufacturer],
    ["Assigned to",  result.assigned_to ?? "Unassigned"],
    ["Location",     result.location],
    ["Last checkout",result.last_checkout],
    ["Purchase date",result.purchase_date],
    ["Warranty",     result.warranty_months ? `${result.warranty_months} months` : null],
    ["Notes",        result.notes],
  ];

  const div = el("div", { className: "snipeit-result" });
  div.appendChild(el("div", { className: "snipeit-found-badge" }, "Record found"));
  const table = el("table");
  rows.forEach(([label, value]) => {
    if (value == null || value === "") return;
    const tr = el("tr");
    tr.appendChild(el("td", { className: "label-cell" }, label));
    tr.appendChild(el("td", { className: "value-cell" }, String(value)));
    table.appendChild(tr);
  });
  div.appendChild(table);
  container.appendChild(div);
}

// ---------------------------------------------------------------------------
// Render — agent panel (session code + commands)
// ---------------------------------------------------------------------------

function renderAgentPanel(code, ttl) {
  const root = document.getElementById("agent-slot");
  if (!root) return;

  // Derive server origin from current page
  const origin = window.location.origin;

  const winCmd  = `$env:ONBOARD_URL="${origin}"; $env:ONBOARD_CODE="${code}"; iwr ${origin}/static/agent.ps1?v=4 -UseBasicParsing | iex`;
  const unixCmd = `curl -sL ${origin}/static/agent.sh?v=2 | ONBOARD_URL=${origin} ONBOARD_CODE=${code} bash`;

  const panel = el("div", { className: "agent-panel", id: "agent-panel" });

  // Header
  const hdr = el("div", { className: "agent-header" });
  hdr.appendChild(el("div", { className: "agent-icon", "aria-hidden": "true" }, "⬡"));
  const hdrText = el("div");
  hdrText.appendChild(el("div", { className: "agent-title" }, "Local Agent"));
  hdrText.appendChild(el("div", { className: "agent-subtitle" },
    "Run one command on this device to collect serial, RAM, disk and hostname."));
  hdr.appendChild(hdrText);
  panel.appendChild(hdr);

  // Session code display
  const codeBand = el("div", { className: "code-band" });
  codeBand.appendChild(el("span", { className: "code-label" }, "Session"));
  codeBand.appendChild(el("span", { className: "code-value" }, code));
  codeBand.appendChild(el("span", { className: "code-ttl" }, `Expires in ${Math.floor(ttl/60)} min`));
  panel.appendChild(codeBand);

  // Tab switcher
  const tabs   = el("div", { className: "cmd-tabs" });
  const bodies = el("div", { className: "cmd-bodies" });

  [
    { id: "win",   label: "Windows (PowerShell)", cmd: winCmd  },
    { id: "unix",  label: "macOS / Linux",        cmd: unixCmd },
  ].forEach(({ id, label, cmd }, i) => {
    const tab = el("button", { className: `cmd-tab${i === 0 ? " active" : ""}`, dataset: { target: id } }, label);
    tab.addEventListener("click", () => {
      tabs.querySelectorAll(".cmd-tab").forEach(t => t.classList.remove("active"));
      bodies.querySelectorAll(".cmd-body").forEach(b => b.classList.remove("active"));
      tab.classList.add("active");
      bodies.querySelector(`[data-id="${id}"]`).classList.add("active");
    });
    tabs.appendChild(tab);

    const body = el("div", { className: `cmd-body${i === 0 ? " active" : ""}`, dataset: { id } });
    const pre  = el("pre", { className: "cmd-pre" }, cmd);
    const copyBtn = el("button", { className: "copy-btn" }, "Copy");
    copyBtn.addEventListener("click", () => {
      navigator.clipboard.writeText(cmd).then(() => {
        copyBtn.textContent = "Copied!";
        setTimeout(() => { copyBtn.textContent = "Copy"; }, 2000);
      });
    });
    body.appendChild(pre);
    body.appendChild(copyBtn);
    bodies.appendChild(body);
  });

  panel.appendChild(tabs);
  panel.appendChild(bodies);

  // Waiting indicator
  const waiting = el("div", { className: "agent-waiting", id: "agent-waiting" });
  const dot = el("span", { className: "waiting-dot" });
  waiting.appendChild(dot);
  waiting.appendChild(document.createTextNode(" Waiting for agent…"));
  panel.appendChild(waiting);

  root.appendChild(panel);
}

function showAgentError(msg) {
  const root = document.getElementById("agent-slot");
  if (!root) return;
  root.appendChild(el("div", { className: "agent-error" }, `Agent session error: ${msg}`));
}

// ---------------------------------------------------------------------------
// Render — browser sections
// ---------------------------------------------------------------------------

function renderBrowserSections(data) {
  const root = document.getElementById("browser-sections");
  if (!root) return;

  renderSection(root, "Browser & OS (via browser)",  buildOSRows(data.uach));
  renderSection(root, "Graphics (WebGL)",             buildGPURows(data.gpu));
  renderSection(root, "Battery",                      buildBatteryRows(data.battery));
}

// ---------------------------------------------------------------------------
// Render — agent hardware sections
// ---------------------------------------------------------------------------

function renderAgentSections(d) {
  const root = document.getElementById("agent-sections");
  if (!root) return;
  root.classList.remove("hidden");

  renderSection(root, "System",    buildSystemRows(d));
  renderSection(root, "Processor", buildAgentCPURows(d));
  renderSection(root, "Memory",    buildAgentRAMRows(d));
  renderSection(root, "Storage",   buildDisksRows(d.disks));
  renderSection(root, "Network interfaces", buildNICRows(d));
  renderSection(root, "Operating System (from agent)", buildAgentOSRows(d));
}

// ---------------------------------------------------------------------------
// Section renderer
// ---------------------------------------------------------------------------

function renderSection(parent, title, rows) {
  if (!rows || rows.length === 0) return;
  const section = el("section", { className: "info-section" });
  section.appendChild(el("h2", {}, title));
  const table = el("table");
  rows.forEach(([label, value, note]) => {
    const tr = el("tr");
    const td1 = el("td", { className: "label-cell" }, label);
    const td2 = el("td", { className: "value-cell" });
    if (value == null || value === "") {
      td2.appendChild(el("span", { className: "unavailable" }, "Not available"));
    } else {
      td2.textContent = String(value);
    }
    if (note) td2.appendChild(el("span", { className: "note" }, ` — ${note}`));
    tr.appendChild(td1); tr.appendChild(td2);
    table.appendChild(tr);
  });
  section.appendChild(table);
  parent.appendChild(section);
}

// ---------------------------------------------------------------------------
// Row builders — browser
// ---------------------------------------------------------------------------

function buildOSRows(u) {
  if (!u) return [];
  const rows = [];
  const os = u.platform_ch || u.platform;
  if (os) rows.push(["Operating system", os]);
  if (u.platformVersion) rows.push(["OS version", u.platformVersion]);
  if (u.architecture)    rows.push(["Architecture", `${u.architecture}${u.bitness ? ` (${u.bitness}-bit)` : ""}`]);
  const brand = u.fullVersionList || u.brand;
  if (brand) rows.push(["Browser", brand]);
  if (u.uaFullVersion) rows.push(["Browser version", u.uaFullVersion]);
  if (u.mobile != null) rows.push(["Mobile", u.mobile ? "Yes" : "No"]);
  rows.push(["Language", u.language || null]);
  rows.push(["Logical CPU threads", u.hardwareConcurrency || null]);
  if (u.chError) rows.push(["Client Hints", null, u.chError]);
  return rows;
}

function buildGPURows(g) {
  if (!g?.supported) return [["GPU", null, "WebGL not available"]];
  return [
    ["Vendor",   g.vendor],
    ["Renderer", g.renderer],
    ["WebGL",    g.version],
  ];
}

function buildBatteryRows(b) {
  if (!b?.supported) return [["Battery", null, "Battery API not available in this browser"]];
  const rows = [
    ["Charge", `${b.level}%`],
    ["Charging", b.charging ? "Yes" : "No"],
  ];
  if (b.chargingTime    != null) rows.push(["Time to full",    fmtSec(b.chargingTime)]);
  if (b.dischargingTime != null) rows.push(["Time remaining",  fmtSec(b.dischargingTime)]);
  return rows;
}

// ---------------------------------------------------------------------------
// Row builders — agent
// ---------------------------------------------------------------------------

function buildSystemRows(d) {
  return [
    ["Hostname",     d.hostname],
    ["Current user", d.username],
    ["Serial",       d.serial],
    ["Manufacturer", d.manufacturer],
    ["Model",        d.model],
    ["Collected at", d.collected_at],
  ];
}

function buildAgentCPURows(d) {
  return [
    ["CPU",   d.cpu],
    ["Cores", d.cpu_cores != null ? String(d.cpu_cores) : null],
  ];
}

function buildAgentRAMRows(d) {
  return [
    ["RAM", d.ram_gb != null ? `${d.ram_gb} GB` : null],
  ];
}

function buildDisksRows(disks) {
  if (!disks || !disks.length) return [["Disks", null, "No disk data"]];
  const rows = [];
  disks.forEach((d, i) => {
    const label = disks.length === 1 ? "Disk" : `Disk ${i + 1}`;
    const size  = d.size_gb != null ? ` — ${d.size_gb} GB` : "";
    const type  = d.type    ? ` (${d.type})` : "";
    rows.push([label, `${d.name || "Unknown"}${size}${type}`]);
  });
  return rows;
}

function buildNICRows(d) {
  const ips = d.ip_addresses ?? [];
  if (!ips.length) return [["IPv4 address", null, "No Wi-Fi or Ethernet IPv4 data"]];
  return ips.map(({ iface, ip }) => [`${iface} IPv4`, ip]);
}

function buildAgentOSRows(d) {
  return [
    ["OS",           d.os_name],
    ["Version",      d.os_version],
    ["Architecture", d.os_arch],
  ];
}

// ---------------------------------------------------------------------------
// Render — software inventory + Windows activation
// ---------------------------------------------------------------------------

/**
 * Inserts two cards into the right column:
 *   1. Windows Activation status card
 *   2. Software inventory card (one row per app, with coloured status dot)
 *
 * Both are inserted into #software-slot which sits in the right column of
 * index.html, between the browser sections and the Snipe-IT record.
 */
function renderSoftwareSection(data) {
  const slot = document.getElementById("software-slot");
  if (!slot) return;

  // ── Windows Activation ───────────────────────────────────────────────────
  if (data.windows_activation) {
    const act = data.windows_activation;
    const activated = act.status_code === 1;

    const card = el("section", { className: "info-section sw-section" });
    card.appendChild(el("h2", {}, "Windows Activation"));

    const body = el("div", { className: "activation-body" });

    // Big status badge
    const badge = el("div", {
      className: `activation-badge ${activated ? "activation-ok" : "activation-warn"}`,
    });
    const dot = el("span", { className: "act-dot" });
    badge.appendChild(dot);
    badge.appendChild(document.createTextNode(act.status ?? "Unknown"));
    body.appendChild(badge);

    // Detail table
    const tbl = el("table");
    const detailRows = [
      ["Product",      act.product_name],
      ["Partial key",  act.partial_key ? `XXXXX-XXXXX-XXXXX-XXXXX-${act.partial_key}` : null],
      ["Status code",  act.status_code != null ? String(act.status_code) : null],
    ];
    detailRows.forEach(([label, value]) => {
      if (!value) return;
      const tr = el("tr");
      tr.appendChild(el("td", { className: "label-cell" }, label));
      tr.appendChild(el("td", { className: "value-cell" }, value));
      tbl.appendChild(tr);
    });
    body.appendChild(tbl);
    card.appendChild(body);
    slot.appendChild(card);
  }

  // ── Software Inventory ───────────────────────────────────────────────────
  if (data.software_checks && data.software_checks.length > 0) {
    const card = el("section", { className: "info-section sw-section" });
    card.appendChild(el("h2", {}, "Software inventory"));

    const tbl = el("table");

    // Header row
    const headTr = el("tr", { className: "sw-head-row" });
    ["Application", "Status", "Version", "Detection"].forEach((h, i) => {
      const th = el("th", { className: i === 0 ? "sw-col-name" : `sw-col-${["status","version","method"][i-1]}` }, h);
      headTr.appendChild(th);
    });
    tbl.appendChild(headTr);

    // One row per app
    data.software_checks.forEach(app => {
      const tr = el("tr", { className: app.installed ? "sw-row-ok" : "sw-row-missing" });

      // Name
      const tdName = el("td", { className: "sw-name" }, app.name);
      tr.appendChild(tdName);

      // Status dot + label
      const tdStatus = el("td", { className: "sw-status" });
      const statusWrap = el("span", { className: `sw-pill ${app.installed ? "sw-pill-ok" : "sw-pill-missing"}` });
      statusWrap.appendChild(el("span", { className: "sw-dot" }));
      statusWrap.appendChild(document.createTextNode(app.installed ? "Installed" : "Missing"));
      tdStatus.appendChild(statusWrap);
      tr.appendChild(tdStatus);

      // Version
      const tdVer = el("td", { className: "sw-version" });
      if (app.version) {
        tdVer.textContent = app.version;
      } else {
        tdVer.appendChild(el("span", { className: app.installed ? "unavailable" : "sw-missing-text" },
          app.installed ? "—" : "—"));
      }
      tr.appendChild(tdVer);

      // Detection method — friendly labels
      const methodMap = {
        registry:       "Registry",
        filesystem:     "File system",
        service:        "Windows service",
        appx:           "MSIX package",
        mdm_enrollment: "MDM enrollment",
        not_found:      "",
      };
      const tdMethod = el("td", { className: "sw-method" },
        methodMap[app.method] ?? app.method ?? "");
      tr.appendChild(tdMethod);

      tbl.appendChild(tr);
    });

    card.appendChild(tbl);
    slot.appendChild(card);
  }
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function fmtSec(sec) {
  if (sec == null) return null;
  const m = Math.floor(sec / 60), s = sec % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

/**
 * Tiny element factory.
 * el("div", { className: "foo", dataset: { bar: "baz" } }, child1, "text")
 */
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  Object.entries(attrs).forEach(([k, v]) => {
    if (k === "dataset") {
      Object.entries(v).forEach(([dk, dv]) => { node.dataset[dk] = dv; });
    } else {
      node[k] = v;
    }
  });
  children.forEach(c => {
    node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  });
  return node;
}

function startClock() {
  const clockEl = document.getElementById("clock");
  if (!clockEl) return;
  const tick = () => {
    clockEl.textContent = new Date().toLocaleTimeString([], {
      hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
    });
  };
  tick();
  setInterval(tick, 1000);
}
