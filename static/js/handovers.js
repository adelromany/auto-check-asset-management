/**
 * handovers.js — remembered board/table view, filters and table sorting.
 * Delegated listeners survive the 15-second partial refresh.
 */
"use strict";

(function () {
  var portal = window.portal;

  function tryStorage(action, key, value) {
    try {
      if (action === "get") return window.localStorage.getItem(key);
      if (action === "set") window.localStorage.setItem(key, value);
    } catch (e) { /* storage blocked; defaults are fine */ }
    return null;
  }

  function applyView(useTable) {
    var board = document.getElementById("handover-board");
    var table = document.getElementById("handover-table");
    if (!board || !table) return;
    board.classList.toggle("hidden", useTable);
    table.classList.toggle("hidden", !useTable);
    var toggle = document.getElementById("view-toggle");
    if (toggle) toggle.checked = useTable;
  }

  function rememberedView() {
    return tryStorage("get", "handovers-view") === "table";
  }

  function sortTable(header, direction, remember) {
    var tableEl = document.getElementById("handover-table-el");
    var tbody = tableEl && tableEl.querySelector("tbody");
    if (!tbody) return;
    var key = header.getAttribute("data-sort");
    tableEl.querySelectorAll("th.th-sort").forEach(function (other) {
      other.removeAttribute("data-dir");
    });
    header.setAttribute("data-dir", direction);
    var rows = Array.prototype.slice.call(tbody.querySelectorAll("tr[data-row]"));
    rows.sort(function (a, b) {
      var av = a.getAttribute("data-" + key) || "";
      var bv = b.getAttribute("data-" + key) || "";
      var cmp = av.localeCompare(bv, undefined, { numeric: true });
      return direction === "asc" ? cmp : -cmp;
    });
    rows.forEach(function (row) { tbody.appendChild(row); });
    if (remember) {
      tryStorage("set", "handovers-sort", JSON.stringify({ key: key, direction: direction }));
    }
  }

  function restoreSort() {
    var saved = null;
    try { saved = JSON.parse(tryStorage("get", "handovers-sort") || "null"); } catch (e) { saved = null; }
    if (!saved || !saved.key || ["asc", "desc"].indexOf(saved.direction) < 0) return;
    var header = document.querySelector('#handover-table-el th[data-sort="' + saved.key + '"]');
    if (header) sortTable(header, saved.direction, false);
  }

  function rememberFilter(control) {
    if (!control.name) return;
    tryStorage("set", "handover-filter-" + control.name, control.value);
  }

  function restoreFilters() {
    var params = new URLSearchParams(window.location.search);
    if (["status", "engineer", "range"].some(function (key) { return params.has(key); })) return;
    if (params.has("new")) return;
    var form = document.getElementById("filter-form");
    if (!form) return;
    var shouldSubmit = false;
    ["status", "engineer", "range"].forEach(function (name) {
      var value = tryStorage("get", "handover-filter-" + name);
      if (!value) return;
      var control = form.querySelector('[name="' + name + '"][value="' + CSS.escape(value) + '"]');
      if (!control) control = form.querySelector('[name="' + name + '"]');
      if (!control || !control.value) return;
      if (control.type === "radio") control.checked = true;
      else control.value = value;
      shouldSubmit = true;
    });
    if (shouldSubmit) form.submit();
  }

  document.addEventListener("change", function (event) {
    var control = event.target;
    if (!control || !control.closest) return;
    if (control.closest("#view-toggle")) {
      tryStorage("set", "handovers-view", control.checked ? "table" : "board");
      applyView(control.checked);
      return;
    }
    if (control.closest("#filter-form")) {
      rememberFilter(control);
      var form = document.getElementById("filter-form");
      if (form) form.submit();
    }
  });

  document.addEventListener("click", function (event) {
    var target = event.target;
    if (!target || !target.closest) return;
    var header = target.closest("#handover-table-el th.th-sort");
    if (!header) return;
    var direction = header.getAttribute("data-dir") === "asc" ? "desc" : "asc";
    sortTable(header, direction, true);
  });

  document.addEventListener("portal:refreshed", function () {
    applyView(rememberedView());
    restoreSort();
  });

  applyView(rememberedView());
  restoreSort();
  restoreFilters();
})();
