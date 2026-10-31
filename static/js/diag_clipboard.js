"use strict";

/* Clipboard diagnostics page. Self-hosted so the page works under CSP. */

const PROBE_TEXT = "clipboard-probe-0123456789";
const facts = {};

function row(k, v, cls) {
  const tr = document.createElement("tr");
  tr.className = "table-row";
  const td1 = document.createElement("td");
  td1.className = "table-cell w-[38%] font-medium text-muted-foreground";
  td1.textContent = k;
  const td2 = document.createElement("td");
  td2.className = "table-cell font-mono text-xs break-all" + (cls ? " " + cls : "");
  td2.textContent = String(v);
  tr.appendChild(td1);
  tr.appendChild(td2);
  document.querySelector("#facts tbody").appendChild(tr);
}

async function permissionState() {
  if (!navigator.permissions || !navigator.permissions.query) return "permissions-api-unavailable";
  try {
    const s = await navigator.permissions.query({ name: "clipboard-write" });
    return s.state;
  } catch (e) {
    return "query-threw: " + (e && e.name ? e.name : e);
  }
}

async function methodA(text) {
  // Mirrors the portal's tier-1 path.
  try {
    await navigator.clipboard.writeText(text);
    return { ok: true, method: "clipboard-api" };
  } catch (e) {
    return { ok: false, method: "clipboard-api",
             error: (e && e.name ? e.name : "Error") + ": " + (e && e.message ? e.message : e) };
  }
}

function methodB(text) {
  // Mirrors the portal's tier-2 path (shared utility in static/js/clipboard.js).
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  const prev = document.activeElement;
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  try { ta.setSelectionRange(0, text.length); } catch (_) { /* ignore */ }
  let ok = false, err = "";
  try {
    ok = document.execCommand("copy");
  } catch (e) {
    err = (e && e.name ? e.name : "Error") + ": " + (e && e.message ? e.message : e);
  }
  ta.remove();
  if (prev && prev.focus) { try { prev.focus(); } catch (_) { /* ignore */ } }
  return err ? { ok: false, method: "exec-command", error: err }
             : { ok: !!ok, method: "exec-command" };
}

function fmt(r) { return r.ok ? "OK" : ("FAIL" + (r.error ? " (" + r.error + ")" : "")); }

async function collect() {
  facts.isSecureContext = window.isSecureContext;
  facts.protocol = location.protocol;
  facts.host = location.host;
  facts.clipboardType = typeof navigator.clipboard;
  facts.writeTextType = (navigator.clipboard && typeof navigator.clipboard.writeText);
  facts.execCommandSupported = (typeof document.queryCommandSupported === "function")
    ? document.queryCommandSupported("copy") : "unknown";
  facts.permission = await permissionState();
  facts.userAgent = navigator.userAgent;
  facts.platform = navigator.platform;
  return facts;
}

function renderFacts() {
  document.querySelector("#facts tbody").innerHTML = "";
  row("isSecureContext", facts.isSecureContext, facts.isSecureContext ? "text-success" : "text-destructive");
  row("protocol", facts.protocol);
  row("host", facts.host);
  row("typeof navigator.clipboard", facts.clipboardType,
      facts.clipboardType === "undefined" ? "text-destructive" : "text-success");
  row("typeof writeText", facts.writeTextType);
  row("queryCommandSupported('copy')", facts.execCommandSupported);
  row("clipboard-write permission", facts.permission);
  row("userAgent", facts.userAgent);
  row("platform", facts.platform);
  document.getElementById("report").value = JSON.stringify(facts, null, 2);
}

document.getElementById("btn-a").addEventListener("click", async () => {
  const r = (typeof navigator.clipboard === "undefined")
    ? { ok: false, method: "clipboard-api", error: "navigator.clipboard is undefined" }
    : await methodA(PROBE_TEXT);
  facts.methodA = r;
  document.getElementById("res-a").textContent = fmt(r);
  renderFacts();
});

document.getElementById("btn-b").addEventListener("click", () => {
  const r = methodB(PROBE_TEXT);
  facts.methodB = r;
  document.getElementById("res-b").textContent = fmt(r) + " — now paste into the box below";
  renderFacts();
});

document.getElementById("btn-copy").addEventListener("click", async () => {
  const ta = document.getElementById("report");
  ta.select();
  try {
    if (typeof navigator.clipboard !== "undefined") {
      await navigator.clipboard.writeText(ta.value);
    } else {
      document.execCommand("copy");
    }
  } catch (_) { /* report stays selected for manual Ctrl+C */ }
});

document.getElementById("btn-json").addEventListener("click", () => {
  const blob = new Blob([JSON.stringify(facts, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "clipboard-diag.json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
});

document.getElementById("btn-send").addEventListener("click", async () => {
  try {
    const resp = await fetch("/diag/clipboard/report", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(facts),
    });
    document.getElementById("res-send").textContent =
      resp.ok ? "logged on server" : ("server: HTTP " + resp.status);
  } catch (e) {
    document.getElementById("res-send").textContent = "send failed: " + e;
  }
});

collect().then(renderFacts);
