/**
 * Handover case page: stage actions, recipient search, Snipe-IT preview,
 * scan upload and the cancel action.
 *
 * Every server response is reflected by reloading the server-rendered page
 * (single source of truth); a short flash message survives the reload.
 * Dynamic text is always inserted with textContent.
 */
"use strict";

(function () {
  var main = document.querySelector("main[data-handover-id]");
  if (!main) return;
  var handoverId = main.getAttribute("data-handover-id");
  var base = "/api/handovers/" + encodeURIComponent(handoverId);
  var FLASH_KEY = "handoverFlash";

  // -- feedback ---------------------------------------------------------
  function showToast(message, kind) {
    var stack = document.getElementById("toast-stack");
    if (!stack) return;
    var toast = document.createElement("div");
    toast.className = "toast " + (kind === "error" ? "toast-error" : "toast-success");
    toast.setAttribute("role", kind === "error" ? "alert" : "status");
    toast.textContent = message;
    stack.appendChild(toast);
    window.setTimeout(function () {
      toast.remove();
    }, 6000);
  }

  function showStoredFlash() {
    var raw = null;
    try {
      raw = sessionStorage.getItem(FLASH_KEY);
      sessionStorage.removeItem(FLASH_KEY);
    } catch (error) {
      raw = null;
    }
    if (!raw) return;
    try {
      var flash = JSON.parse(raw);
      showToast(flash.message, flash.kind || "success");
    } catch (error) {
      /* a corrupt flash is not worth breaking the page */
    }
  }

  function flashAndReload(message, kind) {
    try {
      sessionStorage.setItem(
        FLASH_KEY,
        JSON.stringify({ message: message, kind: kind || "success" })
      );
    } catch (error) {
      /* storage blocked: the server-rendered page still shows the result */
    }
    window.location.reload();
  }

  function detailText(body) {
    if (!body) return "";
    var detail = body.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map(function (item) {
          return item && item.msg ? item.msg : String(item);
        })
        .join("; ");
    }
    return "";
  }

  async function request(path, options) {
    options = options || {};
    var method = (options.method || "GET").toUpperCase();
    var init = {
      method: method,
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    };
    if (method !== "GET" && method !== "HEAD" && window.HandoverShell) {
      var token = await window.HandoverShell.csrfToken();
      if (token) init.headers["X-CSRF-Token"] = token;
    }
    if (options.json !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.json);
    }
    if (options.body !== undefined) init.body = options.body;
    var response = await fetch(path, init);
    var body = null;
    try {
      body = await response.json();
    } catch (error) {
      body = null;
    }
    if (!response.ok) {
      throw new Error(
        detailText(body) || "Request failed (" + response.status + ")."
      );
    }
    return body;
  }

  function setBusy(button, busy) {
    if (!button) return;
    button.disabled = busy;
    if (busy) {
      button.setAttribute("aria-busy", "true");
    } else {
      button.removeAttribute("aria-busy");
    }
  }

  function stageOf(detail, stageKey) {
    if (!detail || !detail.stages) return null;
    for (var index = 0; index < detail.stages.length; index += 1) {
      if (detail.stages[index].stage === stageKey) return detail.stages[index];
    }
    return null;
  }

  // -- stage confirm ----------------------------------------------------
  async function confirmStage(button) {
    var stage = button.getAttribute("data-stage");
    var confirmation = button.getAttribute("data-confirm-message");
    if (confirmation && !window.confirm(confirmation)) return;
    setBusy(button, true);
    try {
      await request(base + "/stages/" + encodeURIComponent(stage) + "/confirm", {
        method: "POST",
      });
      flashAndReload("Stage confirmed: " + stage + ".", "success");
    } catch (error) {
      showToast(error.message, "error");
      setBusy(button, false);
    }
  }

  // -- recipient --------------------------------------------------------
  function clear(element) {
    element.replaceChildren();
  }

  function textElement(tag, className, text) {
    var element = document.createElement(tag);
    if (className) element.className = className;
    element.textContent = text;
    return element;
  }

  function renderCandidates(result) {
    var container = document.getElementById("recipient-results");
    if (!container) return;
    clear(container);

    if (result.warning) {
      var warning = document.createElement("div");
      warning.className = "alert alert-warning";
      warning.appendChild(textElement("p", "alert-title", "Check the reported user"));
      warning.appendChild(textElement("p", "alert-description", result.warning));
      container.appendChild(warning);
    }

    if (!result.candidates || result.candidates.length === 0) {
      container.appendChild(
        textElement("p", "text-sm text-muted-foreground", "No Snipe-IT user matched.")
      );
      return;
    }

    result.candidates.forEach(function (candidate) {
      var label = document.createElement("label");
      label.className = "flex cursor-pointer items-start gap-2 rounded-md border p-2 text-sm";

      var radio = document.createElement("input");
      radio.type = "radio";
      radio.name = "recipient-candidate";
      radio.value = String(candidate.id);
      radio.className = "mt-1";

      var body = document.createElement("span");
      body.className = "flex min-w-0 flex-col";
      body.appendChild(
        textElement(
          "span",
          "font-medium",
          candidate.name || candidate.username || "Snipe-IT user " + candidate.id
        )
      );
      body.appendChild(
        textElement(
          "span",
          "font-mono text-xs text-muted-foreground",
          (candidate.username || "") +
            (candidate.email ? " · " + candidate.email : "")
        )
      );
      if (candidate.matches_reported) {
        body.appendChild(
          textElement("span", "badge badge-success mt-1", "Reported by the agent")
        );
      }
      if (candidate.matches_engineer) {
        body.appendChild(
          textElement("span", "badge badge-warning mt-1", "This is your own account")
        );
      }

      label.appendChild(radio);
      label.appendChild(body);
      container.appendChild(label);
    });

    var confirm = document.createElement("button");
    if (result.same_as_engineer) {
      var acknowledgement = document.createElement("label");
      acknowledgement.className = "flex items-start gap-2 text-sm";
      var checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.id = "ack-same-as-engineer";
      checkbox.className = "mt-1";
      acknowledgement.appendChild(checkbox);
      acknowledgement.appendChild(
        textElement("span", "text-muted-foreground", "I acknowledge this is my own account and confirm the recipient deliberately.")
      );
      container.appendChild(acknowledgement);
    }
    confirm.type = "button";
    confirm.className = "btn btn-default btn-sm self-start";
    confirm.setAttribute("data-action", "confirm-recipient");
    confirm.textContent = "Confirm selected recipient";
    container.appendChild(confirm);
  }

  async function searchRecipients(event) {
    event.preventDefault();
    var form = event.currentTarget;
    var query = document.getElementById("recipient-query").value.trim();
    var button = form.querySelector("button[type=submit]");
    setBusy(button, true);
    try {
      var searchPath = base + "/recipient/search";
      if (query) searchPath += "?q=" + encodeURIComponent(query);
      var result = await request(
        searchPath,
        { method: "POST" }
      );
      renderCandidates(result);
    } catch (error) {
      showToast(error.message, "error");
    } finally {
      setBusy(button, false);
    }
  }

  async function confirmRecipient(button) {
    var checked = document.querySelector(
      "input[name=recipient-candidate]:checked"
    );
    if (!checked) {
      showToast("Choose a Snipe-IT user first.", "error");
      return;
    }
    setBusy(button, true);
    try {
      var acknowledgement = document.getElementById("ack-same-as-engineer");
      await request(base + "/recipient/confirm", {
        method: "POST",
        json: {
          snipeit_user_id: Number(checked.value),
          acknowledge_same_as_engineer: Boolean(acknowledgement && acknowledgement.checked),
        },
      });
      flashAndReload("Recipient confirmed.", "success");
    } catch (error) {
      showToast(error.message, "error");
      setBusy(button, false);
    }
  }

  async function recipientNotFound(button) {
    var proceed = window.confirm(
      "Mark the recipient as not in Snipe-IT? Checkout needs a confirmed recipient, or mark it not done."
    );
    if (!proceed) return;
    setBusy(button, true);
    try {
      await request(base + "/recipient/confirm", {
        method: "POST",
        json: { not_found: true },
      });
      flashAndReload("Recipient marked as not in Snipe-IT.", "success");
    } catch (error) {
      showToast(error.message, "error");
      setBusy(button, false);
    }
  }

  // -- preview / checkout / checkin -------------------------------------
  function renderPreview(preview) {
    var panel = document.getElementById("preview-panel");
    var devices = document.getElementById("recipient-devices");
    if (!panel) return;
    clear(panel);
    panel.classList.remove("hidden");

    panel.appendChild(textElement("p", "font-medium", "Dry run: no Snipe-IT writes were made."));

    if (preview.warnings && preview.warnings.length) {
      preview.warnings.forEach(function (warning) {
        panel.appendChild(
          textElement("p", "mt-1 text-xs text-muted-foreground", warning)
        );
      });
    }

    var checkoutCalls = (preview.calls || []).filter(function (call) {
      return call.action === "checkout";
    });
    var checkinCalls = (preview.calls || []).filter(function (call) {
      return call.action === "checkin";
    });

    if (checkoutCalls.length === 0) {
      panel.appendChild(
        textElement("p", "mt-2 text-xs text-muted-foreground", "No checkout call would be made.")
      );
    }
    checkoutCalls.forEach(function (call) {
      panel.appendChild(textElement("p", "mt-2 text-sm", call.description));
    });

    if (!devices) return;
    clear(devices);
    if (checkinCalls.length === 0) {
      devices.appendChild(
        textElement(
          "p",
          "text-sm text-muted-foreground",
          "No old devices would be checked in."
        )
      );
      return;
    }
    checkinCalls.forEach(function (call) {
      var row = document.createElement("div");
      row.className = "flex flex-wrap items-center justify-between gap-2 rounded-md border p-2";
      row.appendChild(textElement("span", "text-sm", call.description));
      var button = document.createElement("button");
      button.type = "button";
      button.className = "btn btn-outline btn-sm";
      button.setAttribute("data-action", "checkin");
      button.setAttribute("data-asset-id", String(call.asset_id));
      button.textContent = "Checkin";
      row.appendChild(button);
      devices.appendChild(row);
    });
  }

  async function preview(button, quiet) {
    setBusy(button, true);
    try {
      var result = await request(base + "/preview");
      renderPreview(result);
      if (!quiet) {
        showToast("Assigned devices loaded; no Snipe-IT changes were made.", "success");
      }
    } catch (error) {
      showToast(error.message, "error");
    } finally {
      setBusy(button, false);
    }
  }

  async function checkout(button) {
    var proceed = window.confirm(
      "Checkout this device to the confirmed recipient in Snipe-IT now?"
    );
    if (!proceed) return;
    setBusy(button, true);
    try {
      var detail = await request(base + "/checkout", { method: "POST" });
      var stage = stageOf(detail, "checkout");
      if (stage && stage.status === "passed") {
        flashAndReload("Device checked out and verified in Snipe-IT.", "success");
      } else {
        flashAndReload(
          (stage && stage.reason) || "Checkout did not pass; see the stage reason.",
          "error"
        );
      }
    } catch (error) {
      showToast(error.message, "error");
      setBusy(button, false);
    }
  }

  async function checkin(button) {
    var assetId = button.getAttribute("data-asset-id");
    var proceed = window.confirm(
      "Checkin this device from the recipient in Snipe-IT now? The device becomes unassigned."
    );
    if (!proceed) return;
    setBusy(button, true);
    try {
      var result = await request(base + "/checkin", {
        method: "POST",
        json: { asset_ids: [Number(assetId)] },
      });
      var outcome = result.results && result.results[0];
      var message = outcome
        ? "Checkin: " + outcome.status + (outcome.message ? " — " + outcome.message : "")
        : "Checkin finished.";
      flashAndReload(
        message,
        outcome && outcome.status === "checked_in" ? "success" : "error"
      );
    } catch (error) {
      showToast(error.message, "error");
      setBusy(button, false);
    }
  }

  // -- document ---------------------------------------------------------
  async function upload(event) {
    event.preventDefault();
    var input = document.getElementById("document-file");
    var button = event.currentTarget.querySelector("button[type=submit]");
    if (!input || !input.files || input.files.length === 0) {
      showToast("Choose a PDF, PNG or JPEG file first.", "error");
      return;
    }
    var data = new FormData();
    data.append("file", input.files[0]);
    setBusy(button, true);
    try {
      var documentRecord = await request(base + "/document", {
        method: "POST",
        body: data,
      });
      flashAndReload("Scan attached: " + documentRecord.original_name + ".", "success");
    } catch (error) {
      showToast(error.message, "error");
      setBusy(button, false);
    }
  }

  async function pushDocument(button) {
    var proceed = window.confirm(
      "Push the signed scan to this device's Snipe-IT asset now?"
    );
    if (!proceed) return;
    setBusy(button, true);
    try {
      var detail = await request(base + "/document/push", { method: "POST" });
      var stage = stageOf(detail, "document_pushed");
      if (stage && stage.status === "passed") {
        flashAndReload("Scan pushed to Snipe-IT and verified.", "success");
      } else {
        flashAndReload(
          (stage && stage.reason) || "Push did not pass; see the stage reason.",
          "error"
        );
      }
    } catch (error) {
      showToast(error.message, "error");
      setBusy(button, false);
    }
  }

  // -- independent operations / closing ---------------------------------
  async function markNotDone(button) {
    var stage = button.getAttribute("data-stage");
    var title = button.getAttribute("data-operation-title") || stage;
    var reason = window.prompt(
      "Why was " + title + " not done? (3–300 characters; this stays visible as a gap.)",
      ""
    );
    if (reason === null) return;
    reason = reason.trim();
    if (reason.length < 3 || reason.length > 300) {
      showToast("Enter a reason between 3 and 300 characters.", "error");
      return;
    }
    setBusy(button, true);
    try {
      await request(base + "/operations/" + encodeURIComponent(stage) + "/not-done", {
        method: "POST",
        json: { reason: reason },
      });
      flashAndReload(title + " recorded as not done.", "success");
    } catch (error) {
      showToast(error.message, "error");
      setBusy(button, false);
    }
  }

  async function closeCase(button) {
    var confirmation = window.prompt(
      "This closes the case and records the missing operations as gaps. Type CLOSE to confirm.",
      ""
    );
    if (confirmation === null) return;
    setBusy(button, true);
    try {
      await request(base + "/close", {
        method: "POST",
        json: { confirmation: confirmation },
      });
      flashAndReload("Case closed with gaps.", "success");
    } catch (error) {
      showToast(error.message, "error");
      setBusy(button, false);
    }
  }

  async function reopenCase(button) {
    if (!window.confirm("Reopen this case so its missing operations can be finished?")) return;
    setBusy(button, true);
    try {
      await request(base + "/reopen", { method: "POST" });
      flashAndReload("Case reopened.", "success");
    } catch (error) {
      showToast(error.message, "error");
      setBusy(button, false);
    }
  }

  // -- cancel -----------------------------------------------------------
  async function cancel(button) {
    var proceed = window.confirm(
      "Cancel this handover? No further stage can be confirmed and this cannot be undone."
    );
    if (!proceed) return;
    setBusy(button, true);
    try {
      await request(base + "/cancel", { method: "POST" });
      flashAndReload("Handover cancelled.", "success");
    } catch (error) {
      showToast(error.message, "error");
      setBusy(button, false);
    }
  }

  // -- wiring -----------------------------------------------------------
  // -- drawer controller ------------------------------------------------
  var activeDrawerStage = null;

  var STAGE_LABELS = {
    device_prepared: "Device prepared",
    user_account_created: "User signed in",
    agent_report: "Agent report",
    software_check: "Software check",
    recipient_check: "Recipient check",
    snipeit_checkout: "Checkout",
    print_form: "Print form",
    paper_signed: "Signed paper",
    scan_attached: "Scan attached",
    snipeit_push: "Push to Snipe-IT",
    received: "Received",
    diagnosis: "Diagnosis",
    snipeit_status: "Snipe-IT status",
    sent_out: "Sent out",
    returned: "Returned",
  };

  function openDrawer(stageKey) {
    if (!stageKey) return;
    activeDrawerStage = stageKey;

    var drawer = document.getElementById("operation-drawer");
    var backdrop = document.getElementById("drawer-backdrop");
    var title = document.getElementById("drawer-title");
    var retryBtn = document.getElementById("drawer-retry-btn");

    if (title) {
      title.textContent = STAGE_LABELS[stageKey] || stageKey;
    }

    // Switch visible panel
    document.querySelectorAll("[data-drawer-panel]").forEach(function (panel) {
      if (panel.getAttribute("data-drawer-panel") === stageKey) {
        panel.classList.remove("hidden");
      } else {
        panel.classList.add("hidden");
      }
    });

    // Configure retry button
    if (retryBtn) {
      var tile = document.querySelector('[data-tile="' + stageKey + '"]');
      var badge = tile ? tile.querySelector(".badge") : null;
      var status = badge ? badge.textContent.trim().toLowerCase() : "";
      if (status === "failed" || status === "not done") {
        retryBtn.classList.remove("hidden");
        retryBtn.setAttribute("data-stage", stageKey);
      } else {
        retryBtn.classList.add("hidden");
      }
    }

    // Show drawer and backdrop
    if (backdrop) backdrop.classList.remove("hidden");
    if (drawer) {
      drawer.classList.remove("hidden");
      drawer.classList.remove("translate-x-full");
      var focusable = drawer.querySelector("button:not([disabled]), input:not([disabled]), a[href]");
      if (focusable) focusable.focus();
    }

    if (stageKey === "recipient_check" && main.getAttribute("data-recipient-confirmed") === "true") {
      preview(null, true);
    }
  }

  function closeDrawer() {
    activeDrawerStage = null;
    var drawer = document.getElementById("operation-drawer");
    var backdrop = document.getElementById("drawer-backdrop");
    if (drawer) {
      drawer.classList.add("translate-x-full");
      drawer.classList.add("hidden");
    }
    if (backdrop) backdrop.classList.add("hidden");
  }

  // Close triggers
  var closeBtn = document.getElementById("drawer-close-btn");
  if (closeBtn) closeBtn.addEventListener("click", closeDrawer);
  var backdrop = document.getElementById("drawer-backdrop");
  if (backdrop) backdrop.addEventListener("click", closeDrawer);

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") closeDrawer();
  });

  // Tile clicks and Enter key open drawer
  document.addEventListener("click", function (event) {
    var trigger = event.target.closest ? event.target.closest("[data-open-drawer]") : null;
    if (trigger) {
      var stage = trigger.getAttribute("data-open-drawer");
      if (stage) openDrawer(stage);
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Enter") {
      var target = event.target;
      if (target && target.hasAttribute && target.hasAttribute("data-open-drawer")) {
        var stage = target.getAttribute("data-open-drawer");
        if (stage) openDrawer(stage);
      }
    }
  });

  // Preset chips for "Mark not done"
  document.addEventListener("click", function (event) {
    var chip = event.target.closest ? event.target.closest("[data-preset-reason]") : null;
    if (chip) {
      var reasonInput = document.getElementById("drawer-not-done-reason");
      if (reasonInput) {
        reasonInput.value = chip.getAttribute("data-preset-reason") || "";
        reasonInput.focus();
      }
    }
  });

  async function submitDrawerNotDone(button) {
    var stage = activeDrawerStage || (button ? button.getAttribute("data-stage") : null);
    if (!stage) return;
    var reasonInput = document.getElementById("drawer-not-done-reason");
    var reason = reasonInput ? reasonInput.value.trim() : "";
    if (reason.length < 3 || reason.length > 300) {
      showToast("Please provide a reason between 3 and 300 characters.", "error");
      return;
    }
    setBusy(button, true);
    try {
      await request(base + "/operations/" + encodeURIComponent(stage) + "/not-done", {
        method: "POST",
        json: { reason: reason },
      });
      flashAndReload("Operation marked not done: " + stage + ".", "success");
    } catch (error) {
      showToast(error.message, "error");
      setBusy(button, false);
    }
  }

  async function submitDrawerRetry(button) {
    var stage = activeDrawerStage || (button ? button.getAttribute("data-stage") : null);
    if (!stage) return;
    setBusy(button, true);
    try {
      await request(base + "/operations/" + encodeURIComponent(stage) + "/retry", {
        method: "POST",
      });
      flashAndReload("Operation queued for retry: " + stage + ".", "success");
    } catch (error) {
      showToast(error.message, "error");
      setBusy(button, false);
    }
  }

  // Scan file upload (supports both file input names)
  async function handleScanUpload(event) {
    event.preventDefault();
    var input = document.getElementById("scan-file") || document.getElementById("document-file");
    var button = event.currentTarget.querySelector("button[type=submit]");
    if (!input || !input.files || input.files.length === 0) {
      showToast("Choose a PDF, PNG or JPEG file first.", "error");
      return;
    }
    var data = new FormData();
    data.append("file", input.files[0]);
    setBusy(button, true);
    try {
      var documentRecord = await request(base + "/document", {
        method: "POST",
        body: data,
      });
      flashAndReload("Scan attached: " + documentRecord.original_name + ".", "success");
    } catch (error) {
      showToast(error.message, "error");
      setBusy(button, false);
    }
  }

  var scanForm = document.getElementById("scan-upload-form") || document.getElementById("upload-form");
  if (scanForm) scanForm.addEventListener("submit", handleScanUpload);

  // Software check override
  var swForm = document.getElementById("software-override-form");
  if (swForm) {
    swForm.addEventListener("submit", async function (event) {
      event.preventDefault();
      var reasonInput = document.getElementById("sw-override-reason");
      var reason = reasonInput ? reasonInput.value.trim() : "";
      if (!reason) {
        showToast("Enter an override justification.", "error");
        return;
      }
      var submitBtn = swForm.querySelector("button[type=submit]");
      setBusy(submitBtn, true);
      try {
        await request(base + "/software-check/override", {
          method: "POST",
          json: { reason: reason },
        });
        flashAndReload("Software check overridden.", "success");
      } catch (error) {
        showToast(error.message, "error");
        setBusy(submitBtn, false);
      }
    });
  }

  // Maintenance forms submission
  document.querySelectorAll("form[data-maint-stage]").forEach(function (maintForm) {
    maintForm.addEventListener("submit", async function (event) {
      event.preventDefault();
      var stage = maintForm.getAttribute("data-maint-stage");
      var submitBtn = maintForm.querySelector("button[type=submit]");
      setBusy(submitBtn, true);
      var formData = new FormData(maintForm);
      var payload = {};
      formData.forEach(function (value, key) {
        var str = String(value).trim();
        if (str) payload[key] = str;
      });
      try {
        await request(base + "/maintenance", {
          method: "POST",
          json: payload,
        });
        await request(base + "/stages/" + encodeURIComponent(stage) + "/confirm", {
          method: "POST",
        });
        flashAndReload("Operation confirmed: " + stage + ".", "success");
      } catch (error) {
        showToast(error.message, "error");
        setBusy(submitBtn, false);
      }
    });
  });

  // Action dispatcher
  document.addEventListener("click", function (event) {
    var button = event.target.closest ? event.target.closest("[data-action]") : null;
    if (!button) return;
    var action = button.getAttribute("data-action");
    if (action === "stage-confirm" || action === "confirm-stage") confirmStage(button);
    else if (action === "confirm-recipient") confirmRecipient(button);
    else if (action === "preview-checkout" || action === "preview") preview(button);
    else if (action === "confirm-checkout" || action === "checkout") checkout(button);
    else if (action === "push-to-snipeit" || action === "push-document") pushDocument(button);
    else if (action === "mark-not-done" || action === "not-done") submitDrawerNotDone(button);
    else if (action === "retry") submitDrawerRetry(button);
    else if (action === "close-case") closeCase(button);
    else if (action === "reopen-case") reopenCase(button);
    else if (action === "cancel") cancel(button);
  });

  var searchForm = document.getElementById("recipient-search-form");
  if (searchForm) searchForm.addEventListener("submit", searchRecipients);

  if (main.getAttribute("data-recipient-confirmed") === "true") {
    preview(null, true);
  }

  showStoredFlash();
})();
