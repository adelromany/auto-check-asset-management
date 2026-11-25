/* Handover dashboard: outcome tiles, company filters and server-backed rows. */
"use strict";
(function () {
  var portal = window.portal;
  var selected = { outcome: "ready", company: "" };

  function badge(text, cls) {
    var node = portal.el("span", cls || "badge badge-outline", text);
    return node;
  }

  function age(created) {
    if (!created) return "—";
    var days = Math.max(0, Math.floor((Date.now() - new Date(created).getTime()) / 86400000));
    return days + "d";
  }

  function caseRow(item) {
    var row = portal.el("div", "handover-row");
    var serial = portal.el("a", "mono handover-serial", item.device_serial);
    serial.href = "/handovers/" + item.id;
    row.appendChild(serial);
    row.appendChild(portal.el("span", "handover-model", item.device_model || "—"));
    row.appendChild(badge(item.device_company || "—", "badge badge-secondary"));
    row.appendChild(portal.el("span", "handover-recipient", item.recipient_snipeit_name || item.recipient_free_name || "No recipient"));
    var missing = portal.el("span", "handover-missing");
    (item.missing || []).slice(0, 3).forEach(function (part) {
      missing.appendChild(badge(part.replace(/_/g, " "), "badge badge-outline"));
    });
    if ((item.missing || []).length > 3) missing.appendChild(badge("+" + (item.missing.length - 3), "badge badge-secondary"));
    row.appendChild(missing);
    row.appendChild(portal.el("span", "muted mono", age(item.created_at)));
    var action = portal.el("a", "btn btn-outline btn-sm", item.outcome === "complete" ? "Open" : "Continue");
    action.href = "/handovers/" + item.id;
    action.setAttribute("data-case-open", item.id);
    row.appendChild(action);
    return row;
  }

  function renderRows(items) {
    var list = document.querySelector("[data-handover-list]");
    if (!list) return;
    list.textContent = "";
    if (!items.length) {
      list.appendChild(portal.el("div", "empty", "—"));
      return;
    }
    items.forEach(function (item) { list.appendChild(caseRow(item)); });
  }

  function loadRows() {
    var query = "/api/handovers?kind=handover&outcome=" + encodeURIComponent(selected.outcome);
    if (selected.company) query += "&company=" + encodeURIComponent(selected.company);
    portal.request(query).then(function (result) {
      renderRows((result.items || []).filter(function (item) {
        return item.kind === "handover";
      }));
    }).catch(function (error) { portal.toast(error.message, "error"); });
  }

  function loadSummary() {
    portal.request("/api/dashboard/handover").then(function (data) {
      var ready = document.querySelector("[data-ready-count]");
      var complete = document.querySelector("[data-complete-count]");
      var incomplete = document.querySelector("[data-not-complete-count]");
      if (ready) ready.textContent = String((data.ready || {}).total || 0);
      if (complete) complete.textContent = String(((data.complete || {}).total) || 0);
      if (incomplete) incomplete.textContent = String(((data.not_complete || {}).total) || 0);
      var chips = document.querySelector("[data-ready-companies]");
      if (chips) {
        chips.textContent = "";
        ((data.ready || {}).by_company || []).forEach(function (group) {
          var chip = portal.el("button", "badge badge-secondary", group.company + " " + group.count);
          chip.type = "button";
          chip.setAttribute("data-company", group.company);
          chip.addEventListener("click", function () {
            selected.company = group.company;
            loadRows();
          });
          chips.appendChild(chip);
        });
      }
    }).catch(function (error) { portal.toast(error.message, "error"); });
  }

  function openNew() {
    var drawer = portal.drawerForm("New handover", {});
    var form = drawer.__form;
    var input = portal.textInput("device_serial", "Serial", { maxlength: 100 });
    var error = portal.el("p", "field-error");
    error.setAttribute("data-new-error", "");
    error.hidden = true;
    var actions = portal.formActions("Start");
    form.appendChild(portal.field("Serial", input));
    form.appendChild(error);
    form.appendChild(actions);
    function submit() {
      var serial = input.value.trim();
      if (!serial) { error.textContent = "Enter a serial."; error.hidden = false; return; }
      portal.setBusy(actions, true);
      portal.apiJson("/api/handovers", { method: "POST", body: JSON.stringify({ device_serial: serial }) })
        .then(function (created) { window.location.href = "/handovers/" + created.id; })
        .catch(function (err) {
          portal.setBusy(actions, false);
          error.textContent = err.message;
          error.hidden = false;
          var open = portal.el("a", "link-quiet", "Open");
          open.href = "/handovers/" + (err.active_handover_id || "");
          open.hidden = !err.active_handover_id;
          error.appendChild(open);
        });
    }
    form.addEventListener("submit", function (event) { event.preventDefault(); submit(); });
    actions.__primary.addEventListener("click", function (event) { event.preventDefault(); submit(); });
  }

  document.addEventListener("click", function (event) {
    var target = event.target;
    if (!target || !target.closest) return;
    var tile = target.closest("[data-outcome]");
    if (tile) {
      selected.outcome = tile.getAttribute("data-outcome");
      selected.company = "";
      loadRows();
      return;
    }
    if (target.closest("[data-new-handover]")) openNew();
  });

  loadSummary();
  loadRows();
})();
