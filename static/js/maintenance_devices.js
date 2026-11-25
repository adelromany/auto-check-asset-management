/* Maintenance devices: add, filter, and batch send/receive. */
"use strict";
(function () {
  var portal = window.portal;
  if (!portal) return;

  var state = { items: [], tab: "with_it", selected: { with_it: {}, at_vendor: {} }, reasons: [], vendors: [], lookup: null };
  var addForm = portal.$("[data-maint-add-form]");
  var filterForm = portal.$("[data-device-filters]");

  function node(tag, cls, text) { return portal.el(tag, cls, text); }
  function all(selector, root) { return portal.$all(selector, root); }
  function selectedIds(tab) { return Object.keys(state.selected[tab] || {}); }

  function clearLookup() {
    state.lookup = null;
    var box = portal.$("[data-device-lookup]");
    box.textContent = "";
    box.removeAttribute("data-state");
  }

  function renderLookup(device) {
    var box = portal.$("[data-device-lookup]");
    box.textContent = "";
    box.setAttribute("data-state", "ok");
    var card = node("div", "maint-lookup-card");
    var head = node("div", "maint-lookup-head");
    head.appendChild(node("strong", "", device.model || "Unknown model"));
    if (device.company) head.appendChild(node("span", "badge badge-accent", device.company));
    card.appendChild(head);
    var status = node("span", "badge badge-outline", device.status || "No status");
    status.setAttribute("data-device-status", "");
    card.appendChild(status);
    card.appendChild(node("span", "maint-lookup-user", device.assigned_to || "No user"));
    box.appendChild(card);
  }

  function lookupSerial() {
    var serial = addForm.elements.serial.value.trim();
    clearLookup();
    if (serial.length < 3) return;
    portal.request("/api/maintenance/device-lookup?serial=" + encodeURIComponent(serial))
      .then(function (device) { state.lookup = device; renderLookup(device); })
      .catch(function () {
        var box = portal.$("[data-device-lookup]");
        box.textContent = "Not found";
        box.setAttribute("data-state", "miss");
      });
  }

  var lookupTimer = null;
  addForm.elements.serial.addEventListener("input", function () {
    window.clearTimeout(lookupTimer);
    clearLookup();
    lookupTimer = window.setTimeout(lookupSerial, 400);
  });
  addForm.elements.serial.addEventListener("keydown", function (event) {
    if (event.key === "Enter") {
      event.preventDefault();
      addForm.elements.reason_id.focus();
    }
  });

  function populateReasons() {
    return portal.request("/api/maintenance/reasons").then(function (items) {
      state.reasons = items || [];
      var select = addForm.elements.reason_id;
      select.textContent = "";
      var blank = node("option", "", "Select reason");
      blank.value = "";
      select.appendChild(blank);
      state.reasons.forEach(function (item) {
        var option = node("option", "", item.name);
        option.value = item.id;
        select.appendChild(option);
      });
    });
  }

  function populateVendors() {
    return portal.request("/api/maintenance/vendors").then(function (items) {
      state.vendors = items || [];
      var select = addForm.elements.planned_vendor_id;
      select.textContent = "";
      var blank = node("option", "", "Not assigned");
      blank.value = "";
      select.appendChild(blank);
      state.vendors.forEach(function (item) {
        var option = node("option", "", item.name);
        option.value = item.id;
        select.appendChild(option);
      });
    });
  }

  function reasonIsOther() {
    var selected = state.reasons.find(function (item) { return String(item.id) === String(addForm.elements.reason_id.value); });
    return selected && selected.name.toLowerCase() === "other";
  }

  addForm.elements.reason_id.addEventListener("change", function () {
    var details = portal.$("[data-details-field]");
    details.classList.toggle("hidden", !reasonIsOther());
    addForm.elements.reason_text.required = reasonIsOther();
  });

  addForm.addEventListener("submit", function (event) {
    event.preventDefault();
    var serial = addForm.elements.serial.value.trim();
    var reasonId = addForm.elements.reason_id.value;
    var details = addForm.elements.reason_text.value.trim();
    if (!serial) return;
    if (!reasonId) { portal.toast("Select a reason.", "error"); return; }
    if (reasonIsOther() && !details) { portal.toast("Details are required for Other.", "error"); addForm.elements.reason_text.focus(); return; }
    var payload = { serial: serial, reason_id: Number(reasonId) };
    if (details) payload.reason_text = details;
    if (addForm.elements.planned_vendor_id.value) payload.planned_vendor_id = Number(addForm.elements.planned_vendor_id.value);
    var button = addForm.querySelector("[data-primary]");
    portal.setBusy({ __primary: button }, true);
    portal.apiJson("/api/maintenance/cases", { method: "POST", body: JSON.stringify(payload) })
      .then(function () {
        addForm.reset();
        portal.$("[data-details-field]").classList.add("hidden");
        clearLookup();
        addForm.elements.serial.focus();
        portal.toast("Device added.", "success");
        return loadCases();
      })
      .catch(function (error) { portal.toast(error.message, "error"); })
      .then(function () { portal.setBusy({ __primary: button }, false); });
  });

  function stageStatus(item, stage) {
    var found = (item.stages || []).find(function (s) { return s.stage === stage; });
    return found ? found.status : "pending";
  }

  function actionButton(label, action, item) {
    var button = node("button", "btn btn-outline btn-sm", label);
    button.type = "button";
    button.setAttribute("data-row-action", action);
    button.setAttribute("data-case-id", item.case_id);
    return button;
  }

  function resultChip() {
    var chip = node("span", "badge badge-outline hidden", "");
    chip.setAttribute("data-row-result", "");
    return chip;
  }

  function renderWithIt(item) {
    var row = node("tr", "table-row");
    row.setAttribute("data-case-id", item.case_id);
    row.setAttribute("data-serial", item.serial);
    var checkCell = node("td", "table-cell");
    var check = node("input", "");
    check.type = "checkbox";
    check.setAttribute("data-select-case", item.case_id);
    check.setAttribute("aria-label", "Select " + item.serial);
    checkCell.appendChild(check); row.appendChild(checkCell);
    var serial = node("td", "table-cell");
    var link = node("a", "row-link mono", item.serial); link.href = "/maintenance/" + item.case_id;
    serial.appendChild(link);
    serial.appendChild(node("span", "badge badge-outline ml-2", item.snipeit_status || "No status"));
    row.appendChild(serial);
    row.appendChild(node("td", "table-cell", item.model || "—"));
    var company = node("td", "table-cell"); company.appendChild(node("span", "badge badge-accent", item.company || "Unknown")); row.appendChild(company);
    row.appendChild(node("td", "table-cell", item.reason || "—"));
    row.appendChild(node("td", "table-cell", String(item.days || 0) + "d"));
    row.appendChild(node("td", "table-cell", item.planned_vendor || item.vendor || "Not assigned"));
    var actions = node("td", "table-cell maint-row-actions");
    actions.appendChild(actionButton("Set Maintenance", "set-status", item));
    if (item.assigned_to) actions.appendChild(actionButton("Remove from user", "take-back", item));
    actions.appendChild(resultChip());
    row.appendChild(actions);
    return row;
  }

  function renderAtVendor(item) {
    var row = node("tr", "table-row");
    row.setAttribute("data-case-id", item.case_id);
    row.setAttribute("data-serial", item.serial);
    var checkCell = node("td", "table-cell");
    var check = node("input", "");
    check.type = "checkbox"; check.setAttribute("data-select-case", item.case_id); check.setAttribute("aria-label", "Select " + item.serial);
    checkCell.appendChild(check); row.appendChild(checkCell);
    var serial = node("td", "table-cell"); var link = node("a", "row-link mono", item.serial); link.href = "/maintenance/" + item.case_id; serial.appendChild(link); row.appendChild(serial);
    row.appendChild(node("td", "table-cell", item.model || "—"));
    row.appendChild(node("td", "table-cell", item.company || "Unknown"));
    row.appendChild(node("td", "table-cell", item.vendor || "Not assigned"));
    row.appendChild(node("td", "table-cell mono", item.sent_date || "—"));
    row.appendChild(node("td", "table-cell", String(item.days || 0) + "d"));
    row.appendChild(node("td", "table-cell", item.reason || "—"));
    return row;
  }

  function filteredItems(tab) {
    var form = filterForm;
    var q = (form.elements.q.value || "").trim().toLowerCase();
    var company = form.elements.company.value;
    var model = form.elements.model.value;
    var vendor = form.elements.vendor.value;
    return state.items.filter(function (item) {
      if (item.state !== tab) return false;
      if (q && item.serial.toLowerCase().indexOf(q) < 0) return false;
      if (company && item.company !== company) return false;
      if (model && item.model !== model) return false;
      if (vendor && (item.vendor || "Not assigned") !== vendor) return false;
      return true;
    });
  }

  function updateFilterOptions() {
    var fields = ["company", "model", "vendor"];
    fields.forEach(function (name) {
      var select = filterForm.elements[name];
      var current = select.value;
      var values = {};
      state.items.forEach(function (item) {
        var value = name === "vendor" ? (item.vendor || "Not assigned") : item[name];
        if (value) values[value] = true;
      });
      select.textContent = "";
      var all = node("option", "", (name === "company" ? "Company: all" : name === "model" ? "Model: all" : "Vendor: all")); all.value = ""; select.appendChild(all);
      Object.keys(values).sort().forEach(function (value) { var option = node("option", "", value); option.value = value; select.appendChild(option); });
      select.value = current;
    });
  }

  function renderTables() {
    ["with_it", "at_vendor"].forEach(function (tab) {
      var body = portal.$("[data-device-rows='" + tab + "']");
      body.textContent = "";
      var items = filteredItems(tab);
      if (!items.length) {
        var emptyRow = node("tr"); var empty = node("td", "table-cell", "No devices."); empty.colSpan = 8; emptyRow.appendChild(empty); body.appendChild(emptyRow);
      }
      items.forEach(function (item) { body.appendChild(tab === "with_it" ? renderWithIt(item) : renderAtVendor(item)); });
    });
    restoreChecks();
    updateSelection();
  }

  function restoreChecks() {
    all("[data-select-case]").forEach(function (check) {
      check.checked = !!state.selected[state.tab][check.getAttribute("data-select-case")];
    });
  }

  function updateSelection() {
    var ids = selectedIds(state.tab);
    var count = ids.length;
    var bar = portal.$("[data-selection-bar]");
    bar.classList.toggle("hidden", count === 0);
    portal.$("[data-selection-count]").textContent = count + " selected";
    portal.$("[data-batch-send]").textContent = "Send batch (" + count + ")";
    portal.$("[data-batch-receive]").textContent = "Receive batch (" + count + ")";
    portal.$("[data-batch-send]").classList.toggle("hidden", state.tab !== "with_it");
    portal.$("[data-batch-receive]").classList.toggle("hidden", state.tab !== "at_vendor");
  }

  function loadCases() {
    return portal.request("/api/maintenance/cases").then(function (items) {
      state.items = items || [];
      updateFilterOptions();
      renderTables();
    }).catch(function (error) { portal.toast(error.message, "error"); });
  }

  document.addEventListener("change", function (event) {
    var check = event.target.closest ? event.target.closest("[data-select-case]") : null;
    if (check) {
      var id = check.getAttribute("data-select-case");
      if (check.checked) state.selected[state.tab][id] = true; else delete state.selected[state.tab][id];
      updateSelection(); return;
    }
    var allCheck = event.target.closest ? event.target.closest("[data-select-all]") : null;
    if (allCheck) {
      allCheck.checked = false;
      all("[data-select-case]").forEach(function (item) {
        if (item.checked !== allCheck.checked) { item.checked = allCheck.checked; item.dispatchEvent(new Event("change", { bubbles: true })); }
      });
    }
  });

  document.addEventListener("click", function (event) {
    var tab = event.target.closest ? event.target.closest("[data-device-tab]") : null;
    if (tab) {
      state.tab = tab.getAttribute("data-device-tab");
      all("[data-device-tab]").forEach(function (button) { button.setAttribute("aria-selected", button === tab ? "true" : "false"); });
      all("[data-device-table]").forEach(function (table) { table.classList.toggle("hidden", table.getAttribute("data-device-table") !== state.tab); });
      restoreChecks(); updateSelection(); return;
    }
    var action = event.target.closest ? event.target.closest("[data-row-action]") : null;
    if (action) runRowAction(action);
  });

  function runRowAction(button) {
    var id = button.getAttribute("data-case-id");
    var kind = button.getAttribute("data-row-action");
    var row = button.closest("tr");
    var chip = row.querySelector("[data-row-result]");
    button.disabled = true;
    portal.request("/api/maintenance/cases/" + id + "/" + kind, { method: "POST" })
      .then(function (detail) {
        var stage = kind === "set-status" ? "snipeit_status" : "taken_back";
        var operation = (detail.stages || []).find(function (item) { return item.stage === stage; });
        if (operation && (operation.status === "failed" || operation.status === "not_done")) {
          chip.textContent = operation.reason || (operation.status === "not_done" ? "Not assigned" : "Failed");
          chip.className = "badge badge-destructive";
          return null;
        }
        chip.textContent = kind === "set-status" ? "Done" : "User removed";
        chip.className = "badge badge-success";
        if (kind === "take-back") {
          var remove = row.querySelector("[data-row-action='take-back']");
          if (remove) remove.remove();
        }
        return loadCases();
      })
      .catch(function (error) { chip.textContent = error.message; chip.className = "badge badge-destructive"; })
      .then(function () { button.disabled = false; });
  }

  function today() {
    var date = new Date();
    return date.getFullYear() + "-" + String(date.getMonth() + 1).padStart(2, "0") + "-" + String(date.getDate()).padStart(2, "0");
  }

  function openSendDrawer() {
    var ids = selectedIds("with_it");
    if (!ids.length) return;
    var drawer = portal.drawerForm("Send to vendor", {});
    var form = drawer.__form;
    var vendor = portal.selectInput("vendor_id", [{ value: "", label: "Select vendor" }]);
    form.appendChild(portal.field("Vendor", vendor));
    var newVendor = portal.textInput("new_vendor", "New vendor name", { maxlength: 120 });
    form.appendChild(portal.field("New vendor", newVendor));
    var day = portal.textInput("sent_date", "", { type: "date", value: today(), required: true });
    form.appendChild(portal.field("Day", day));
    var actions = portal.formActions("Send"); form.appendChild(actions);
    state.vendors.forEach(function (item) { var option = node("option", "", item.name); option.value = item.id; vendor.appendChild(option); });
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var vendorId = vendor.value;
      var create = vendorId ? Promise.resolve(null) : portal.apiJson("/api/maintenance/vendors", { method: "POST", body: JSON.stringify({ name: newVendor.value.trim() }) });
      create.then(function (created) {
        var id = vendorId || created.id;
        if (!id) throw new Error("Select or create a vendor.");
        return portal.apiJson("/api/maintenance/batches/send", { method: "POST", body: JSON.stringify({ case_ids: ids, vendor_id: Number(id), sent_date: day.value }) });
      }).then(function (results) {
        showBatchResults("Send", results, ids, "send"); return loadCases();
      }).catch(function (error) { portal.toast(error.message, "error"); }).then(function () { portal.setBusy(actions, false); });
    });
  }

  function openReceiveDrawer() {
    var ids = selectedIds("at_vendor");
    if (!ids.length) return;
    var drawer = portal.drawerForm("Receive batch", {});
    var form = drawer.__form;
    var day = portal.textInput("returned_date", "", { type: "date", value: today(), required: true });
    form.appendChild(portal.field("Date", day));
    var actions = portal.formActions("Receive"); form.appendChild(actions);
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      portal.setBusy(actions, true);
      portal.apiJson("/api/maintenance/batches/receive", { method: "POST", body: JSON.stringify({ case_ids: ids, returned_date: day.value }) })
        .then(function (results) { showBatchResults("Receive", results, ids, "receive"); return loadCases(); })
        .catch(function (error) { portal.toast(error.message, "error"); })
        .then(function () { portal.setBusy(actions, false); });
    });
  }

  function showBatchResults(title, results, ids, mode) {
    var drawer = portal.openDrawer(title + " results", node("div", "drawer-body stack-sm"));
    var body = drawer.querySelector(".drawer-body");
    results.forEach(function (result) {
      var item = state.items.find(function (candidate) { candidate.case_id === result.case_id; });
      var row = node("div", "maint-result-row");
      row.appendChild(node("strong", "", item ? item.serial : result.case_id));
      if (mode === "send") {
        row.appendChild(node("span", result.ok ? "badge badge-success" : "badge badge-destructive", result.ok ? "✓ Sent" : "✕ " + (result.error || "Failed")));
      } else {
        row.appendChild(node("span", "badge badge-success", "✓ Returned"));
        var ready = node("span", result.ok ? "badge badge-success" : "badge badge-warning", result.ok ? "✓ Status Ready" : "✕ Status Ready");
        row.appendChild(ready);
        if (!result.ok) {
          var retry = actionButton("Retry", "ready-status", { case_id: result.case_id });
          retry.addEventListener("click", function () {
            retry.disabled = true;
            portal.request("/api/maintenance/cases/" + result.case_id + "/ready-status", { method: "POST" }).then(function () {
              ready.textContent = "✓ Status Ready"; ready.className = "badge badge-success"; retry.remove();
            }).catch(function (error) { ready.textContent = error.message; retry.disabled = false; });
          });
          row.appendChild(retry);
        }
      }
      body.appendChild(row);
    });
  }

  portal.$("[data-batch-send]").addEventListener("click", openSendDrawer);
  portal.$("[data-batch-receive]").addEventListener("click", openReceiveDrawer);
  filterForm.addEventListener("submit", function (event) { event.preventDefault(); renderTables(); });
  filterForm.addEventListener("change", renderTables);

  populateReasons();
  populateVendors();
  loadCases();
})();
