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

  // -- tabs and panels ---------------------------------------------------------
  // All controls are reached through delegated listeners so the 15 s
  // auto-refresh can replace the board without leaving dead buttons behind.
  var currentTab = tryStorage("get", "maintenance-tab") || "board";
  var collapsed = tryStorage("get", "vendor-panel") === "collapsed";

  function tabNodes() {
    return portal.$all("[data-maint-tab]");
  }

  function showTab(name) {
    currentTab = name;
    tabNodes().forEach(function (tab) {
      tab.setAttribute("aria-selected", tab.getAttribute("data-maint-tab") === name ? "true" : "false");
    });
    var board = document.getElementById("maint-board");
    var atVendors = document.getElementById("maint-atvendors");
    if (board) board.classList.toggle("hidden", name !== "board");
    if (atVendors) atVendors.classList.toggle("hidden", name !== "atvendors");
    tryStorage("set", "maintenance-tab", name);
  }

  function applyPanel() {
    var panelToggle = portal.$("[data-panel-toggle]");
    var panelBody = document.getElementById("vendor-panel-body");
    if (!panelToggle || !panelBody) return;
    panelBody.classList.toggle("hidden", collapsed);
    panelToggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
    var arrow = panelToggle.querySelector("span.muted");
    if (arrow) arrow.textContent = collapsed ? "▸" : "▾";
  }

  document.addEventListener("click", function (event) {
    var target = event.target;
    if (!target || !target.closest) return;
    var tab = target.closest("[data-maint-tab]");
    if (tab) {
      showTab(tab.getAttribute("data-maint-tab"));
      return;
    }
    var toggle = target.closest("[data-panel-toggle]");
    if (toggle) {
      collapsed = !collapsed;
      tryStorage("set", "vendor-panel", collapsed ? "collapsed" : "open");
      applyPanel();
      return;
    }
    var step = target.closest("[data-step]");
    if (step) {
      var caseId = step.getAttribute("data-case");
      if (step.getAttribute("data-step") === "send") openSendDrawer(caseId);
      else openReceiveDrawer(caseId);
    }
  });

  document.addEventListener("change", function (event) {
    var control = event.target;
    if (control && control.closest && control.closest("#maint-filter-form")) {
      if (control.name) tryStorage("set", "maintenance-filter-" + control.name, control.value);
      var form = document.getElementById("maint-filter-form");
      if (form) form.submit();
    }
  });

  function restoreFilters() {
    var params = new URLSearchParams(window.location.search);
    if (params.has("state") || params.has("vendor") || params.has("new")) return;
    var form = document.getElementById("maint-filter-form");
    if (!form) return;
    var shouldSubmit = false;
    ["state", "vendor"].forEach(function (name) {
      var value = tryStorage("get", "maintenance-filter-" + name);
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

  // The refreshed markup carries the server defaults: restore what the user
  // had chosen, without touching an open drawer or a half-filled form.
  document.addEventListener("portal:refreshed", function () {
    showTab(currentTab);
    applyPanel();
  });

  if (tabNodes().length) showTab(currentTab);
  applyPanel();
  restoreFilters();

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

  function appendNotDone(form, caseId, operation) {
    var section = portal.el("section", "stack-sm notdone-section");
    section.appendChild(portal.el("h3", "drawer-sub", "Or mark not done"));
    var reason = portal.textInput("not_done_reason", "Reason (3–300 characters)", { maxlength: 300 });
    section.appendChild(reason);
    var button = portal.actionButton("Not done", "btn-outline");
    button.addEventListener("click", function () {
      if (reason.value.trim().length < 3) {
        portal.toast("Give a reason of at least 3 characters.", "error");
        reason.focus();
        return;
      }
      button.disabled = true;
      markNotDone(caseId, operation, reason.value.trim()).then(function () {
        portal.toast("Marked as not done.", "success");
        window.location.reload();
      }).catch(function (error) {
        button.disabled = false;
        portal.toast(error.message, "error");
      });
    });
    section.appendChild(button);
    form.appendChild(section);
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

    appendNotDone(form, caseId, "sent_out");
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

    appendNotDone(form, caseId, "returned");
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

})();
