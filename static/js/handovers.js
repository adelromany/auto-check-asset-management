/**
 * handovers.js — board/table switch (remembered), sortable table,
 * filter chips submitted as navigation.
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

  // view switch
  var toggle = document.getElementById("view-toggle");
  var board = document.getElementById("handover-board");
  var table = document.getElementById("handover-table");
  function applyView(useTable) {
    if (!board || !table) return;
    if (useTable) {
      board.classList.add("hidden");
      table.classList.remove("hidden");
    } else {
      board.classList.remove("hidden");
      table.classList.add("hidden");
    }
  }
  if (toggle) {
    var stored = tryStorage("get", "handovers-view");
    var useTable = stored === "table";
    toggle.checked = useTable;
    applyView(useTable);
    toggle.addEventListener("change", function () {
      tryStorage("set", "handovers-view", toggle.checked ? "table" : "board");
      applyView(toggle.checked);
    });
  }

  // sortable table
  var tableEl = document.getElementById("handover-table-el");
  if (tableEl) {
    var headers = tableEl.querySelectorAll("th.th-sort");
    headers.forEach(function (th) {
      th.addEventListener("click", function () {
        var key = th.getAttribute("data-sort");
        var tbody = tableEl.querySelector("tbody");
        var rows = Array.prototype.slice.call(tbody.querySelectorAll("tr[data-row]"));
        var asc = th.getAttribute("data-dir") !== "asc";
        headers.forEach(function (other) { other.removeAttribute("data-dir"); });
        th.setAttribute("data-dir", asc ? "asc" : "desc");
        rows.sort(function (a, b) {
          var av = a.getAttribute("data-" + key) || "";
          var bv = b.getAttribute("data-" + key) || "";
          var cmp = av.localeCompare(bv, undefined, { numeric: true });
          return asc ? cmp : -cmp;
        });
        rows.forEach(function (row) { tbody.appendChild(row); });
      });
    });
  }

  // filter chips submit on change
  var form = document.getElementById("filter-form");
  if (form) {
    form.querySelectorAll("input, select").forEach(function (control) {
      control.addEventListener("change", function () { form.submit(); });
    });
  }
})();
