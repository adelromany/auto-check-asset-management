/**
 * maintenance.js — tabs, vendor panel collapse, filter chips, and the two
 * transit step drawers ("Send to vendor", "Receive back"). Each step
 * records the typed maintenance fields and confirms the operation; the
 * Snipe-IT status label is updated through the env-configured names, and a
 * missing label is recorded as not done with that reason (non-blocking).
 */
"use strict";

(function () {
  var portal = window.portal;

  function tryStorage(action, key, value) {
    try {
      if (action === "get") return window.localStorage.getItem(key);
      if (action === "set") window.localStorage.setItem(key, value);
    } catch (e) { return null; }
    return null;
  }

  // -- tabs -------------------------------------------------------------------
  var tabs = portal.$all("[data-maint-tab]");
  var board = document.getElementById("maint-board");
  var atVendors = document.getElementById("maint-atvendors");
  function showTab(name) {
    tabs.forEach(function (tab) {
      tab.setAttribute("aria-selected", tab.getAttribute("data-maint-tab") === name ? "true" : "false");
    });
    if (board) board.classList.toggle("hidden", name !== "board");
    if (atVendors) atVendors.classList.toggle("hidden", name !== "atvendors");
    tryStorage("set", "maintenance-tab", name);
  }
  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () { showTab(tab.getAttribute("data-maint-tab")); });
  });
  if (tabs.length) showTab(tryStorage("get", "maintenance-tab") || "board");

  // -- vendor panel collapse (remembered) --------------------------------------
  var panelToggle = portal.$("[data-panel-toggle]");
  var panelBody = document.getElementById("vendor-panel-body");
  if (panelToggle && panelBody) {
    var collapsed = tryStorage("get", "vendor-panel") === "collapsed";
    function applyPanel() {
      panelBody.classList.toggle("hidden", collapsed);
      panelToggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
      panelToggle.querySelector("span.muted").textContent = collapsed ? "▸" : "▾";
    }
    applyPanel();
    panelToggle.addEventListener("click", function () {
      collapsed = !collapsed;
      tryStorage("set", "vendor-panel", collapsed ? "collapsed" : "open");
      applyPanel();
    });
  }

  // -- filter chips --------------------------------------------------------------
  var filterForm = document.getElementById("maint-filter-form");
  if (filterForm) {
    filterForm.querySelectorAll("input").forEach(function (control) {
      control.addEventListener("change", function () { filterForm.submit(); });
    });
  }

  // -- transit step drawers -------------------------------------------------------
  function maintenanceFields(caseId, payload) {
    return portal.apiJson("/api/handovers/" + caseId + "/maintenance", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  function confirmOperation(caseId, operation) {
    return portal.apiJson(
      "/api/handovers/" + caseId + "/operations/" + operation + "/confirm",
      { method: "POST" }
    );
  }

  function markNotDone(caseId, operation, reason) {
    return portal.apiJson(
      "/api/handovers/" + caseId + "/operations/" + operation + "/not-done",
      { method: "POST", body: JSON.stringify({ reason: reason }) }
    );
  }

  function updateSnipeStatusLabel(caseId) {
    // New endpoint keeps this additive; a 503/422 simply means "not updated".
    return portal.apiJson("/api/handovers/" + caseId + "/maintenance/status-label", {
      method: "POST",
    }).then(function (res) {
      return res.updated === true;
    }).catch(function () { return false; });
  }

  function settleSnipeIt(caseId) {
    return updateSnipeStatusLabel(caseId).then(function (updated) {
      if (!updated) {
        portal.toast("Snipe-IT status not updated", "info");
        return markNotDone(
          caseId,
          "snipeit_status",
          "Snipe-IT status not updated (label not configured or Snipe-IT unavailable)"
        ).catch(function () { /* the transit step itself succeeded */ });
      }
      return confirmOperation(caseId, "snipeit_status").catch(function () { /* already done */ });
    });
  }

  function openSendDrawer(caseId) {
    var drawer = portal.drawerForm("Send to vendor", {});
    var form = drawer.__form;
    form.setAttribute("data-step-form", "send");

    var vendorSelect = portal.selectInput("vendor", []);
    var reference = portal.textInput("reference", "Reference number", { maxlength: 100 });
    var expected = portal.textInput("expected_return_date", "", { type: "date" });
    var accessories = portal.textInput("accessories", "Accessories sent (optional)", { maxlength: 200 });
    var condition = portal.textInput("condition_notes", "Condition at send (optional)", { maxlength: 200 });

    form.appendChild(portal.field("Vendor", vendorSelect));
    form.appendChild(portal.field("Reference", reference));
    form.appendChild(portal.field("Expected return", expected, "When the vendor promised the device back"));
    form.appendChild(portal.field("Accessories", accessories));
    form.appendChild(portal.field("Condition", condition));

    var actions = portal.formActions("Send");
    form.appendChild(actions);
    portal.request("/api/handovers/maintenance/vendors").then(function (vendors) {
      var names = (vendors || []).filter(function (v) { return v.active; }).map(function (v) { return v.name; });
      while (vendorSelect.firstChild) vendorSelect.removeChild(vendorSelect.firstChild);
      portal.selectInput("vendor", names).querySelectorAll("option").forEach(function (option) {
        vendorSelect.appendChild(option);
      });
    }).catch(function () {
      while (vendorSelect.firstChild) vendorSelect.removeChild(vendorSelect.firstChild);
      var empty = portal.el("option", "", "No vendor list available");
      empty.value = "";
      vendorSelect.appendChild(empty);
    });

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      portal.setBusy(actions, true);
      var payload = {};
      ["vendor", "reference", "expected_return_date", "accessories", "condition_notes"].forEach(function (key) {
        var control = form.querySelector('[name="' + key + '"]');
        if (control && control.value.trim()) payload[key] = control.value.trim();
      });
      maintenanceFields(caseId, payload)
        .then(function () { return confirmOperation(caseId, "sent_out"); })
        .then(function () { return settleSnipeIt(caseId); })
        .then(function () {
          portal.toast("Sent to vendor.", "success");
          window.location.reload();
        })
        .catch(function (error) {
          portal.setBusy(actions, false);
          portal.toast(error.message, "error");
        });
    });
  }

  function openReceiveDrawer(caseId) {
    var drawer = portal.drawerForm("Receive back", {});
    var form = drawer.__form;
    form.setAttribute("data-step-form", "receive");

    var outcome = portal.selectInput("outcome", [
      { value: "repaired", label: "Repaired" },
      { value: "replaced", label: "Replaced" },
      { value: "unrepairable", label: "Unrepairable" },
    ]);
    var condition = portal.textInput("condition_notes", "Condition at return (optional)", { maxlength: 200 });
    var note = portal.textInput("outcome_note", "Note (optional)", { maxlength: 300 });
    var cost = portal.textInput("cost", "Cost (optional)", { maxlength: 100 });
    var warranty = portal.selectInput("warranty", [
      { value: "", label: "Warranty: unknown" },
      { value: "yes", label: "Under warranty" },
      { value: "no", label: "Not under warranty" },
    ]);

    form.appendChild(portal.field("Outcome", outcome));
    form.appendChild(portal.field("Condition", condition));
    form.appendChild(portal.field("Cost", cost));
    form.appendChild(portal.field("Warranty", warranty));
    form.appendChild(portal.field("Note", note));

    var actions = portal.formActions("Receive");
    form.appendChild(actions);

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      portal.setBusy(actions, true);
      var payload = {};
      ["outcome", "condition_notes", "outcome_note", "cost", "warranty"].forEach(function (key) {
        var control = form.querySelector('[name="' + key + '"]');
        if (control && control.value.trim()) payload[key] = control.value.trim();
      });
      maintenanceFields(caseId, payload)
        .then(function () { return confirmOperation(caseId, "returned"); })
        .then(function () { return settleSnipeIt(caseId); })
        .then(function () {
          portal.toast("Device received back.", "success");
          window.location.reload();
        })
        .catch(function (error) {
          portal.setBusy(actions, false);
          portal.toast(error.message, "error");
        });
    });
  }

  portal.$all("[data-step]").forEach(function (button) {
    button.addEventListener("click", function () {
      var caseId = button.getAttribute("data-case");
      if (button.getAttribute("data-step") === "send") openSendDrawer(caseId);
      else openReceiveDrawer(caseId);
    });
  });
})();
