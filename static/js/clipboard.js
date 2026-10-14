/**
 * Shared clipboard utility for the handover portal.
 *
 * copyText(text, opts) tries, in order:
 *   1. `navigator.clipboard.writeText` (secure contexts only: https/localhost)
 *   2. `document.execCommand('copy')` via an off-screen textarea
 *      (PRIMARY path on plain http://IP:port, where the Clipboard API
 *      does not exist)
 *   3. A manual-copy modal with preselected text + file download.
 *
 * It never fails silently: it always resolves
 * `{ ok, method: 'clipboard-api' | 'exec-command' | 'manual', error? }`
 * and gives visible UI feedback (success message or the modal).
 *
 * Call it SYNCHRONOUSLY inside the click handler (the text must already
 * be in memory — pre-fetch anything beforehand) so the browser keeps the
 * user activation needed for tiers 1 and 2.
 *
 * Loaded as a classic script before app.js; exposes `window.copyText`.
 */
"use strict";

(function () {
  var MODAL_ID = "copy-manual-modal";

  function downloadFile(filename, text) {
    var blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename || "copy.txt";
    document.body.appendChild(a);
    a.click();
    setTimeout(function () {
      URL.revokeObjectURL(a.href);
      a.remove();
    }, 5000);
  }

  function showManualModal(text, filename, reason) {
    var overlay = document.getElementById(MODAL_ID);
    if (overlay) overlay.remove();

    overlay = document.createElement("div");
    overlay.id = MODAL_ID;
    overlay.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.65);" +
      "display:flex;align-items:center;justify-content:center;z-index:9999;";

    var box = document.createElement("div");
    box.style.cssText = "background:#161b22;border:1px solid #2a3140;border-radius:6px;" +
      "padding:16px;max-width:520px;width:90%;color:#e6edf3;font-family:system-ui,sans-serif;";

    var title = document.createElement("div");
    title.style.cssText = "font-weight:600;margin-bottom:8px;";
    title.textContent = "Automatic copy did not work";
    box.appendChild(title);

    var why = document.createElement("div");
    why.style.cssText = "font-size:.82rem;color:#8b949e;margin-bottom:8px;";
    why.textContent = reason ||
      "The browser blocked automatic copy (often on plain http origins). " +
      "Press Ctrl+C to copy manually.";
    box.appendChild(why);

    var ta = document.createElement("textarea");
    ta.readOnly = true;
    ta.value = text;
    ta.style.cssText = "width:100%;min-height:90px;background:#0d1117;color:#79c0ff;" +
      "border:1px solid #2a3140;border-radius:4px;padding:8px;" +
      "font-family:monospace;font-size:.75rem;";
    box.appendChild(ta);

    var row = document.createElement("div");
    row.style.cssText = "margin-top:10px;display:flex;gap:8px;";

    function btn(label, onclick) {
      var b = document.createElement("button");
      b.textContent = label;
      b.style.cssText = "background:#1e2430;color:#e6edf3;border:1px solid #2a3140;" +
        "border-radius:4px;padding:6px 12px;cursor:pointer;";
      b.addEventListener("click", onclick);
      row.appendChild(b);
      return b;
    }

    btn("Download " + (filename || "file"), function () {
      downloadFile(filename || "copy.txt", text);
    });
    btn("Close", function () { overlay.remove(); });

    box.appendChild(row);
    overlay.appendChild(box);
    document.body.appendChild(overlay);

    ta.focus();
    ta.select();
    try { ta.setSelectionRange(0, text.length); } catch (_) { /* ignore */ }

    overlay.addEventListener("click", function (e) {
      if (e.target === overlay) overlay.remove();
    });
  }

  function execCommandCopy(text) {
    // Must be in the DOM and selectable: fixed + transparent, NEVER display:none.
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    var prev = document.activeElement;
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    try { ta.setSelectionRange(0, text.length); } catch (_) { /* ignore */ }
    var ok = false, error = "";
    try {
      ok = document.execCommand("copy");
    } catch (e) {
      error = (e && e.name ? e.name : "Error") + ": " + (e && e.message ? e.message : e);
    }
    ta.remove();
    if (prev && prev.focus) { try { prev.focus(); } catch (_) { /* ignore */ } }
    if (error) return { ok: false, method: "exec-command", error: error };
    return { ok: !!ok, method: "exec-command" };
  }

  async function copyText(text, opts) {
    opts = opts || {};
    var filename = opts.filename || "copy.txt";
    var lastError = "";

    // Tier 1 — Clipboard API (only exists in secure contexts).
    if (window.isSecureContext && navigator.clipboard && navigator.clipboard.writeText) {
      try {
        await navigator.clipboard.writeText(text);
        return { ok: true, method: "clipboard-api" };
      } catch (e) {
        lastError = (e && e.name ? e.name : "Error") + ": " + (e && e.message ? e.message : e);
      }
    } else {
      lastError = typeof navigator.clipboard === "undefined"
        ? "navigator.clipboard is undefined (insecure origin)"
        : "secure context without clipboard.writeText";
    }

    // Tier 2 — execCommand (primary path on http://IP:port).
    var r2 = execCommandCopy(text);
    if (r2.ok) return r2;
    if (r2.error) lastError = r2.error;

    // Tier 3 — manual modal (never silent).
    showManualModal(text, filename,
      "The browser blocked automatic copy" +
      (lastError ? " (" + lastError + ")" : "") +
      ". Press Ctrl+C to copy manually, or download the file.");
    return { ok: false, method: "manual", error: lastError };
  }

  window.copyText = copyText;
})();
