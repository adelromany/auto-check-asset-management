/* Handover dashboard: one JSON read feeds every block. */
"use strict";
(function () {
  var portal = window.portal;
  var charts = window.dashboardCharts || {};
  var state = {
    period: "30d",
    company: "all",
    filter: "attention",
    stage: null,
    engineer: null,
  };
  var last = null;
  var busy = false;

  var FILTER_TITLES = {
    attention: "Needs attention",
    ready: "Ready labs",
    complete: "Complete",
    not_complete: "Not complete",
    missing: "Missing part",
    engineer: "Engineer",
  };

  function badge(text, cls) {
    return portal.el("span", cls || "badge badge-outline", text);
  }

  function ago(created) {
    if (!created) return "—";
    var seconds = Math.max(0, Math.floor((Date.now() - new Date(created).getTime()) / 1000));
    if (seconds < 60) return "now";
    var minutes = Math.floor(seconds / 60);
    if (minutes < 60) return minutes + "m";
    var hours = Math.floor(minutes / 60);
    if (hours < 24) return hours + "h";
    return Math.floor(hours / 24) + "d";
  }

  function hoursLabel(value) {
    if (value == null) return "—";
    if (value < 1) return "<1 h";
    if (value < 48) return Math.round(value) + " h";
    return (value / 24).toFixed(1).replace(".0", "") + " d";
  }

  function caseRow(item) {
    var row = portal.el("div", "handover-row");
    var serial = portal.el("a", "mono handover-serial", item.device_serial);
    serial.href = "/devices/" + encodeURIComponent(item.device_serial);
    row.appendChild(serial);
    row.appendChild(portal.el("span", "handover-model", item.device_model || "—"));
    row.appendChild(badge(item.device_company || "—", "badge badge-secondary"));
    var states = portal.el("span", "case-chips");
    var outcomeText = item.outcome === "complete" ? "Complete" : item.outcome === "ready" ? "Ready lab" : "Not complete";
    var outcomeClass = item.outcome === "complete" ? "badge badge-success" : item.outcome === "ready" ? "badge badge-accent" : "badge badge-warning";
    states.appendChild(badge(outcomeText, outcomeClass));
    if (["pending_user", "not_in_snipeit"].indexOf(item.recipient_mode) >= 0) {
      states.appendChild(badge("Waiting user", "badge badge-secondary"));
    }
    if ((item.warnings || []).some(function (warning) { return warning.code === "company_mismatch"; })) {
      var warn = badge("Company differs !", "badge badge-secondary");
      warn.title = (item.device_company || "—") + " / " + (item.recipient_company || "—");
      states.appendChild(warn);
    }
    if (item.status === "stalled") states.appendChild(badge("Stale", "badge badge-secondary"));
    row.appendChild(states);
    row.appendChild(portal.el("span", "handover-recipient", item.recipient_snipeit_name || item.recipient_free_name || "No recipient"));
    var missing = portal.el("span", "handover-missing");
    (item.missing || []).slice(0, 3).forEach(function (part) {
      missing.appendChild(badge(part.replace(/_/g, " "), "badge badge-outline"));
    });
    if ((item.missing || []).length > 3) {
      missing.appendChild(badge("+" + (item.missing.length - 3), "badge badge-secondary"));
    }
    row.appendChild(missing);
    row.appendChild(portal.el("span", "muted mono", ago(item.created_at)));
    var action = portal.el("a", "btn btn-outline btn-sm", item.outcome === "complete" ? "Open" : "Continue");
    action.href = "/handovers/" + item.id;
    row.appendChild(action);
    row.appendChild(portal.caseMenu(item.id, item.status));
    return row;
  }

  function renderCases(payload) {
    var list = document.querySelector("[data-handover-list]");
    if (!list) return;
    list.textContent = "";
    var items = (payload && payload.items) || [];
    if (!items.length) {
      var empty = portal.el("div", "empty", "—");
      empty.setAttribute("data-empty", "");
      list.appendChild(empty);
      return;
    }
    items.forEach(function (item) { list.appendChild(caseRow(item)); });
  }

  function panelTitle(filter, extra) {
    var title = FILTER_TITLES[filter] || "Cases";
    if (extra) title += ": " + extra;
    return title;
  }

  function loadCases() {
    var query = "/api/dashboard/handover/cases?filter=" + encodeURIComponent(state.filter) +
      "&period=" + encodeURIComponent(state.period) +
      "&company=" + encodeURIComponent(state.company);
    if (state.stage) query += "&stage=" + encodeURIComponent(state.stage);
    if (state.engineer) query += "&engineer=" + encodeURIComponent(state.engineer);
    var title = document.querySelector("[data-panel-title]");
    if (title) title.textContent = panelTitle(state.filter, state.stage || state.engineer);
    portal.request(query).then(renderCases)
      .catch(function (error) { portal.toast(error.message, "error"); });
  }

  function setTile(name, value, modifier) {
    var node = document.querySelector('[data-tile="' + name + '"]');
    if (node) node.textContent = String(value || 0);
    var tile = document.querySelector('[data-kpi="' + name + '"]');
    if (tile) {
      tile.className = "tile kpi" + (modifier ? " " + modifier : "");
    }
  }

  function renderTiles(data) {
    var tiles = data.tiles || {};
    setTile("ready", tiles.ready, tiles.ready ? "tile-accent" : "tile-muted");
    setTile("complete", tiles.complete, tiles.complete ? "tile-success" : "tile-muted");
    setTile("not_complete", tiles.not_complete, tiles.not_complete ? "tile-amber" : "tile-muted");

    var perDay = data.per_day || [];
    if (charts.sparkline) {
      charts.sparkline(
        document.querySelector('[data-spark="complete"]'),
        perDay.map(function (point) { return point.completed || 0; })
      );
      charts.sparkline(
        document.querySelector('[data-spark="not_complete"]'),
        perDay.map(function (point) { return point.started || 0; })
      );
    }
    var median = document.querySelector('[data-metric="median"]');
    var average = document.querySelector('[data-metric="average"]');
    var within = document.querySelector('[data-metric="within"]');
    if (median) median.textContent = hoursLabel(tiles.median_hours_to_complete);
    if (average) average.textContent = hoursLabel(tiles.avg_hours_to_complete);
    if (within) within.textContent = tiles.within_24h_percent == null ? "—" : Math.round(tiles.within_24h_percent) + "%";
  }

  function clickableCell(value, filter, company) {
    var cell = portal.el("td", "table-cell");
    var button = portal.el("button", "cell-button", String(value || 0));
    button.type = "button";
    button.setAttribute("data-filter", filter);
    if (company) button.setAttribute("data-company-filter", company);
    cell.appendChild(button);
    return cell;
  }

  function renderCompanies(data) {
    var body = document.querySelector("[data-company-table]");
    if (!body) return;
    body.textContent = "";
    (data.by_company || []).forEach(function (row) {
      var tr = portal.el("tr", "table-row");
      var head = portal.el("td", "table-cell", row.company);
      tr.appendChild(head);
      ["ready", "complete", "not_complete", "waiting_user"].forEach(function (key) {
        tr.appendChild(clickableCell(row[key], key, row.company));
      });
      body.appendChild(tr);
    });
  }

  function barRow(label, value, max, filter, company) {
    var button = portal.el("button", "bar-button");
    button.type = "button";
    button.setAttribute("data-filter", filter);
    if (company) button.setAttribute("data-company-filter", company);
    button.appendChild(portal.el("span", "bar-label", label));
    var track = portal.el("span", "bar-track");
    var fill = portal.el("span", "bar-fill");
    fill.style.width = (max ? Math.round((value / max) * 100) : 0) + "%";
    track.appendChild(fill);
    button.appendChild(track);
    button.appendChild(portal.el("span", "bar-count", String(value)));
    return button;
  }

  function renderReady(data) {
    var host = document.querySelector("[data-ready-bars]");
    if (!host) return;
    host.textContent = "";
    var rows = (data.by_company || []).filter(function (row) { return row.ready; });
    if (!rows.length) {
      host.appendChild(portal.el("p", "muted", "—"));
    } else {
      var max = Math.max.apply(null, rows.map(function (row) { return row.ready; }));
      rows.forEach(function (row) {
        host.appendChild(barRow(row.company, row.ready, max, "ready", row.company));
      });
    }
    var models = document.querySelector("[data-ready-models]");
    if (!models) return;
    models.textContent = "";
    (data.ready_by_model || []).forEach(function (model) {
      var button = portal.el("button", "model-row");
      button.type = "button";
      button.setAttribute("data-filter", "ready");
      button.appendChild(portal.el("span", "truncate", model.model));
      button.appendChild(portal.el("span", "muted", String(model.total)));
      models.appendChild(button);
    });
  }

  function renderMissing(data) {
    var host = document.querySelector("[data-missing-bars]");
    if (!host) return;
    host.textContent = "";
    var rows = data.missing_parts || [];
    if (!rows.length) {
      host.appendChild(portal.el("p", "muted", "—"));
      return;
    }
    var max = Math.max.apply(null, rows.map(function (row) { return row.count; }));
    rows.forEach(function (row) {
      var button = barRow(row.title, row.count, max, "missing");
      button.setAttribute("data-stage", row.stage);
      host.appendChild(button);
    });
  }

  function renderAttention(data) {
    var host = document.querySelector("[data-attention]");
    if (!host) return;
    host.textContent = "";
    var rows = data.attention || [];
    if (!rows.length) {
      host.appendChild(portal.el("p", "muted", "—"));
      return;
    }
    rows.forEach(function (row) {
      var line = portal.el("div", "attention-row");
      var level = /missing/.test(row.reason) ? "attention-0" : /Waiting/.test(row.reason) ? "attention-1" : /Stale/.test(row.reason) ? "attention-2" : "attention-3";
      line.appendChild(portal.el("span", "attention-icon " + level, "!"));
      var link = portal.el("a", "attention-serial mono", row.serial);
      link.href = "/devices/" + encodeURIComponent(row.serial);
      line.appendChild(link);
      line.appendChild(portal.el("span", "attention-reason", row.reason));
      line.appendChild(portal.el("span", "attention-age muted", hoursLabel(row.age_hours)));
      var action = portal.el("a", "btn btn-outline btn-sm attention-open", /Waiting/.test(row.reason) ? "Check now" : "Continue");
      action.href = "/handovers/" + row.id;
      line.appendChild(action);
      host.appendChild(line);
    });
  }

  function renderActivity(data) {
    var host = document.querySelector("[data-activity]");
    if (!host) return;
    host.textContent = "";
    var rows = data.activity || [];
    if (!rows.length) {
      host.appendChild(portal.el("p", "muted", "—"));
      return;
    }
    rows.forEach(function (row) {
      var link = portal.el("a", "activity-row");
      link.href = "/handovers/" + row.case_id;
      var body = portal.el("div", "activity-text");
      body.appendChild(portal.el("div", "", row.text));
      var meta = portal.el("div", "activity-meta");
      meta.appendChild(portal.el("span", "", ago(row.time) + " ago"));
      meta.appendChild(document.createTextNode(" · "));
      meta.appendChild(portal.el("span", "mono", row.serial));
      if (row.engineer) {
        meta.appendChild(document.createTextNode(" · "));
        meta.appendChild(portal.el("span", "", row.engineer));
      }
      body.appendChild(meta);
      link.appendChild(body);
      host.appendChild(link);
    });
  }

  function renderEngineers(data) {
    var body = document.querySelector("[data-engineer-table]");
    if (!body) return;
    body.textContent = "";
    var rows = data.by_engineer || [];
    if (!rows.length) {
      var emptyRow = portal.el("tr", "table-row");
      var cell = portal.el("td", "table-cell", "—");
      cell.colSpan = 3;
      emptyRow.appendChild(cell);
      body.appendChild(emptyRow);
      return;
    }
    var maxOpen = Math.max.apply(null, rows.map(function (row) { return row.open; }));
    rows.forEach(function (row) {
      var tr = portal.el("tr", "table-row");
      tr.appendChild(portal.el("td", "table-cell", row.name));
      var openCell = portal.el("td", "table-cell");
      var openButton = portal.el("button", "cell-button", String(row.open));
      openButton.type = "button";
      openButton.setAttribute("data-filter", "engineer");
      openButton.setAttribute("data-engineer", row.name);
      openCell.appendChild(openButton);
      var bar = portal.el("span", "engineer-bar");
      bar.style.width = (maxOpen ? Math.round((row.open / maxOpen) * 100) : 0) + "%";
      openCell.appendChild(bar);
      tr.appendChild(openCell);
      var doneCell = portal.el("td", "table-cell");
      var doneButton = portal.el("button", "cell-button", String(row.completed_in_period));
      doneButton.type = "button";
      doneButton.setAttribute("data-filter", "engineer");
      doneButton.setAttribute("data-engineer", row.name);
      doneCell.appendChild(doneButton);
      tr.appendChild(doneCell);
      body.appendChild(tr);
    });
  }

  function render(data) {
    last = data;
    renderTiles(data);
    renderCompanies(data);
    renderReady(data);
    renderMissing(data);
    renderAttention(data);
    renderActivity(data);
    renderEngineers(data);
    if (charts.perDay) charts.perDay(document.querySelector('[data-chart="per-day"]'), data.per_day || []);
  }

  function loadDashboard() {
    if (busy) return;
    busy = true;
    var query = "/api/dashboard/handover?period=" + encodeURIComponent(state.period) +
      "&company=" + encodeURIComponent(state.company);
    portal.request(query).then(render).catch(function (error) {
      portal.toast(error.message, "error");
    }).then(function () { busy = false; });
  }

  function setPeriod(period) {
    state.period = period;
    document.querySelectorAll("[data-period]").forEach(function (button) {
      var active = button.getAttribute("data-period") === period;
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
    loadDashboard();
    loadCases();
  }

  function setCompany(company) {
    state.company = company;
    document.querySelectorAll("[data-company]").forEach(function (button) {
      var active = button.getAttribute("data-company") === company;
      button.setAttribute("aria-pressed", active ? "true" : "false");
      button.classList.toggle("chip-active", active);
    });
    loadDashboard();
    loadCases();
  }

  function openNew() {
    portal.openNewCase("handover");
  }

  document.addEventListener("click", function (event) {
    var target = event.target;
    if (!target || !target.closest) return;
    var period = target.closest("[data-period]");
    if (period) { setPeriod(period.getAttribute("data-period")); return; }
    var company = target.closest("[data-company]");
    if (company) { setCompany(company.getAttribute("data-company")); return; }
    if (target.closest("[data-refresh]")) {
      loadDashboard();
      loadCases();
      return;
    }
    if (target.closest("[data-new-handover]")) { openNew(); return; }
    if (target.closest("[data-panel-clear]")) {
      state.filter = "attention";
      state.stage = null;
      state.engineer = null;
      loadCases();
      return;
    }
    var filterButton = target.closest("[data-filter]");
    if (filterButton) {
      state.filter = filterButton.getAttribute("data-filter");
      state.stage = filterButton.getAttribute("data-stage");
      state.engineer = filterButton.getAttribute("data-engineer");
      var filterCompany = filterButton.getAttribute("data-company-filter");
      if (filterCompany) state.company = filterCompany;
      loadCases();
      var panel = document.querySelector("[data-handover-list]");
      if (panel && panel.scrollIntoView) panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
      return;
    }
    var kpi = target.closest("[data-kpi]");
    if (kpi) {
      state.filter = kpi.getAttribute("data-kpi");
      state.stage = null;
      state.engineer = null;
      loadCases();
      return;
    }
  });

  window.setInterval(function () {
    if (document.visibilityState === "visible") loadDashboard();
  }, 30000);

  if (last === null) {
    loadDashboard();
    loadCases();
  }
})();
