/* Devices: searchable list and a per-device summary with a milestone timeline. */
"use strict";
(function () {
  var portal = window.portal;
  var serial = document.body.getAttribute("data-device-serial");

  function parse(value) { return value ? new Date(value) : null; }
  function exactDate(value) {
    var when = parse(value);
    return when && !isNaN(when) ? when.toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" }) : "";
  }
  function day(value) {
    var when = parse(value);
    return when && !isNaN(when) ? when.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "—";
  }
  // "3 days ago": the exact date is always available on hover (title).
  function relative(value, now) {
    var when = parse(value);
    if (!when || isNaN(when)) return "—";
    var seconds = Math.round(((now || new Date()) - when) / 1000);
    if (seconds < 0) seconds = 0;
    if (seconds < 60) return "just now";
    var units = [["minute", 60], ["hour", 3600], ["day", 86400], ["month", 2592000], ["year", 31536000]];
    var best = units[0];
    units.forEach(function (unit) { if (seconds >= unit[1]) best = unit; });
    var count = Math.floor(seconds / best[1]);
    return count + " " + best[0] + (count === 1 ? "" : "s") + " ago";
  }
  window.deviceRelativeTime = relative;

  function debounce(fn, wait) {
    var timer = null;
    return function () {
      var args = arguments;
      clearTimeout(timer);
      timer = setTimeout(function () { fn.apply(null, args); }, wait);
    };
  }

  /* ---------------------------------------------------------------- list */
  var PLACES = [
    ["", "All"], ["lab", "In lab"], ["user", "With user"], ["maintenance", "In maintenance"], ["unknown", "Unknown"],
  ];
  var PLACE_BADGE = { lab: "badge-success", user: "badge-outline", maintenance: "badge-warning", unknown: "badge-secondary" };
  var state = { place: "", order: "desc", counts: null, companiesLoaded: false, sequence: 0 };

  function rowsHost() { return document.querySelector("[data-device-rows]"); }

  function messageRow(className, build) {
    var host = rowsHost();
    host.textContent = "";
    var row = portal.el("tr", "dv-message-row");
    var cell = portal.el("td", className);
    cell.colSpan = 6;
    build(cell);
    row.appendChild(cell);
    host.appendChild(row);
  }

  function showSkeleton() {
    var host = rowsHost();
    host.textContent = "";
    host.setAttribute("aria-busy", "true");
    for (var i = 0; i < 6; i += 1) {
      var row = portal.el("tr", "dv-row dv-skeleton-row");
      for (var c = 0; c < 6; c += 1) {
        var cell = portal.el("td", "");
        cell.appendChild(portal.el("span", "skeleton dv-skeleton"));
        row.appendChild(cell);
      }
      host.appendChild(row);
    }
  }

  function renderChips() {
    var host = document.querySelector("[data-place-chips]");
    host.textContent = "";
    PLACES.forEach(function (place) {
      var button = portal.el("button", "chip" + (state.place === place[0] ? " chip-active" : ""), "");
      button.type = "button";
      button.setAttribute("data-place", place[0]);
      button.setAttribute("aria-pressed", state.place === place[0] ? "true" : "false");
      button.appendChild(document.createTextNode(place[1]));
      if (state.counts && place[0]) button.appendChild(portal.el("span", "dv-chip-count", String(state.counts[place[0]] || 0)));
      host.appendChild(button);
    });
  }

  function fillCompanies(companies) {
    var select = document.querySelector("[data-device-company]");
    var current = select.value;
    select.textContent = "";
    var all = portal.el("option", "", "All companies");
    all.value = "";
    select.appendChild(all);
    companies.forEach(function (name) {
      var option = portal.el("option", "", name);
      option.value = name;
      select.appendChild(option);
    });
    select.value = companies.indexOf(current) >= 0 ? current : "";
  }

  function cell(label, className) {
    var td = portal.el("td", className || "");
    td.setAttribute("data-label", label);
    return td;
  }

  function renderRows(items) {
    var host = rowsHost();
    host.textContent = "";
    host.removeAttribute("aria-busy");
    var now = new Date();
    items.forEach(function (item) {
      var row = portal.el("tr", "device-row dv-row");
      var id = cell("Device", "dv-id");
      var link = portal.el("a", "mono dv-serial", item.serial);
      link.href = item.url;
      id.appendChild(link);
      if (item.asset_tag) id.appendChild(portal.el("span", "mono muted dv-tag", item.asset_tag));
      row.appendChild(id);
      row.appendChild(cell("Model", "dv-model")).textContent = item.model || "—";
      var company = cell("Company", "dv-company-cell");
      company.appendChild(portal.el("span", "badge badge-secondary", item.company || "—"));
      row.appendChild(company);
      var place = cell("Place", "dv-place");
      var badge = portal.el("span", "badge " + (PLACE_BADGE[item.place_kind] || "badge-secondary"), item.place);
      badge.setAttribute("data-place-kind", item.place_kind);
      place.appendChild(badge);
      row.appendChild(place);
      row.appendChild(cell("Holder", "dv-holder")).textContent = item.holder || "—";
      var last = cell("Last activity", "muted dv-last");
      last.textContent = relative(item.last_activity, now);
      last.title = exactDate(item.last_activity);
      row.appendChild(last);
      row.addEventListener("click", function (event) { if (!event.target.closest("a")) window.location.href = item.url; });
      host.appendChild(row);
    });
  }

  function clearFilters() {
    document.querySelector("[data-device-search]").value = "";
    document.querySelector("[data-device-company]").value = "";
    state.place = "";
    loadList();
  }

  function renderEmpty(filtered) {
    messageRow("dv-empty", function (td) {
      td.appendChild(portal.el("strong", "", filtered ? "No devices match these filters" : "No devices yet"));
      td.appendChild(portal.el("p", "muted", filtered
        ? "Try a shorter search, another company or place, or clear the filters."
        : "A device appears here after its first handover or maintenance case."));
      if (filtered) {
        var clear = portal.actionButton("Clear filters", "btn-outline btn-sm");
        clear.addEventListener("click", clearFilters);
        td.appendChild(clear);
      }
    });
  }

  function renderError(message) {
    messageRow("dv-error", function (td) {
      td.appendChild(portal.el("strong", "", "Devices could not be loaded"));
      td.appendChild(portal.el("p", "muted", message || "Check the connection and try again."));
      var retry = portal.actionButton("Retry", "btn-outline btn-sm");
      retry.addEventListener("click", loadList);
      td.appendChild(retry);
    });
    document.querySelector("[data-device-total]").textContent = "Not loaded";
  }

  function loadList() {
    var q = document.querySelector("[data-device-search]").value.trim();
    var company = document.querySelector("[data-device-company]").value;
    var ticket = ++state.sequence;
    showSkeleton();
    var url = "/api/devices?q=" + encodeURIComponent(q) + "&company=" + encodeURIComponent(company) +
      "&place=" + encodeURIComponent(state.place) + "&order=" + state.order;
    portal.request(url).then(function (data) {
      if (ticket !== state.sequence) return; // a newer request already replaced this one
      state.counts = data.counts;
      if (!state.companiesLoaded || (data.companies || []).length) { fillCompanies(data.companies || []); state.companiesLoaded = true; }
      renderChips();
      var total = data.total;
      document.querySelector("[data-device-total]").textContent = total + (total === 1 ? " device" : " devices");
      if (!data.items.length) renderEmpty(!!(q || company || state.place));
      else renderRows(data.items);
    }).catch(function (error) {
      if (ticket !== state.sequence) return;
      renderError(error && error.message);
    });
  }

  function setSortArrow() {
    var head = document.querySelector("[data-sort-head]");
    head.setAttribute("aria-sort", state.order === "asc" ? "ascending" : "descending");
    document.querySelector("[data-sort-arrow]").textContent = state.order === "asc" ? "↑" : "↓";
  }

  function initList() {
    renderChips();
    loadList();
    document.querySelector("[data-device-search]").addEventListener("input", debounce(loadList, 250));
    document.querySelector("[data-device-company]").addEventListener("change", loadList);
    document.querySelector("[data-place-chips]").addEventListener("click", function (event) {
      var chip = event.target.closest("[data-place]");
      if (!chip) return;
      state.place = chip.getAttribute("data-place");
      renderChips();
      loadList();
    });
    document.querySelector("[data-sort-last]").addEventListener("click", function () {
      state.order = state.order === "desc" ? "asc" : "desc";
      setSortArrow();
      loadList();
    });
  }

  /* -------------------------------------------------------------- detail */
  function summaryTile(key, label, value) {
    var box = portal.el("div", "summary-fact");
    box.setAttribute("data-fact", key);
    box.appendChild(portal.el("small", "muted", label));
    box.appendChild(portal.el("strong", "", String(value)));
    return box;
  }

  function renderMeta(device) {
    var meta = document.querySelector("[data-device-meta]");
    meta.textContent = "";
    if (!device) return;
    if (device.model) meta.appendChild(portal.el("span", "badge badge-outline", device.model));
    meta.appendChild(portal.el("span", "badge badge-secondary", device.company || "No company"));
  }

  function renderSummary(summary) {
    var host = document.querySelector("[data-device-summary]");
    host.textContent = "";
    var maintenance = summary.maintenance_count + (summary.maintenance_count === 1 ? " case" : " cases") +
      (summary.maintenance_days ? " · " + summary.maintenance_days + " days" : "");
    host.appendChild(summaryTile("now", "Now", summary.now));
    host.appendChild(summaryTile("handovers", "Handovers", summary.handovers));
    host.appendChild(summaryTile("maintenance", "Maintenance", maintenance));
    var last = summaryTile("last", "Last activity", relative(summary.last_activity));
    last.querySelector("strong").title = exactDate(summary.last_activity);
    host.appendChild(last);
  }

  function renderHistoryState(title, hint, retry) {
    var host = document.querySelector("[data-device-history]");
    host.textContent = "";
    host.classList.add("dv-history-empty");
    var box = portal.el("div", "dv-empty");
    box.appendChild(portal.el("strong", "", title));
    box.appendChild(portal.el("p", "muted", hint));
    if (retry) {
      var button = portal.actionButton("Retry", "btn-outline btn-sm");
      button.addEventListener("click", loadDetail);
      box.appendChild(button);
    }
    host.appendChild(box);
  }

  function renderTimeline(cards) {
    var host = document.querySelector("[data-device-history]");
    host.textContent = "";
    host.classList.remove("dv-history-empty");
    var currentDate = null, group = null;
    cards.forEach(function (card) {
      var label = day(card.date);
      if (label !== currentDate) {
        currentDate = label;
        group = portal.el("section", "history-date-group");
        var heading = portal.el("h3", "history-date", label);
        heading.appendChild(portal.el("span", "history-dot"));
        group.appendChild(heading);
        host.appendChild(group);
      }
      var outer = portal.el("article", "card milestone-card");
      var inner = portal.el("a", "milestone-inner");
      inner.href = card.case_url;
      var main = portal.el("div", "milestone-main");
      main.appendChild(portal.el("span", "badge " + (card.tag === "Handover" ? "badge-accent" : "badge-warning"), card.tag));
      main.appendChild(portal.el("h4", "milestone-title", card.headline));
      inner.appendChild(main);
      var facts = portal.el("div", "milestone-facts");
      card.facts.forEach(function (fact) {
        var box = portal.el("div", "history-fact");
        box.appendChild(portal.el("small", "muted", fact.label));
        var kind = fact.kind === "chip-ok" ? "badge-success" : fact.kind === "chip-warn" ? "badge-warning" : "badge-secondary";
        box.appendChild(portal.el("strong", fact.kind === "plain" ? "" : "badge " + kind, fact.value));
        facts.appendChild(box);
      });
      inner.appendChild(facts);
      outer.appendChild(inner);
      group.appendChild(outer);
    });
  }

  function loadLive() {
    var live = document.querySelector("[data-live-holder]");
    live.textContent = "";
    live.appendChild(portal.el("span", "skeleton dv-skeleton dv-skeleton-chip"));
    portal.request("/api/snipeit/device-lookup?serial=" + encodeURIComponent(serial)).then(function (device) {
      live.textContent = "";
      var ready = device.status === "Ready to deploy";
      var status = portal.el("span", "badge " + (ready ? "badge-success" : "badge-outline"), device.status || "No status");
      status.setAttribute("data-live-status", "");
      live.appendChild(status);
      live.appendChild(portal.el("span", "dv-holder-text", device.assigned_to ? "With " + device.assigned_to.name : "Not assigned"));
      var now = document.querySelector('[data-fact="now"] strong');
      if (now && device.assigned_to) now.textContent = "With " + device.assigned_to.name;
    }).catch(function () {
      live.textContent = "";
      var badge = portal.el("span", "badge badge-secondary", "Snipe-IT unavailable");
      badge.setAttribute("data-live-unavailable", "");
      badge.title = "The live status and holder could not be read. The history below is still accurate.";
      live.appendChild(badge);
    });
  }

  function loadDetail() {
    var history = document.querySelector("[data-device-history]");
    history.textContent = "";
    history.classList.remove("dv-history-empty");
    for (var i = 0; i < 3; i += 1) history.appendChild(portal.el("div", "skeleton dv-skeleton dv-skeleton-card"));
    portal.request("/api/devices/" + encodeURIComponent(serial) + "/history").then(function (data) {
      renderMeta(data.device);
      renderSummary(data.summary);
      if (!data.cards.length) {
        renderHistoryState("No history yet", "Start a handover or register a maintenance case to build this device's history.", false);
      } else {
        renderTimeline(data.cards);
      }
    }).catch(function (error) {
      renderHistoryState("History could not be loaded", (error && error.message) || "Check the connection and try again.", true);
    });
    loadLive();
  }

  if (serial) {
    loadDetail();
    document.querySelector("[data-new-handover]").addEventListener("click", function () { portal.openNewCase("handover", { serial: serial }); });
    document.querySelector("[data-new-maintenance]").addEventListener("click", function () { portal.openNewCase("maintenance", { serial: serial }); });
  } else {
    initList();
  }
})();
