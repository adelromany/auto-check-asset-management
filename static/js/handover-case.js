/* Handover case: independent Device, Recipient and Handover panels. */
"use strict";
(function () {
  var portal = window.portal;
  var caseId = document.body.getAttribute("data-case-id");
  var base = "/api/handovers/" + caseId;
  var detail = null;
  var items = [];

  function outcomeLabel(value) {
    return value === "complete" ? "Complete" : value === "ready" ? "Ready lab" : "Not complete";
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

  function renderMode(data) {
    document.querySelectorAll("[data-case-mode]").forEach(function (button) {
      button.setAttribute("aria-pressed", button.getAttribute("data-case-mode") === data.mode ? "true" : "false");
    });
    var panels = {
      "[data-device-panel]": true,
      "[data-recipient-panel]": data.mode === "snipeit",
      "[data-waiting-user-panel]": data.mode === "pending_user",
      "[data-handover-panel]": data.mode !== "none",
    };
    Object.keys(panels).forEach(function (selector) {
      var panel = document.querySelector(selector);
      if (panel) panel.classList.toggle("hidden", !panels[selector]);
    });
  }

  function renderLiveDevice(device) {
    var hadHolder = !!(detail && detail.device_holder_id);
    if (detail) {
      detail.snipeit_status_name = device.status;
      detail.device_holder_id = device.assigned_to && device.assigned_to.id;
      detail.device_holder_name = device.assigned_to && device.assigned_to.name;
    }
    var status = document.querySelector("[data-device-status]");
    if (status) {
      status.textContent = device.status || "—";
      status.className = "badge " + (device.status === "Ready to deploy" ? "badge-success" : device.deployable ? "badge-warning" : "badge-destructive");
    }
    var holder = device.assigned_to;
    setText("[data-device-holder]", holder ? "With: " + (holder.name || holder.username) + (holder.company ? " (" + holder.company + ")" : "") : "Not assigned");
    var slot = document.querySelector("[data-device-checkin-slot]");
    if (slot) portal.actionSlot(slot, {
      applicable: !!holder, done: !holder && hadHolder,
      doneLabel: "Checked in", label: "Check in", attribute: "data-device-checkin", onClick: function () {},
    });
    setText("[data-device-updated]", "Updated " + new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }));
    var useHolder = document.querySelector("[data-use-holder]");
    if (useHolder) useHolder.classList.toggle("hidden", !(holder && holder.id));
    renderStatusAction();
  }

  function deviceStatusStage() {
    return ((detail && detail.stages) || []).find(function (stage) { return stage.stage === "device_status"; });
  }

  function renderStatusAction() {
    var host = document.querySelector("[data-apply-status-slot]");
    var select = document.querySelector("[data-status-select]");
    if (!host || !select || !detail) return;
    var option = select.options[select.selectedIndex];
    var selectedName = option ? option.textContent : "";
    if (!selectedName) { host.textContent = ""; return; }
    if (selectedName !== detail.snipeit_status_name) {
      portal.actionSlot(host, {
        applicable: true, done: false, doneLabel: "", label: "Apply", attribute: "data-apply-status",
        onClick: applySelectedStatus,
      });
      return;
    }
    // The selected status is already the device's status: nothing to change, but
    // the engineer still has to be able to confirm it (Device status part).
    var stage = deviceStatusStage();
    var confirmed = !!stage && stage.status === "passed";
    portal.actionSlot(host, {
      applicable: !confirmed, done: confirmed, doneLabel: "Status confirmed",
      label: "Confirm status", attribute: "data-confirm-status", onClick: confirmCurrentStatus,
    });
  }

  function applySelectedStatus() {
    var select = document.querySelector("[data-status-select]");
    return portal.apiJson(base + "/device-status", { method: "POST", body: JSON.stringify({ status_label_id: Number(select.value) }) })
      .then(function (data) { renderDetail(data); refreshDevice(); portal.toast("Status applied.", "success"); })
      .catch(function (error) { portal.toast(error.message, "error"); throw error; });
  }

  // POST with no label = verify only: Snipe-IT is not changed, the current status is checked.
  function confirmCurrentStatus() {
    return portal.apiJson(base + "/device-status", { method: "POST", body: JSON.stringify({ status_label_id: null }) })
      .then(function (data) {
        renderDetail(data);
        var stage = deviceStatusStage();
        if (stage && stage.status === "passed") portal.toast("Status confirmed.", "success");
        else portal.toast((stage && stage.reason) || "Status is not Ready to deploy.", "error");
      })
      .catch(function (error) { portal.toast(error.message, "error"); throw error; });
  }

  function refreshDevice() {
    return portal.request(base + "/device-live").then(function (device) {
      renderLiveDevice(device);
      // The server confirms Device status itself when Snipe-IT already shows Ready.
      var stage = deviceStatusStage();
      if (stage && stage.status !== "passed") return loadDetail();
      return null;
    }).catch(function (error) {
      setText("[data-device-updated]", "Snipe-IT unavailable");
      portal.toast(error.message, "error");
    });
  }

  function renderDetail(data) {
    detail = data;
    var menuHost = document.querySelector("[data-case-menu]");
    if (menuHost) { menuHost.textContent = ""; menuHost.appendChild(portal.caseMenu(data.id, data.status, data.maintenance_state)); }
    renderMode(data);
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
    var canCheckout = data.mode === "snipeit" && !!data.recipient_snipeit_id;
    var checkoutStage = (data.stages || []).find(function (stage) { return stage.stage === "checkout"; });
    var checkout = document.querySelector("[data-checkout]");
    var reason = document.querySelector("[data-checkout-reason]");
    if (checkout) {
      checkout.disabled = !canCheckout;
      checkout.firstChild.textContent = checkoutStage && checkoutStage.status === "passed" ? "Check out again" : "Check out";
      var replace = document.querySelector("[data-replace-holder]");
      if (replace) replace.classList.add("hidden");
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
    renderStatusAction();
    var checkoutResult = document.querySelector("[data-checkout-result]");
    if (checkoutResult && checkoutStage && checkoutStage.status === "passed") {
      checkoutResult.textContent = "✓ Checked out to " + (data.recipient_snipeit_name || "recipient");
      checkoutResult.className = "field-hint text-success";
      checkoutResult.classList.remove("hidden");
    } else if (checkoutResult && checkoutStage && (checkoutStage.status === "failed" || checkoutStage.status === "not_done")) {
      checkoutResult.textContent = checkoutStage.reason || "Checkout failed. Review the device and try again.";
      checkoutResult.className = "field-error";
      checkoutResult.classList.remove("hidden");
    }
    var card = document.querySelector("[data-recipient-card]");
    if (card) {
      card.textContent = "";
      card.classList.remove("hidden");
      card.appendChild(portal.el("strong", "", data.recipient_snipeit_name || data.recipient_free_name || "No recipient"));
      card.appendChild(portal.el("div", "muted", data.recipient_snipeit_email || data.recipient_free_email || ""));
      if (hasCompanyMismatch(data)) card.appendChild(warningChip(data));
      if (data.pending_found_at && (!checkoutStage || checkoutStage.status !== "passed")) {
        card.appendChild(portal.el("span", "badge badge-warning", "Check out manually"));
      }
      var change = portal.actionButton("Change", "btn-outline btn-sm");
      change.addEventListener("click", function () { card.classList.add("hidden"); });
      card.appendChild(change);
    }
    setText("[data-pending-checked]", data.pending_checked_at ? "Last checked " + new Date(data.pending_checked_at).toLocaleString() : "Not checked yet");
    var pendingCode = document.querySelector("[data-pending-code]");
    var pendingUsername = document.querySelector("[data-pending-username]");
    if (pendingCode && document.activeElement !== pendingCode) pendingCode.value = data.recipient_employee_code || "";
    if (pendingUsername && document.activeElement !== pendingUsername) pendingUsername.value = data.recipient_username || "";
    setText("[data-logged-on-user]", data.logged_on_user ? "On device: " + data.logged_on_user : "");
    var useLogged = document.querySelector("[data-use-logged-user]");
    if (useLogged) useLogged.classList.toggle("hidden", !data.logged_on_user);
    var useHolder = document.querySelector("[data-use-holder]");
    if (useHolder) useHolder.classList.toggle("hidden", !data.device_holder_id);
    var useDeviceUser = document.querySelector("[data-use-device-user]");
    if (useDeviceUser) useDeviceUser.classList.toggle("hidden", !data.logged_on_user);
    renderPaper(data);
  }

  function savePendingUser() {
    return portal.apiJson(base + "/recipient", { method: "POST", body: JSON.stringify({
      mode: "pending_user", employee_code: document.querySelector("[data-pending-code]").value,
      username: document.querySelector("[data-pending-username]").value,
      name: document.querySelector("[data-pending-name]").value,
    }) }).then(function (data) { renderDetail(data); return data; }).catch(function (error) {
      var node = document.querySelector("[data-pending-error]"); node.textContent = error.message; node.classList.remove("hidden");
      return null;
    });
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
      renderStatusAction();
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
      if (candidate.employee_num) info.appendChild(portal.el("span", "muted mono", "Code " + candidate.employee_num));
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
          .then(function (data) { renderDetail(data); loadRecipientItems(); })
          .catch(function (error) { portal.setBusy(row, false); portal.toast(error.message, "error"); });
      });
      row.appendChild(pick);
      results.appendChild(row);
    });
  }

  function recipientItemsStage() {
    return ((detail && detail.stages) || []).find(function (stage) {
      return stage.stage === "recipient_items";
    }) || { status: "pending", detail: {} };
  }

  function renderRecipientItems() {
    var host = document.querySelector("[data-recipient-items]");
    if (!host || !detail) return;
    host.textContent = "";
    host.appendChild(portal.el("h3", "drawer-sub", "Other devices with this user"));
    var stage = recipientItemsStage();
    var facts = stage.detail || {};
    var reviewed = stage.status === "passed";
    var rows = items.map(function (item) {
      return { serial: item.serial || item.asset_tag || item.asset_id, model: item.model, id: item.asset_id, done: reviewed ? "Kept" : null };
    });
    (facts.checked_in || []).forEach(function (serial) {
      if (!rows.some(function (item) { return item.serial === serial; })) rows.push({ serial: serial, done: "Checked in" });
    });
    rows.forEach(function (item) {
      var label = portal.el(reviewed ? "div" : "label", "recipient-row");
      if (!reviewed) {
        var check = portal.el("input", "");
        check.type = "checkbox"; check.value = item.id;
        check.setAttribute("data-take-back", "");
        check.addEventListener("change", updateTakeBack);
        label.appendChild(check);
      }
      label.appendChild(portal.el("span", "mono", item.serial));
      label.appendChild(portal.el("span", "muted", item.model || ""));
      if (item.done) label.appendChild(portal.el("span", "badge badge-success", "✓ " + item.done));
      host.appendChild(label);
    });
    if (!rows.length) host.appendChild(portal.el("p", "muted", "None"));
    var actions = document.querySelector("[data-recipient-item-actions]");
    actions.classList.toggle("hidden", reviewed || !items.length);
    portal.actionSlot(document.querySelector("[data-items-checkin-slot]"), {
      applicable: !reviewed && !!items.length, done: false, doneLabel: "", label: "Check in",
      onClick: function () { return checkinSelectedItems(); },
    });
    portal.actionSlot(document.querySelector("[data-items-keep-slot]"), {
      applicable: !reviewed && !!items.length, done: false, doneLabel: "", label: "Keep all",
      onClick: function () { return keepRecipientItems(); },
    });
    updateTakeBack();
  }

  function loadRecipientItems() {
    if (!detail || detail.mode !== "snipeit") {
      items = [];
      renderRecipientItems();
      return Promise.resolve();
    }
    return portal.request(base + "/recipient/items").then(function (data) {
      items = data || [];
      renderRecipientItems();
    }).catch(function (error) { portal.toast(error.message, "error"); });
  }

  function updateTakeBack() {
    var host = document.querySelector("[data-items-checkin-slot]");
    var button = host && host.querySelector("button");
    if (button) button.disabled = !document.querySelector("[data-take-back]:checked");
  }

  function finishRecipientItems(data) {
    renderDetail(data);
    return loadRecipientItems();
  }

  function keepRecipientItems() {
    return portal.apiJson(base + "/recipient/items/confirm", { method: "POST" })
      .then(finishRecipientItems).catch(function (error) {
        var node = document.querySelector("[data-recipient-items-error]");
        node.textContent = error.message; node.classList.remove("hidden");
        throw error;
      });
  }

  function checkinSelectedItems() {
    var selected = Array.prototype.slice.call(document.querySelectorAll("[data-take-back]:checked")).map(function (node) { return Number(node.value); });
    if (!selected.length) return Promise.resolve();
    return portal.apiJson(base + "/recipient/items/checkin", { method: "POST", body: JSON.stringify({ asset_ids: selected }) })
      .then(function () { return portal.apiJson(base + "/recipient/items/confirm", { method: "POST" }); })
      .then(finishRecipientItems).catch(function (error) {
        var node = document.querySelector("[data-recipient-items-error]");
        node.textContent = error.message; node.classList.remove("hidden");
        throw error;
      });
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
    if (saved) {
      var download = portal.el("a", "link-quiet", "Download signed scan");
      download.href = base + "/document";
      host.appendChild(download);
    }
  }

  function performCheckout(replaceHolder) {
    var checkout = document.querySelector("[data-checkout]");
    var checkoutResult = document.querySelector("[data-checkout-result]");
    checkout.disabled = true;
    checkoutResult.textContent = "Checking out...";
    checkoutResult.className = "field-hint";
    checkoutResult.classList.remove("hidden");
    portal.apiJson(base + "/checkout", {
      method: "POST", body: JSON.stringify({ replace_holder: replaceHolder }),
    }).then(function (data) {
      renderDetail(data);
      refreshDevice();
      var stage = (data.stages || []).find(function (item) { return item.stage === "checkout"; });
      if (stage && stage.status === "passed") {
        portal.toast(stage.detail && stage.detail.already ? "Already checked out to this user." : "Checkout completed.", "success");
      } else {
        checkoutResult.textContent = (stage && stage.reason) || "Checkout did not complete.";
        checkoutResult.className = "field-error";
        checkoutResult.classList.remove("hidden");
      }
    }).catch(function (error) {
      checkout.disabled = false;
      checkoutResult.className = "field-error";
      checkoutResult.classList.remove("hidden");
      if (error.status === 409 && error.detail && error.detail.code === "held_by_other") {
        checkoutResult.textContent = "Held by " + error.detail.holder;
        document.querySelector("[data-replace-holder]").classList.remove("hidden");
      } else {
        checkoutResult.textContent = error.message || "Checkout failed. Try again.";
      }
    });
  }

  function showHardwareState(value) {
    var chip = document.querySelector("[data-form-hardware]");
    if (chip) chip.classList.toggle("hidden", value !== "missing");
  }

  function downloadWord() {
    return fetch(base + "/form?format=docx", { credentials: "same-origin" }).then(function (response) {
      showHardwareState(response.headers.get("X-Form-Hardware"));
      if (!response.ok) return response.json().then(function (body) { throw new Error(body.detail || "Download failed."); });
      return response.blob();
    }).then(function (blob) {
      var url = URL.createObjectURL(blob);
      var link = document.createElement("a");
      link.href = url; link.download = "handover-form.docx"; link.click();
      setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    });
  }

  document.addEventListener("click", function (event) {
    var target = event.target;
    if (!target || !target.closest) return;
    if (target.closest("[data-pending-save]")) savePendingUser();
    if (target.closest("[data-pending-check]")) {
      savePendingUser().then(function (saved) {
        if (!saved) return null;
        return portal.apiJson(base + "/pending-user/check", { method: "POST" });
      }).then(function (data) { if (data) renderDetail(data); }).catch(function (error) { portal.toast(error.message, "error"); });
    }
    if (target.closest("[data-use-logged-user]") && detail.logged_on_user) {
      document.querySelector("[data-pending-username]").value = detail.logged_on_user.split("\\").pop();
    }
    if (target.closest("[data-device-refresh]")) {
      refreshDevice();
    }
    if (target.closest("[data-device-checkin]")) {
      var checkinButton = target.closest("[data-device-checkin]");
      portal.setBusy(checkinButton.parentNode, true);
      portal.apiJson(base + "/device/checkin", { method: "POST" })
        .then(function (device) { renderLiveDevice(device); return loadDetail(); })
        .then(function () { portal.toast("Checked in.", "success"); })
        .catch(function (error) { portal.toast(error.message, "error"); })
        .then(function () { portal.setBusy(checkinButton.parentNode, false); });
    }
    if (target.closest("[data-check-device]")) {
      if (window.syncFlow) window.syncFlow.open({ handoverId: caseId, expectedSerial: document.body.getAttribute("data-case-serial") });
      else portal.toast("Device check is unavailable.", "error");
    }
    var modeButton = target.closest("[data-case-mode]");
    if (modeButton) {
      portal.apiJson(base + "/mode", {
        method: "POST",
        body: JSON.stringify({ mode: modeButton.getAttribute("data-case-mode") }),
      }).then(function (data) { renderDetail(data); loadRecipientItems(); })
        .catch(function (error) { portal.toast(error.message, "error"); });
    }
    if (target.closest("[data-download-word]")) {
      event.preventDefault();
      downloadWord();
    }
    if (target.closest("[data-print-form]")) {
      var formError = document.querySelector("[data-form-error]");
      fetch(base + "/form?format=pdf", { credentials: "same-origin" }).then(function (response) {
        showHardwareState(response.headers.get("X-Form-Hardware"));
        if (response.status === 503) {
          return downloadWord().then(function () {
            formError.textContent = "PDF printing is not available on the server (needs Microsoft Word or LibreOffice) \u2014 Word file downloaded instead.";
            formError.classList.remove("hidden");
            return null;
          });
        }
        if (!response.ok) return response.json().then(function (body) { throw new Error(body.detail || "Print form failed."); });
        return response.blob();
      }).then(function (blob) {
        if (!blob) return;
        var url = URL.createObjectURL(blob);
        var frame = document.createElement("iframe");
        frame.hidden = true;
        frame.src = url;
        frame.addEventListener("load", function () {
          frame.contentWindow.focus();
          frame.contentWindow.print();
          setTimeout(function () { URL.revokeObjectURL(url); frame.remove(); }, 60000);
        });
        document.body.appendChild(frame);
      }).catch(function (error) {
        formError.textContent = error.message;
        formError.classList.remove("hidden");
      });
    }
    if (target.closest("[data-checkout]")) performCheckout(false);
    if (target.closest("[data-replace-holder]")) performCheckout(true);
  });

  function showRecipientCandidates(path) {
    return portal.request(path + "&handover_id=" + encodeURIComponent(caseId))
      .then(renderRecipientResults).catch(function (error) { portal.toast(error.message, "error"); });
  }

  document.addEventListener("input", function (event) {
    if (!event.target.matches || !event.target.matches("[data-recipient-search]")) return;
    var query = event.target.value.trim();
    var results = document.querySelector("[data-recipient-results]");
    if (query.length < 2) { results.textContent = ""; return; }
    showRecipientCandidates("/api/snipeit/users?q=" + encodeURIComponent(query));
  });

  document.addEventListener("click", function (event) {
    var target = event.target;
    if (!target.closest) return;
    var search = document.querySelector("[data-recipient-search]");
    if (target.closest("[data-use-holder]") && detail && detail.device_holder_id) {
      if (search) search.value = detail.device_holder_name || "";
      showRecipientCandidates("/api/snipeit/users?user_id=" + encodeURIComponent(detail.device_holder_id));
    }
    if (target.closest("[data-use-device-user]") && detail && detail.logged_on_user) {
      var sam = detail.logged_on_user.split("\\").pop().trim();
      if (search) search.value = sam;
      if (sam.length >= 2) showRecipientCandidates("/api/snipeit/users?q=" + encodeURIComponent(sam));
    }
  });

  document.addEventListener("change", function (event) {
    if (event.target.matches && event.target.matches("[data-status-select]")) {
      renderStatusAction();
      return;
    }
    if (!event.target.matches || !event.target.matches("[data-signed-file]")) return;
    var file = event.target.files[0];
    if (!file) return;
    var selected = document.querySelector("[data-paper-selected]");
    if (selected) selected.textContent = "Uploading " + file.name + "...";
    var data = new FormData();
    data.append("file", file);
    portal.request(base + "/signed-paper", { method: "POST", body: data })
      .then(function (response) {
        renderDetail(response);
        if (selected) selected.textContent = "Uploaded " + file.name;
        event.target.value = "";
      }).catch(function (error) {
        if (selected) selected.textContent = error.message;
        portal.toast(error.message, "error");
      });
  });

  loadDetail().then(function () { loadStatuses(); loadRecipientItems(); refreshDevice(); });
})();
