"use strict";
(function () {
  var portal = window.portal;
  var grid = portal.$("[data-vendor-grid]");
  var overview = portal.$("[data-vendor-overview]");
  var analytics = portal.$("[data-vendor-analytics]");
  var showInactive = portal.$("[data-show-inactive]");
  var vendors = [];

  function text(value) {
    return value === null || value === undefined || value === "" ? "-" : String(value);
  }

  function metric(label, value, note, tone) {
    var card = portal.el("article", "vendor-metric" + (tone ? " vendor-metric-" + tone : ""));
    card.appendChild(portal.el("span", "vendor-metric-label", label));
    card.appendChild(portal.el("strong", "vendor-metric-value mono", value));
    if (note) card.appendChild(portal.el("span", "vendor-metric-note", note));
    return card;
  }

  function renderOverview() {
    overview.textContent = "";
    var active = vendors.filter(function (item) { return item.is_active; });
    var inService = active.reduce(function (sum, item) { return sum + item.at_vendor_now; }, 0);
    var overdue = active.reduce(function (sum, item) { return sum + item.overdue_now; }, 0);
    var returned = active.reduce(function (sum, item) { return sum + item.returned_total; }, 0);
    var weightedDays = active.reduce(function (sum, item) {
      return sum + (item.avg_days || 0) * item.returned_total;
    }, 0);
    overview.appendChild(metric("Active vendors", String(active.length), "Available for new sends"));
    overview.appendChild(metric("At vendors now", String(inService), "Open repair cases", inService ? "accent" : "muted"));
    overview.appendChild(metric("Overdue", String(overdue), "Past expected return", overdue ? "warning" : "muted"));
    overview.appendChild(metric("Returned cases", String(returned), "Completed vendor visits"));
    overview.appendChild(metric("Avg turnaround", returned ? (weightedDays / returned).toFixed(1) + " d" : "-", "Returned cases only"));
  }

  function renderAnalytics() {
    analytics.textContent = "";
    var ranked = vendors.slice().sort(function (a, b) {
      return b.total_sent - a.total_sent || a.name.localeCompare(b.name);
    });
    if (!ranked.length) {
      analytics.appendChild(portal.el("p", "vendor-no-activity", "No vendors to analyze yet."));
      return;
    }
    var maxSent = Math.max(1, ...ranked.map(function (item) { return item.total_sent; }));
    var wrap = portal.el("div", "vendor-analysis-table-wrap");
    var table = portal.el("table", "table vendor-analysis-table");
    var head = portal.el("thead");
    var header = portal.el("tr");
    ["Vendor", "At vendor", "Returned", "Avg days", "Overdue", "Send volume"].forEach(function (label) {
      header.appendChild(portal.el("th", "table-head", label));
    });
    head.appendChild(header);
    table.appendChild(head);
    var body = portal.el("tbody");
    ranked.forEach(function (item) {
      var row = portal.el("tr", "table-row");
      var nameCell = portal.el("td", "table-cell");
      var vendorLink = portal.el("a", "row-link vendor-analysis-link", item.name);
      vendorLink.href = "#vendor-" + item.id;
      nameCell.appendChild(vendorLink);
      if (!item.is_active) nameCell.appendChild(portal.el("span", "badge ml-2", "Inactive"));
      row.appendChild(nameCell);
      row.appendChild(portal.el("td", "table-cell mono", String(item.at_vendor_now)));
      row.appendChild(portal.el("td", "table-cell mono", String(item.returned_total)));
      row.appendChild(portal.el("td", "table-cell mono", item.avg_days == null ? "-" : Number(item.avg_days).toFixed(1)));
      row.appendChild(portal.el("td", "table-cell mono" + (item.overdue_now ? " text-destructive font-semibold" : ""), String(item.overdue_now)));
      var volume = portal.el("td", "table-cell");
      var line = portal.el("div", "vendor-volume-line");
      var track = portal.el("span", "vendor-volume-track");
      var fill = portal.el("span", "vendor-volume-fill");
      fill.style.width = Math.round(item.total_sent * 100 / maxSent) + "%";
      track.appendChild(fill);
      line.appendChild(track);
      line.appendChild(portal.el("strong", "mono", String(item.total_sent)));
      volume.appendChild(line);
      row.appendChild(volume);
      body.appendChild(row);
    });
    table.appendChild(body);
    wrap.appendChild(table);
    analytics.appendChild(wrap);
  }

  function load() {
    var path = "/api/maintenance/vendors" + (showInactive.checked ? "?include_inactive=true" : "");
    return portal.request(path).then(function (items) {
      vendors = items || [];
      renderOverview();
      renderAnalytics();
      grid.textContent = "";
      if (!vendors.length) {
        var state = portal.el("div", "vendor-empty");
        state.appendChild(portal.el("p", "muted", "No vendor contacts yet."));
        grid.appendChild(state);
        return;
      }
      vendors.forEach(renderVendor);
    }).catch(function (error) { portal.toast(error.message, "error"); });
  }

  function renderVendor(item) {
    var card = portal.el("article", "card vendor-card");
    card.id = "vendor-" + item.id;
    var head = portal.el("div", "card-header row-between");
    head.appendChild(portal.el("h3", "card-title", item.name));
    if (!item.is_active) head.appendChild(portal.el("span", "badge", "Inactive"));
    card.appendChild(head);
    var body = portal.el("div", "card-content stack-sm");
    var contact = portal.el("div", "vendor-contact");
    if (item.contact_name) contact.appendChild(portal.el("strong", "", item.contact_name));
    if (item.phone) {
      var phone = portal.el("a", "", item.phone);
      phone.href = "tel:" + item.phone;
      contact.appendChild(phone);
    }
    if (item.email) {
      var email = portal.el("a", "", item.email);
      email.href = "mailto:" + item.email;
      contact.appendChild(email);
    }
    if (!contact.childNodes.length) contact.appendChild(portal.el("span", "muted", "No contact details"));
    body.appendChild(contact);
    if (item.notes) body.appendChild(portal.el("p", "muted vendor-notes", item.notes));
    var actions = portal.el("div", "row-actions");
    var edit = portal.el("button", "btn btn-outline btn-sm", "Edit");
    edit.type = "button";
    edit.addEventListener("click", function () { openForm(item); });
    actions.appendChild(edit);
    var toggle = portal.el("button", "btn btn-outline btn-sm", item.is_active ? "Deactivate" : "Activate");
    toggle.type = "button";
    toggle.addEventListener("click", function () {
      portal.apiJson("/api/maintenance/vendors/" + item.id, { method: "PATCH", body: JSON.stringify({ is_active: !item.is_active }) })
        .then(load).catch(function (error) { portal.toast(error.message, "error"); });
    });
    actions.appendChild(toggle);
    if (item.can_delete) {
      var remove = portal.el("button", "btn btn-ghost btn-sm", "Delete");
      remove.type = "button";
      remove.addEventListener("click", function () {
        portal.apiJson("/api/maintenance/vendors/" + item.id, { method: "DELETE" })
          .then(load).catch(function (error) { portal.toast(error.message, "error"); });
      });
      actions.appendChild(remove);
    }
    body.appendChild(actions);
    card.appendChild(body);
    grid.appendChild(card);
  }

  function openForm(item) {
    var drawer = portal.drawerForm(item ? "Edit vendor" : "Add vendor", {});
    var form = drawer.__form;
    var fields = [
      ["Name", "name", 120], ["Contact", "contact_name", 120],
      ["Phone", "phone", 40], ["Email", "email", 200], ["Notes", "notes", 500]
    ];
    var inputs = {};
    fields.forEach(function (field) {
      var control = portal.textInput(field[1], "", { value: item ? (item[field[1]] || "") : "", maxlength: field[2], required: field[1] === "name" });
      inputs[field[1]] = control;
      form.appendChild(portal.field(field[0], control));
    });
    var error = portal.el("p", "field-error", "");
    error.setAttribute("aria-live", "polite");
    form.appendChild(error);
    var actions = portal.formActions("Save");
    form.appendChild(actions);
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      error.textContent = "";
      portal.setBusy(actions, true);
      var payload = {};
      Object.keys(inputs).forEach(function (key) { payload[key] = inputs[key].value.trim() || null; });
      var path = "/api/maintenance/vendors" + (item ? "/" + item.id : "");
      portal.apiJson(path, { method: item ? "PATCH" : "POST", body: JSON.stringify(payload) })
        .then(function () { portal.closeDrawer(); return load(); })
        .catch(function (err) { error.textContent = err.message; portal.setBusy(actions, false); });
    });
  }

  portal.$("[data-add-vendor]").addEventListener("click", function () { openForm(null); });
  showInactive.addEventListener("change", load);
  load();
}());
