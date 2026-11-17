/**
 * sync.js — the agent flow.
 *
 * Start sync: create a session code, show it big with a countdown and the
 * one-line commands for Windows and Linux/macOS. Poll the existing session
 * endpoint every 2 s; when the report arrives, show the result live and let
 * the engineer attach it to a case (default: the open case with the same
 * serial). Also usable inside the case page drawer (window.syncFlow.open).
 *
 * The code is short-lived and single-use; only the code-based agent
 * endpoints are reachable without sign-in — nothing new is added here.
 */
"use strict";

(function () {
  var portal = window.portal;

  var state = {
    code: null,
    ttl: 0,
    deadline: 0,
    timer: null,
    countdownTimer: null,
    payload: null,
    handoverId: null,
    onDone: null,
  };

  function base() {
    var host = document.body.getAttribute("data-app-host");
    if (host) {
      if (!/^https?:\/\//.test(host)) {
        var scheme = window.location.protocol === "https:" ? "https://" : "http://";
        host = scheme + host;
      }
      return host.replace(/\/+$/, "");
    }
    return window.location.origin;
  }

  function commands(code) {
    var url = base();
    var windows =
      '$env:ONBOARD_URL="' + url + '"; $env:ONBOARD_CODE="' + code + '"\n' +
      "iwr $env:ONBOARD_URL/static/agent.ps1 -UseBasicParsing | iex";
    var unix =
      'curl -sL ' + url + '/static/agent.sh | ONBOARD_URL=' + url +
      ' ONBOARD_CODE=' + code + ' bash';
    return { windows: windows, unix: unix };
  }

  function stopPolling() {
    if (state.timer) { clearInterval(state.timer); state.timer = null; }
    if (state.countdownTimer) { clearInterval(state.countdownTimer); state.countdownTimer = null; }
  }

  function show(id) {
    var node = document.getElementById(id);
    if (node) node.classList.remove("hidden");
  }
  function hide(id) {
    var node = document.getElementById(id);
    if (node) node.classList.add("hidden");
  }

  function startSync(handoverId, onDone) {
    state.handoverId = handoverId || null;
    state.onDone = onDone || null;
    var query = handoverId ? "?handover_id=" + encodeURIComponent(handoverId) : "";
    return portal.request("/api/session/new" + query)
      .then(function (session) {
        state.code = session.code;
        state.ttl = session.ttl_seconds || 600;
        state.deadline = Date.now() + state.ttl * 1000;
        state.payload = null;
        var cmds = commands(session.code);
        var codeNode = document.getElementById("sync-code");
        if (codeNode) {
          codeNode.textContent = session.code;
          codeNode.setAttribute("data-sync-code", session.code);
        }
        var win = document.getElementById("sync-cmd-windows");
        var unix = document.getElementById("sync-cmd-unix");
        if (win) win.textContent = cmds.windows;
        if (unix) unix.textContent = cmds.unix;
        hide("sync-start");
        hide("sync-result");
        show("sync-waiting");
        var waiting = document.querySelector("[data-waiting-text]");
        if (waiting) waiting.textContent = "Waiting for the device…";
        pollLoop();
        return session;
      })
      .catch(function (error) {
        portal.toast(error.message, "error");
        throw error;
      });
  }

  function tickCountdown() {
    var node = document.getElementById("sync-countdown");
    if (!node) return;
    var left = Math.max(0, Math.round((state.deadline - Date.now()) / 1000));
    var minutes = Math.floor(left / 60);
    var seconds = left % 60;
    node.textContent = (minutes < 10 ? "0" : "") + minutes + ":" + (seconds < 10 ? "0" : "") + seconds;
    if (left <= 0) {
      stopPolling();
      var waiting = document.querySelector("[data-waiting-text]");
      if (waiting) waiting.textContent = "The code expired. Start again.";
    }
  }

  function pollLoop() {
    stopPolling();
    state.countdownTimer = setInterval(tickCountdown, 1000);
    tickCountdown();
    state.timer = setInterval(pollOnce, 2000);
    pollOnce();
  }

  function pollOnce() {
    if (!state.code) return;
    fetch("/api/session/" + encodeURIComponent(state.code) + "/data", {
      credentials: "same-origin",
    }).then(function (res) {
      if (res.status === 202) return null;
      if (!res.ok) throw new Error("Polling failed (" + res.status + ")");
      return res.json();
    }).then(function (body) {
      if (!body || body.status !== "ready") return;
      stopPolling();
      state.payload = body.data;
      renderResult(body.data);
    }).catch(function () { /* transient; the next tick retries */ });
  }

  function factRow(label, value) {
    var wrap = portal.el("div", "fact");
    wrap.appendChild(portal.el("dt", "", label));
    var dd = portal.el("dd", "", value === undefined || value === null || value === "" ? "—" : String(value));
    wrap.appendChild(dd);
    return wrap;
  }

  function renderResult(payload) {
    hide("sync-waiting");
    show("sync-result");
    var serialNode = document.getElementById("sync-result-serial");
    if (serialNode) serialNode.textContent = payload.serial || "—";
    var facts = document.getElementById("sync-result-facts");
    if (facts) {
      facts.textContent = "";
      var expectedSerial = state.expectedSerial || null;
      var matchNode = portal.el("div", "fact");
      matchNode.appendChild(portal.el("dt", "", "Serial match"));
      var matchValue;
      if (expectedSerial) {
        var ok = (payload.serial || "").trim().toUpperCase() === expectedSerial.trim().toUpperCase();
        matchValue = portal.el("dd", ok ? "state-ok" : "state-fail", ok ? "✓ matches" : "✕ differs");
      } else {
        matchValue = portal.el("dd", "", payload.serial || "—");
      }
      matchNode.appendChild(matchValue);
      facts.appendChild(matchNode);
      facts.appendChild(factRow("Model", payload.model));
      facts.appendChild(factRow("OS", (payload.os_name || "") + " " + (payload.os_version || "")));
      facts.appendChild(factRow("RAM", payload.ram_gb ? payload.ram_gb + " GB" : "—"));
      if (payload.disks && payload.disks.length) {
        facts.appendChild(factRow("Disk", payload.disks[0].size_gb + " GB " + (payload.disks[0].type || "")));
      }
      if (payload.windows_activation) {
        var activated = payload.windows_activation.status_code === 1;
        facts.appendChild(factRow("Activation", activated ? "Activated" : "Not activated"));
      }
    }
    var software = document.getElementById("sync-result-software");
    if (software) {
      software.textContent = "";
      (payload.software_checks || []).forEach(function (check) {
        var item = portal.el("li", "software-item");
        var icon = portal.el("span", check.installed ? "state-ok" : "state-fail", check.installed ? "✓" : "✕");
        var name = portal.el("span", "", check.name || check.id || "");
        item.appendChild(icon);
        item.appendChild(name);
        software.appendChild(item);
      });
      if (!(payload.software_checks || []).length) {
        var note = portal.el("li", "muted", "No software checks in this report (the Linux/macOS agent collects hardware only).");
        software.appendChild(note);
      }
    }
    rememberRecent(payload);
    var waiting = document.querySelector("[data-waiting-text]");
    if (waiting) waiting.textContent = "";
    suggestDefaultCase(payload);
  }

  // -- attach to case -----------------------------------------------------------
  function suggestDefaultCase(payload) {
    if (!payload || !payload.serial) return;
    portal.request("/api/handovers/active?serial=" + encodeURIComponent(payload.serial))
      .then(function (active) {
        var results = document.getElementById("attach-results");
        if (results && active && active.id) {
          results.textContent = "";
          var row = portal.el("div", "recipient-row");
          var label = portal.el("span", "", "Open case with this serial");
          var attach = portal.actionButton("Attach", "btn-default btn-sm");
          attach.addEventListener("click", function () {
            attachToCase(active.id, active.kind || "handover");
          });
          row.appendChild(label);
          row.appendChild(attach);
          results.appendChild(row);
          if (window.syncFlow) state.expectedSerial = active.device_serial;
          if (state.onDone) state.onDone(active);
        }
      }).catch(function () { /* no open case; the search below works */ });
  }

  function attachSearch(query) {
    var results = document.getElementById("attach-results");
    if (!results) return;
    results.textContent = "";
    if (!query || query.length < 2) return;
    portal.request("/api/handovers?q=" + encodeURIComponent(query) + "&page_size=8")
      .then(function (list) {
        results.textContent = "";
        (list.items || []).forEach(function (row) {
          var line = portal.el("div", "recipient-row");
          var label = portal.el("span", "", row.device_serial + " · " + (row.kind === "maintenance" ? "Maintenance" : "Handover"));
          var attach = portal.actionButton("Attach", "btn-outline btn-sm");
          attach.addEventListener("click", function () {
            attachToCase(row.id, row.kind || "handover");
          });
          line.appendChild(label);
          line.appendChild(attach);
          results.appendChild(line);
        });
        if (!(list.items || []).length) {
          results.appendChild(portal.el("p", "muted", "No case found for this search."));
        }
      }).catch(function (error) {
        results.textContent = "";
        results.appendChild(portal.el("p", "muted", error.message));
      });
  }

  function attachToCase(caseId, kind) {
    if (!state.payload) {
      portal.toast("No report to attach yet.", "error");
      return;
    }
    var payload = Object.assign({}, state.payload);
    delete payload.partial_key;
    portal.apiJson("/api/handovers/" + caseId + "/attach-report", {
      method: "POST",
      body: JSON.stringify({ payload: payload }),
    }).then(function () {
      portal.toast("Report attached to the case.", "success");
      rememberRecent(state.payload, caseId, kind);
      if (state.onDone) state.onDone({ id: caseId });
      state.payload = null;
      resetToStart();
    }).catch(function (error) {
      portal.toast(error.message, "error");
    });
  }

  function createCase(kind) {
    if (!state.payload || !state.payload.serial) {
      portal.toast("The report has no serial yet.", "error");
      return;
    }
    portal.apiJson("/api/handovers", {
      method: "POST",
      body: JSON.stringify({ device_serial: state.payload.serial, kind: kind }),
    }).then(function (created) {
      return attachToCase(created.id, kind);
    }).catch(function (error) {
      portal.toast(error.message, "error");
    });
  }

  // -- recent syncs (local) ---------------------------------------------------------
  var RECENT_KEY = "recent-syncs";

  function rememberRecent(payload, caseId, kind) {
    var list = [];
    try { list = JSON.parse(window.localStorage.getItem(RECENT_KEY) || "[]"); } catch (e) { list = []; }
    list.unshift({
      serial: payload.serial || "—",
      model: payload.model || "",
      at: new Date().toISOString(),
      attached: caseId || null,
      kind: kind || null,
      ok: !!payload.serial,
    });
    list = list.slice(0, 10);
    try { window.localStorage.setItem(RECENT_KEY, JSON.stringify(list)); } catch (e) { /* fine */ }
    renderRecent();
  }

  function renderRecent() {
    var node = document.getElementById("recent-syncs");
    if (!node) return;
    node.textContent = "";
    var list = [];
    try { list = JSON.parse(window.localStorage.getItem(RECENT_KEY) || "[]"); } catch (e) { list = []; }
    if (!list.length) {
      node.appendChild(portal.el("li", "muted", "No syncs yet."));
      return;
    }
    list.forEach(function (item) {
      var line = portal.el("li", "recent-sync-row");
      var when = new Date(item.at);
      line.appendChild(portal.el("span", "mono", item.serial));
      line.appendChild(portal.el("span", "muted", (item.model || "") + " · " + when.toLocaleTimeString()));
      line.appendChild(portal.el(
        "span",
        item.attached ? "state-ok" : "state-pending",
        item.attached ? (item.kind === "maintenance" ? "attached · maintenance" : "attached · handover") : "not attached"
      ));
      node.appendChild(line);
    });
  }

  function resetToStart() {
    stopPolling();
    hide("sync-waiting");
    hide("sync-result");
    show("sync-start");
  }

  // -- page wiring -------------------------------------------------------------------
  function bootPage() {
    var start = document.getElementById("sync-start-button");
    if (!start) return; // embedded flow only
    start.addEventListener("click", function () { startSync(null, null); });
    var cancel = document.getElementById("sync-cancel");
    if (cancel) cancel.addEventListener("click", resetToStart);
    var again = document.getElementById("sync-again");
    if (again) again.addEventListener("click", resetToStart);
    var search = document.getElementById("attach-search");
    if (search) {
      var timer = null;
      search.addEventListener("input", function () {
        clearTimeout(timer);
        var q = search.value.trim();
        timer = setTimeout(function () { attachSearch(q); }, 250);
      });
    }
    var createHandover = document.getElementById("attach-create-handover");
    if (createHandover) createHandover.addEventListener("click", function () { createCase("handover"); });
    var createMaintenance = document.getElementById("attach-create-maintenance");
    if (createMaintenance) createMaintenance.addEventListener("click", function () { createCase("maintenance"); });
    portal.$all(".copy-btn").forEach(function (button) {
      button.addEventListener("click", function () {
        var target = document.getElementById(button.getAttribute("data-copy-target"));
        if (target && window.copyText) {
          window.copyText(target.textContent);
        } else {
          portal.toast("Copy is not available here.", "error");
        }
      });
    });
    renderRecent();
  }

  // drawer/embedded API for the case page
  window.syncFlow = {
    open: function (options) {
      options = options || {};
      var host = options.appHost;
      if (host) document.body.setAttribute("data-app-host", host);
      var drawer = portal.drawerForm("Sync this device", {});
      var body = portal.el("div", "drawer-body stack");
      var intro = portal.el("p", "field-hint", "Run the command on the employee's PC; the report lands here and is recorded on this case.");
      body.appendChild(intro);
      var startButton = portal.actionButton("Start sync", "btn-default");
      body.appendChild(startButton);
      var codeNode = portal.el("p", "sync-code mono");
      var cmdPre = portal.el("pre", "cmd-pre mono");
      var copyButton = portal.actionButton("Copy command", "btn-outline btn-sm");
      copyButton.classList.add("copy-btn");
      var waiting = portal.el("p", "muted", "");
      body.appendChild(codeNode);
      body.appendChild(cmdPre);
      body.appendChild(copyButton);
      body.appendChild(waiting);
      var drawerBody = drawer.querySelector(".drawer-body");
      drawerBody.appendChild(body);
      startButton.addEventListener("click", function () {
        startSync(options.handoverId, function () {
          portal.closeDrawer();
          window.location.reload();
        });
      });
      copyButton.addEventListener("click", function () {
        if (cmdPre.textContent && window.copyText) window.copyText(cmdPre.textContent);
      });
    },
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootPage);
  } else {
    bootPage();
  }
})();
