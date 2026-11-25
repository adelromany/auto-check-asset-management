/* Handover case: independent Device, Recipient and Handover panels. */
"use strict";
(function () {
  var portal = window.portal;
  var caseId = document.body.getAttribute("data-case-id");
  var base = "/api/handovers/" + caseId;
  var detail = null;
  var items = [];

  function outcomeLabel(value) {
    return value === "complete" ? "Complete" : value === "ready" ? "Ready" : "Not complete yet";
  }

  function outcomeClass(value) {
    return value === "complete" ? "badge badge-success" : value === "ready" ? "badge badge-accent" : "badge badge-warning";
  }

  function setText(selector, value) {
    var node = document.querySelector(selector);
    if (node) node.textContent = value == null ? "—" : String(value);
  }

  function hasCompanyMismatch(data) {
    return (data.warnings || []).some(function (warning) { return warning.code === "company_mismatch"; });
  }

  function companyMismatchTitle(data) {
    return (data.device_company || "—") + " / " + (data.recipient_company || "—");
  }

  function warningChip(data) {
    var chip = portal.el("span", "badge badge-warning", "! Company differs");
    chip.title = companyMismatchTitle(data);
    return chip;
  }

  function renderDetail(data) {
    detail = data;
    var outcome = document.querySelector("[data-case-outcome]");
    if (outcome) {
      outcome.textContent = outcomeLabel(data.outcome);
      outcome.className = outcomeClass(data.outcome);
    }
    setText("[data-case-company]", data.device_company || "—");
    setText("[data-case-model]", data.device_model || "—");
    var headerWarning = document.querySelector("[data-header-warning]");
    if (headerWarning) {
      headerWarning.textContent = "";
      if (hasCompanyMismatch(data)) headerWarning.appendChild(warningChip(data));
    }
    var status = document.querySelector("[data-device-status]");
    if (status) {
      status.textContent = data.snipeit_status_name || "—";
      status.className = "badge " + (data.snipeit_status_name === "Ready to deploy" ? "badge-success" : "badge-outline");
    }
    var missing = document.querySelector("[data-missing-parts]");
    if (missing) {
      missing.textContent = "";
      (data.missing || []).forEach(function (part) {
        missing.appendChild(portal.el("span", "badge badge-outline", part.replace(/_/g, " ")));
      });
    }
    var canCheckout = data.recipient_mode === "snipeit" && !!data.recipient_snipeit_id;
    var checkout = document.querySelector("[data-checkout]");
    var reason = document.querySelector("[data-checkout-reason]");
    if (checkout) {
      checkout.disabled = !canCheckout;
      var oldMark = checkout.querySelector("[data-checkout-warn]");
      if (oldMark) oldMark.remove();
      if (hasCompanyMismatch(data)) {
        var mark = portal.el("span", "warn-mark", "!");
        mark.setAttribute("data-checkout-warn", "");
        mark.title = companyMismatchTitle(data);
        checkout.appendChild(document.createTextNode(" "));
        checkout.appendChild(mark);
      }
    }
    if (reason) reason.hidden = canCheckout;
    var card = document.querySelector("[data-recipient-card]");
    if (card) {
      card.textContent = "";
      card.classList.remove("hidden");
      card.appendChild(portal.el("strong", "", data.recipient_snipeit_name || data.recipient_free_name || "No recipient"));
      card.appendChild(portal.el("div", "muted", data.recipient_snipeit_email || data.recipient_free_email || ""));
      if (hasCompanyMismatch(data)) card.appendChild(warningChip(data));
      var change = portal.actionButton("Change", "btn-outline btn-sm");
      change.addEventListener("click", function () { card.classList.add("hidden"); });
      card.appendChild(change);
    }
    renderPaper(data);
  }

  function loadDetail() {
    return portal.request(base).then(renderDetail).catch(function (error) { portal.toast(error.message, "error"); });
  }

  function loadStatuses() {
    var select = document.querySelector("[data-status-select]");
    if (!select) return;
    portal.request("/api/snipeit/status-labels").then(function (labels) {
      select.textContent = "";
      labels.forEach(function (label) {
        var option = portal.el("option", "", label.name);
        option.value = label.id;
        if (detail && detail.snipeit_status_name === label.name) option.selected = true;
        select.appendChild(option);
      });
    }).catch(function (error) {
      var option = portal.el("option", "", "Status unavailable");
      select.appendChild(option);
      select.disabled = true;
      portal.toast(error.message, "error");
    });
  }

  function renderRecipientResults(users) {
    var results = document.querySelector("[data-recipient-results]");
    results.textContent = "";
    users.forEach(function (candidate) {
      var row = portal.el("div", "recipient-row");
      var info = portal.el("div", "stack-sm");
      info.appendChild(portal.el("strong", "", candidate.name || candidate.username || "—"));
      info.appendChild(portal.el("span", "muted", candidate.email || ""));
      var company = portal.el("div", "case-chips");
      company.appendChild(portal.el("span", "badge badge-secondary", candidate.company || "—"));
      if (candidate.same_company === false) {
        var mark = portal.el("span", "warn-mark", "!");
        mark.title = "Other company";
        company.appendChild(mark);
        company.appendChild(portal.el("span", "badge badge-warning", "Other company"));
      }
      info.appendChild(company);
      row.appendChild(info);
      var pick = portal.actionButton("Choose", "btn-default btn-sm");
      pick.addEventListener("click", function () {
        portal.setBusy(row, true);
        portal.apiJson(base + "/recipient", { method: "POST", body: JSON.stringify({ mode: "snipeit", user_id: candidate.id }) })
          .then(loadDetail).catch(function (error) { portal.setBusy(row, false); portal.toast(error.message, "error"); });
      });
      row.appendChild(pick);
      results.appendChild(row);
    });
  }

  function loadRecipientItems() {
    if (!detail || detail.recipient_mode !== "snipeit") return;
    portal.request(base + "/recipient/items").then(function (data) {
      items = data || [];
      var host = document.querySelector("[data-recipient-items]");
      host.textContent = "";
      host.appendChild(portal.el("h3", "drawer-sub", "Current items"));
      if (!items.length) {
        host.appendChild(portal.el("p", "muted", "None"));
        return;
      }
      items.forEach(function (item) {
        var label = portal.el("label", "recipient-row");
        var check = portal.el("input", "");
        check.type = "checkbox";
        check.value = item.asset_id;
        check.setAttribute("data-take-back", "");
        check.addEventListener("change", updateTakeBack);
        label.appendChild(check);
        label.appendChild(portal.el("span", "mono", item.serial || item.asset_tag || item.asset_id));
        label.appendChild(portal.el("span", "muted", item.model || ""));
        host.appendChild(label);
      });
      updateTakeBack();
    }).catch(function (error) { portal.toast(error.message, "error"); });
  }

  function updateTakeBack() {
    var button = document.querySelector("[data-take-back-selected]");
    if (button) button.disabled = !document.querySelector("[data-take-back]:checked");
  }

  function renderPaper(data) {
    var host = document.querySelector("[data-paper-state]");
    if (!host) return;
    host.textContent = "";
    var saved = (data.stages || []).some(function (stage) { return stage.stage === "document_scanned" && stage.status === "passed"; });
    var pushed = (data.stages || []).some(function (stage) { return stage.stage === "document_pushed" && stage.status === "passed"; });
    host.appendChild(portal.el("span", saved ? "state-ok" : "state-fail", saved ? "✓ Saved" : "✕ Saved"));
    host.appendChild(portal.el("span", pushed ? "state-ok" : "state-fail", pushed ? "✓ Attached to Snipe-IT" : "✕ Attached to Snipe-IT"));
    if (saved && !pushed) {
      var retry = portal.actionButton("Retry", "btn-outline btn-sm");
      retry.addEventListener("click", function () {
        portal.setBusy(retry.parentNode, true);
        portal.apiJson(base + "/operations/document_pushed/retry", { method: "POST" })
          .then(renderDetail).catch(function (error) { portal.setBusy(retry.parentNode, false); portal.toast(error.message, "error"); });
      });
      host.appendChild(retry);
    }
  }

  document.addEventListener("click", function (event) {
    var target = event.target;
    if (!target || !target.closest) return;
    if (target.closest("[data-apply-status]")) {
      var select = document.querySelector("[data-status-select]");
      portal.apiJson(base + "/device-status", { method: "POST", body: JSON.stringify({ status_label_id: Number(select.value) }) })
        .then(function (data) { renderDetail(data); portal.toast("Status applied.", "success"); })
        .catch(function (error) { portal.toast(error.message, "error"); });
    }
    if (target.closest("[data-check-device]")) {
      if (window.syncFlow) window.syncFlow.open({ handoverId: caseId, expectedSerial: document.body.getAttribute("data-case-serial") });
      else portal.toast("Device check is unavailable.", "error");
    }
    if (target.closest("[data-recipient-none]")) {
      portal.apiJson(base + "/recipient", { method: "POST", body: JSON.stringify({ mode: "none" }) })
        .then(loadDetail).catch(function (error) { portal.toast(error.message, "error"); });
    }
    if (target.closest("[data-recipient-external]")) {
      document.querySelector("[data-recipient-external-fields]").classList.remove("hidden");
    }
    if (target.closest("[data-recipient-save]")) {
      var name = document.querySelector("[data-recipient-name]").value.trim();
      var email = document.querySelector("[data-recipient-email]").value.trim();
      portal.apiJson(base + "/recipient", { method: "POST", body: JSON.stringify({ mode: "not_in_snipeit", name: name, email: email }) })
        .then(loadDetail).catch(function (error) { portal.toast(error.message, "error"); });
    }
    if (target.closest("[data-take-back-selected]")) {
      var selected = Array.prototype.slice.call(document.querySelectorAll("[data-take-back]:checked")).map(function (node) { return Number(node.value); });
      portal.apiJson(base + "/recipient/items/checkin", { method: "POST", body: JSON.stringify({ asset_ids: selected }) })
        .then(loadRecipientItems).catch(function (error) { portal.toast(error.message, "error"); });
    }
    if (target.closest("[data-confirm-items]")) {
      portal.apiJson(base + "/recipient/items/confirm", { method: "POST" })
        .then(loadDetail).catch(function (error) { portal.toast(error.message, "error"); });
    }
    if (target.closest("[data-print-form]")) {
      fetch(base + "/form", { credentials: "same-origin" }).then(function (response) {
        if (!response.ok) return response.json().then(function (body) { throw new Error(body.detail || "Print form failed."); });
        return response.blob();
      }).then(function (blob) {
        var link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = "handover-form.docx";
        link.click();
        URL.revokeObjectURL(link.href);
      }).catch(function (error) {
        var node = document.querySelector("[data-form-error]");
        node.textContent = error.message;
        node.classList.remove("hidden");
      });
    }
    if (target.closest("[data-checkout]")) {
      portal.apiJson(base + "/checkout", { method: "POST" })
        .then(loadDetail).catch(function (error) { portal.toast(error.message, "error"); });
    }
  });

  document.addEventListener("input", function (event) {
    if (!event.target.matches || !event.target.matches("[data-recipient-search]")) return;
    var query = event.target.value.trim();
    var results = document.querySelector("[data-recipient-results]");
    if (query.length < 2) { results.textContent = ""; return; }
    portal.request("/api/snipeit/users?q=" + encodeURIComponent(query) + "&handover_id=" + encodeURIComponent(caseId))
      .then(renderRecipientResults).catch(function (error) { portal.toast(error.message, "error"); });
  });

  document.addEventListener("change", function (event) {
    if (!event.target.matches || !event.target.matches("[data-signed-file]")) return;
    var file = event.target.files[0];
    if (!file) return;
    var data = new FormData();
    data.append("file", file);
    portal.request(base + "/signed-paper", { method: "POST", body: data })
      .then(renderDetail).catch(function (error) { portal.toast(error.message, "error"); });
  });

  loadDetail().then(function () { loadStatuses(); loadRecipientItems(); });
})();
