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
 *
 * UI: shadcn/ui primitives (card, button, badge, tabs, table) rendered with
 * Tailwind utility classes. The class names mirror the shadcn component API
 * so a future React port is a mechanical translation.
 *
 * Layout:
 *   - the agent panel spans the full width (primary action; the command
 *     fits on one line)
 *   - two columns below: what the agent reported | what this browser knows
 *
 * Contract with the test-suite (tests/test_clipboard_playwright.py):
 *   - the copy button carries the class `copy-btn`
 *   - the visible command block carries `cmd-body active` and contains `cmd-pre`
 */

"use strict";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let sessionCode   = null;
let pollTimer     = null;
let agentReceived = false;
let agentCard     = null;   // { card, body } — the "Reported by the agent" card
let copied        = false;  // the command was copied at least once

// ---------------------------------------------------------------------------
// Entry
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", async () => {
  startClock();
  loadUser();
  checkSnipeITHealth();

  // Placeholder keeps both columns balanced until the agent reports.
  renderAgentPlaceholder();

  // Collect browser-side data immediately (doesn't need the agent)
  const browserData = await collectBrowserData();
  renderBrowserSections(browserData);

  // Start the agent session
  await initSession();
});

// ---------------------------------------------------------------------------
// Snipe-IT health
// ---------------------------------------------------------------------------

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

  setAgentStatus("success", "Agent connected");
  setStep(3, "done");
  setStep(2, "done");
  setStep(1, "done");

  const waiting = document.getElementById("agent-waiting");
  if (waiting) {
    waiting.textContent = "";
    waiting.appendChild(el("span", { className: "size-1.5 rounded-full bg-success" }));
    waiting.appendChild(document.createTextNode(" All data received."));
  }

  // Render hardware sections (left column)
  renderAgentSections(data);

  // Render software inventory + Windows activation (left column, below hardware)
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
  } catch (_) { return { supported: false }; }
}

// ---------------------------------------------------------------------------
// Snipe-IT lookup
// ---------------------------------------------------------------------------

async function lookupAndRenderSnipeIT(serial) {
  const container = document.getElementById("snipeit-section");
  if (!container) return;

  const body = snipeitBody(container);
  body.textContent = "";
  body.appendChild(snipeitSkeleton());

  let result;
  try {
    const resp = await fetch(`/api/snipeit/device?serial=${encodeURIComponent(serial)}`);
    result = resp.ok ? await resp.json() : { error: (await resp.json().catch(() => ({}))).detail ?? `HTTP ${resp.status}` };
  } catch (e) {
    result = { error: e.message };
  }

  renderSnipeITResult(body, result);
}

/** The content area of the Snipe-IT card (below its header). */
function snipeitBody(container) {
  let body = container.querySelector(".snipeit-body");
  if (!body) {
    body = el("div", { className: "snipeit-body card-content py-4" });
    container.appendChild(body);
  }
  return body;
}

function snipeitSkeleton() {
  const wrap = el("div", { className: "flex flex-col gap-2" });
  [85, 70, 60].forEach((w) => {
    wrap.appendChild(el("div", { className: "skeleton h-3", style: `width:${w}%` }));
  });
  return wrap;
}

function renderSnipeITResult(body, result) {
  body.textContent = "";

  if (!result || result.error) {
    body.appendChild(el("div", { className: "snipeit-error alert alert-destructive" },
      el("span", { className: "alert-title" }, result?.error ?? "Unknown error")));
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
  ].filter(([, v]) => v != null && v !== "");

  if (!rows.length) {
    body.appendChild(el("p", { className: "text-sm text-muted-foreground" },
      "No record found for this serial."));
    return;
  }

  const div = el("div", { className: "snipeit-result" });
  div.appendChild(el("span", { className: "badge badge-success mb-3" }, "Record found"));
  div.appendChild(buildTable(rows));
  body.appendChild(div);
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

  const panel = el("div", { className: "card agent-panel overflow-hidden", id: "agent-panel" });

  // ── Header ───────────────────────────────────────────────────────────────
  const hdr = el("div", { className: "card-header flex-row items-start gap-3 border-b" });
  hdr.appendChild(el("div", {
    className: "flex size-8 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary",
    "aria-hidden": "true",
  }, icon("terminal")));
  const hdrText = el("div", { className: "flex min-w-0 flex-1 flex-col gap-1" });
  hdrText.appendChild(el("div", { className: "card-title text-sm" }, "Local Agent"));
  hdrText.appendChild(el("div", { className: "card-description" },
    "Run one command on this device to collect serial, RAM, disk and hostname."));
  hdr.appendChild(hdrText);
  hdr.appendChild(el("span", {
    id: "agent-status",
    className: "badge badge-secondary shrink-0",
  }, "Waiting for agent"));
  panel.appendChild(hdr);

  // ── Session code ──────────────────────────────────────────────────────────
  const codeBand = el("div", {
    className: "code-band flex flex-wrap items-center gap-x-3 gap-y-1 border-b bg-primary/5 px-5 py-2.5",
  });
  codeBand.appendChild(el("span", { className: "text-xs font-medium text-muted-foreground" }, "Session"));
  codeBand.appendChild(el("span", {
    className: "code-value font-mono text-sm font-semibold tracking-[0.12em] text-primary",
  }, code));
  codeBand.appendChild(el("span", { className: "code-ttl text-xs text-muted-foreground" },
    `Expires in ${Math.floor(ttl/60)} min`));
  codeBand.appendChild(el("span", { className: "ml-auto hidden items-center gap-1.5 text-xs text-muted-foreground sm:flex" },
    icon("shield"), el("span", {}, "Nothing is uploaded from this browser")));
  panel.appendChild(codeBand);

  // ── Tabs + command ───────────────────────────────────────────────────────
  const tabs   = el("div", { className: "tabs-list m-5 mb-0", role: "tablist", "aria-label": "Agent command per platform" });
  const bodies = el("div", { className: "cmd-bodies" });
  const triggers = [];

  [
    { id: "win",   label: "Windows (PowerShell)", cmd: winCmd  },
    { id: "unix",  label: "macOS / Linux",        cmd: unixCmd },
  ].forEach(({ id, label, cmd }, i) => {
    const active = i === 0;
    const tab = el("button", {
      type: "button",
      id: `cmd-tab-${id}`,
      className: "tabs-trigger",
      role: "tab",
      "aria-controls": `cmd-panel-${id}`,
      "aria-selected": active ? "true" : "false",
      tabIndex: active ? 0 : -1,
      dataset: { target: id, state: active ? "active" : "inactive" },
    }, label);
    triggers.push(tab);
    tabs.appendChild(tab);

    const body = el("div", {
      id: `cmd-panel-${id}`,
      className: `cmd-body border-t${active ? " active" : " hidden"}`,
      role: "tabpanel",
      "aria-labelledby": `cmd-tab-${id}`,
      tabindex: "0",
      dataset: { id, state: active ? "active" : "inactive" },
    });

    const row = el("div", { className: "flex items-start gap-3 bg-muted/40 px-5 py-3" });
    const pre = el("pre", {
      className: "cmd-pre min-w-0 flex-1 overflow-x-auto whitespace-pre font-mono text-xs leading-relaxed text-foreground",
    }, cmd);
    const copyBtn = el("button", {
      type: "button",
      className: "copy-btn btn btn-outline btn-sm shrink-0",
    }, "Copy");

    // The command text is already in memory: call copyText synchronously
    // in the click handler so the browser keeps user activation.
    // copyText never fails silently (falls back to execCommand, then modal).
    copyBtn.addEventListener("click", () => {
      copyText(cmd, { filename: id === "win" ? "onboard.ps1" : "onboard.sh" }).then((res) => {
        if (res.ok) {
          copyBtn.textContent = `Copied (${cmd.length} chars)`;
          if (!copied) {
            copied = true;
            setStep(1, "done");
            setStep(2, "current");
          }
        } else {
          copyBtn.textContent = "Copy manually";
        }
        setTimeout(() => { copyBtn.textContent = "Copy"; }, 2500);
      });
    });

    row.appendChild(pre);
    row.appendChild(copyBtn);
    body.appendChild(row);
    bodies.appendChild(body);
  });

  // Tab switching + keyboard support
  function activate(trigger) {
    const id = trigger.dataset.target;
    triggers.forEach(t => {
      const on = t === trigger;
      t.dataset.state = on ? "active" : "inactive";
      t.setAttribute("aria-selected", on ? "true" : "false");
      t.tabIndex = on ? 0 : -1;
      t.classList.toggle("active", on);
    });
    bodies.querySelectorAll(".cmd-body").forEach(b => {
      const on = b.dataset.id === id;
      b.classList.toggle("active", on);
      b.classList.toggle("hidden", !on);
      b.dataset.state = on ? "active" : "inactive";
    });
  }
  triggers.forEach((t, i) => {
    t.addEventListener("click", () => activate(t));
    t.addEventListener("keydown", (e) => {
      let next = null;
      if (e.key === "ArrowRight") next = triggers[(i + 1) % triggers.length];
      else if (e.key === "ArrowLeft") next = triggers[(i - 1 + triggers.length) % triggers.length];
      else if (e.key === "Home") next = triggers[0];
      else if (e.key === "End") next = triggers[triggers.length - 1];
      if (!next) return;
      e.preventDefault();
      activate(next);
      next.focus();
    });
  });

  panel.appendChild(tabs);
  panel.appendChild(bodies);

  // ── Guidance steps ───────────────────────────────────────────────────────
  const steps = el("ol", {
    id: "agent-steps",
    className: "flex flex-wrap items-center gap-x-2 gap-y-2 border-t px-5 py-3 text-xs",
  });
  [
    { n: 1, text: "Copy the command" },
    { n: 2, text: "Run it on the device" },
    { n: 3, text: "Report received" },
  ].forEach((s, i) => {
    const li = el("li", {
      className: `step flex items-center gap-1.5 ${i === 0 ? "step-current" : "step-pending"}`,
      dataset: { step: s.n },
    });
    li.appendChild(el("span", { className: "step-dot flex size-4 items-center justify-center rounded-full border text-[10px] font-semibold" }, s.n));
    li.appendChild(el("span", { className: "step-text" }, s.text));
    steps.appendChild(li);
    if (i < 2) {
      steps.appendChild(el("span", { className: "text-muted-foreground", "aria-hidden": "true" }, "→"));
    }
  });
  panel.appendChild(steps);

  // ── Live status ──────────────────────────────────────────────────────────
  const waiting = el("div", {
    className: "agent-waiting flex items-center gap-2 border-t px-5 py-3 text-sm text-muted-foreground",
    id: "agent-waiting",
    role: "status",
    "aria-live": "polite",
  });
  waiting.appendChild(el("span", { className: "waiting-dot size-1.5 rounded-full bg-primary animate-pulse" }));
  waiting.appendChild(document.createTextNode(" Waiting for the agent to report…"));
  panel.appendChild(waiting);

  root.appendChild(panel);
}

function showAgentError(msg) {
  const root = document.getElementById("agent-slot");
  if (!root) return;
  root.appendChild(el("div", { className: "alert alert-destructive agent-error" },
    el("span", { className: "alert-title" }, `Agent session error: ${msg}`)));
  setAgentStatus("error", "Session error");
}

/** Update the status badge in the agent card header. */
function setAgentStatus(kind, text) {
  const badge = document.getElementById("agent-status");
  if (!badge) return;
  badge.className = "badge shrink-0 " + (
    kind === "success" ? "badge-success" :
    kind === "error"   ? "badge-destructive" : "badge-secondary");
  badge.textContent = text;
}

/** Mark a guidance step as current / done / pending. */
function setStep(n, state) {
  const step = document.querySelector(`#agent-steps [data-step="${n}"]`);
  if (!step) return;
  step.classList.remove("step-current", "step-done", "step-pending");
  step.classList.add(state === "done" ? "step-done"
                    : state === "pending" ? "step-pending" : "step-current");
  const dot = step.querySelector(".step-dot");
  if (dot) dot.textContent = state === "done" ? "✓" : n;
}

// ---------------------------------------------------------------------------
// Render — browser sections
// ---------------------------------------------------------------------------

function renderBrowserSections(data) {
  const root = document.getElementById("browser-sections");
  if (!root) return;

  const card = groupCard("This device", [
    kvGroup("Browser & OS", buildOSRows(data.uach)),
    kvGroup("Graphics",       buildGPURows(data.gpu)),
    kvGroup("Battery",        buildBatteryRows(data.battery)),
  ]);
  root.appendChild(card);
}

// ---------------------------------------------------------------------------
// Render — agent hardware sections
// ---------------------------------------------------------------------------

function renderAgentPlaceholder() {
  const root = document.getElementById("agent-sections");
  if (!root) return;
  root.classList.remove("hidden");

  const body = el("div", { className: "card-content py-4" });
  body.appendChild(el("div", {
    className: "flex items-center gap-2 text-sm text-muted-foreground",
  }, el("span", { className: "size-1.5 animate-pulse rounded-full bg-primary" }),
     el("span", {}, "Waiting for the agent to report…")));

  root.appendChild(makeAgentCard(body));
}

function renderAgentSections(d) {
  const root = document.getElementById("agent-sections");
  if (!root) return;
  root.classList.remove("hidden");

  const body = el("div");
  [
    kvGroup("System",    buildSystemRows(d)),
    kvGroup("Processor", buildAgentCPURows(d)),
    kvGroup("Memory",    buildAgentRAMRows(d)),
    kvGroup("Storage",   buildDisksRows(d.disks)),
    kvGroup("Network",   buildNICRows(d)),
    kvGroup("Operating system", buildAgentOSRows(d)),
  ].forEach((g) => body.appendChild(g));

  fillAgentCard(body);
}

/** The "Reported by the agent" card shell — created once, refilled later. */
function makeAgentCard(body) {
  const card = el("section", { className: "card agent-card overflow-hidden" });
  const head = el("div", { className: "card-header border-b bg-muted/40 py-3" });
  head.appendChild(el("h2", {
    className: "card-title text-xs font-semibold uppercase tracking-wider text-muted-foreground",
  }, "Reported by the agent"));
  card.appendChild(head);
  card.appendChild(body);

  agentCard = { card, body };
  return card;
}

function fillAgentCard(body) {
  if (!agentCard) return;
  agentCard.body.replaceWith(body);
  agentCard.body = body;
}

// ---------------------------------------------------------------------------
// Render — software inventory + Windows activation
// ---------------------------------------------------------------------------

/**
 * Inserts two cards below the hardware card:
 *   1. Software inventory card (one row per app, with a status dot)
 *   2. Windows Activation card
 *
 * Both come from the agent, so they live in the agent column.
 */
function renderSoftwareSection(data) {
  const slot = document.getElementById("agent-sections");
  if (!slot) return;

  // ── Windows Activation ───────────────────────────────────────────────────
  if (data.windows_activation) {
    const act = data.windows_activation;
    const activated = act.status_code === 1;

    const card = el("section", { className: "card sw-section overflow-hidden" });
    const head = el("div", { className: "card-header border-b bg-muted/40 py-3" });
    head.appendChild(el("h2", {
      className: "card-title text-xs font-semibold uppercase tracking-wider text-muted-foreground",
    }, "Windows activation"));
    card.appendChild(head);

    const body = el("div", { className: "card-content py-4" });

    // Status badge
    const badge = el("div", {
      className: `activation-badge mb-3 inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm font-semibold ${
        activated
          ? "border-success/30 bg-success/10 text-success"
          : "border-warning/40 bg-warning/10 text-warning-foreground"}`,
    });
    badge.appendChild(el("span", { className: "act-dot size-2 rounded-full bg-current" }));
    badge.appendChild(document.createTextNode(act.status ?? "Unknown"));
    body.appendChild(badge);

    // Detail rows
    const detailRows = [
      ["Product",     act.product_name],
      ["Partial key", act.partial_key ? `XXXXX-XXXXX-XXXXX-XXXXX-${act.partial_key}` : null],
      ["Status code", act.status_code != null ? String(act.status_code) : null],
    ].filter(([, v]) => v);

    if (detailRows.length) {
      body.appendChild(buildTable(detailRows));
    }

    card.appendChild(body);
    slot.appendChild(card);
  }

  // ── Software Inventory ───────────────────────────────────────────────────
  if (data.software_checks && data.software_checks.length > 0) {
    const card = el("section", { className: "card sw-section overflow-hidden" });
    const head = el("div", { className: "card-header border-b bg-muted/40 py-3" });
    head.appendChild(el("h2", {
      className: "card-title text-xs font-semibold uppercase tracking-wider text-muted-foreground",
    }, "Software inventory"));
    card.appendChild(head);

    const table = el("table", { className: "table table-compact" });

    // Header row
    const thead = el("thead", { className: "table-header" });
    const headTr = el("tr", { className: "table-row" });
    ["Application", "Status", "Version", "Detection"].forEach((h) => {
      headTr.appendChild(el("th", { className: "table-head" }, h));
    });
    thead.appendChild(headTr);
    table.appendChild(thead);

    const tbody = el("tbody", { className: "table-body" });

    // One row per app
    data.software_checks.forEach(app => {
      const tr = el("tr", { className: "table-row sw-row-ok" });

      // Name
      tr.appendChild(el("td", { className: "sw-name table-cell font-medium" }, app.name));

      // Status dot + label
      const tdStatus = el("td", { className: "sw-status table-cell" });
      const statusWrap = el("span", {
        className: `sw-pill inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold ${
          app.installed
            ? "bg-success/15 text-success"
            : "bg-destructive/15 text-destructive"}`,
      });
      statusWrap.appendChild(el("span", { className: "sw-dot size-1.5 rounded-full bg-current" }));
      statusWrap.appendChild(document.createTextNode(app.installed ? "Installed" : "Missing"));
      tdStatus.appendChild(statusWrap);
      tr.appendChild(tdStatus);

      // Version
      tr.appendChild(el("td", { className: "sw-version table-cell font-mono text-xs text-muted-foreground" },
        app.version || "—"));

      // Detection method — friendly labels
      const methodMap = {
        registry:       "Registry",
        filesystem:     "File system",
        service:        "Windows service",
        appx:           "MSIX package",
        mdm_enrollment: "MDM enrollment",
        not_found:      "",
      };
      tr.appendChild(el("td", { className: "sw-method table-cell text-xs text-muted-foreground" },
        methodMap[app.method] ?? app.method ?? ""));

      tbody.appendChild(tr);
    });

    table.appendChild(tbody);
    card.appendChild(table);
    slot.appendChild(card);
  }
}

// ---------------------------------------------------------------------------
// Rendering helpers — cards, groups, tables
// ---------------------------------------------------------------------------

/** A titled group of label/value rows. */
function kvGroup(title, rows) {
  const group = el("div", { className: "px-5 py-4" });
  group.appendChild(el("h3", {
    className: "mb-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground",
  }, title));
  if (rows && rows.length) {
    group.appendChild(buildTable(rows));
  } else {
    group.appendChild(el("p", { className: "text-sm text-muted-foreground" }, "No data"));
  }
  return group;
}

/** A card that stacks titled groups separated by hairlines. */
function groupCard(title, groups) {
  const card = el("section", { className: "card overflow-hidden" });
  const head = el("div", { className: "card-header border-b bg-muted/40 py-3" });
  head.appendChild(el("h2", {
    className: "card-title text-xs font-semibold uppercase tracking-wider text-muted-foreground",
  }, title));
  card.appendChild(head);
  groups.forEach((g) => card.appendChild(g));
  return card;
}

/**
 * shadcn Table from [label, value, note] rows.
 */
function buildTable(rows) {
  const table = el("table", { className: "table" });
  const tbody = el("tbody", { className: "table-body" });

  rows.forEach(([label, value, note]) => {
    const tr = el("tr", { className: "table-row" });

    const td1 = el("td", {
      className: "label-cell table-cell w-[40%] font-medium text-muted-foreground",
    }, label);

    const td2 = el("td", { className: "value-cell table-cell font-mono text-xs break-words" });
    if (value == null || value === "") {
      td2.appendChild(el("span", { className: "unavailable text-xs not-italic text-muted-foreground" },
        "Not available"));
    } else {
      td2.textContent = String(value);
    }
    if (note) td2.appendChild(el("span", { className: "note text-xs text-muted-foreground" }, ` — ${note}`));

    tr.appendChild(td1);
    tr.appendChild(td2);
    tbody.appendChild(tr);
  });

  table.appendChild(tbody);
  return table;
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
// Utilities
// ---------------------------------------------------------------------------

function fmtSec(sec) {
  if (sec == null) return null;
  const m = Math.floor(sec / 60), s = sec % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

/**
 * Inline SVG icon (lucide geometry), 24×24, currentColor.
 */
function icon(name) {
  const paths = {
    terminal: '<path d="m4 17 6-6-6-6"/><path d="M12 19h8"/>',
    shield:  '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>',
    check:   '<path d="M20 6 9 17l-5-5"/>',
    alert:   '<circle cx="12" cy="12" r="10"/><path d="M12 8v4"/><path d="M12 16h.01"/>',
    x:       '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  };
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("class", "size-3.5");
  svg.innerHTML = paths[name] ?? paths.alert;
  return svg;
}

/**
 * Tiny element factory.
 * el("div", { className: "foo", dataset: { bar: "baz" } }, child1, "text")
 *
 * Attribute keys containing "-" (aria-*, data-*) and the special ones
 * (role, list, for, style) are set as real attributes; everything else is
 * assigned as a DOM property.
 */
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  Object.entries(attrs).forEach(([k, v]) => {
    if (k === "dataset") {
      Object.entries(v).forEach(([dk, dv]) => { node.dataset[dk] = dv; });
      return;
    }
    if (v === null || v === undefined || v === false) return;
    if (v === true) { node.setAttribute(k, ""); return; }
    if (k === "className") { node.className = v; return; }
    if (k.includes("-") || ["role", "list", "for", "style"].indexOf(k) !== -1) {
      node.setAttribute(k, v);
      return;
    }
    node[k] = v;
  });
  children.forEach(c => {
    if (c === null || c === undefined || c === false) return;
    if (typeof c === "object" && c.nodeType) node.appendChild(c);
    else node.appendChild(document.createTextNode(String(c)));
  });
  return node;
}

async function loadUser() {
  try {
    const r = await fetch("/api/me");
    if (!r.ok) return;
    const u = await r.json();
    const box = document.getElementById("user-info");
    if (!box) return;
    box.textContent = `${u.name || ""} (${u.email || ""})`;
    if (u.sso) {
      const a = document.createElement("a");
      a.href = "/logout";
      a.className = "hover:text-foreground hover:underline";
      a.textContent = " · Logout";
      box.appendChild(a);
    } else {
      box.append(" · DEV MODE");
    }
  } catch (e) { /* ignore */ }
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
