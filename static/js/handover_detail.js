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
    if (!query) {
      showToast("Enter a name, username or email to search.", "error");
      return;
    }
    setBusy(button, true);
    try {
      var result = await request(
        base + "/recipient/search?q=" + encodeURIComponent(query),
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
      await request(base + "/recipient/confirm", {
        method: "POST",
        json: { snipeit_user_id: Number(checked.value) },
      });
      flashAndReload("Recipient confirmed.", "success");
    } catch (error) {
      showToast(error.message, "error");
      setBusy(button, false);
    }
  }

  async function recipientNotFound(button) {
    var proceed = window.confirm(
      "Mark the recipient as not in Snipe-IT? Stage 4 will be blocked until the recipient is confirmed."
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

  async function preview(button) {
    setBusy(button, true);
    try {
      var result = await request(base + "/preview");
      renderPreview(result);
      showToast("Preview loaded; no Snipe-IT writes were made.", "success");
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
  document.addEventListener("click", function (event) {
    var button = event.target.closest ? event.target.closest("[data-action]") : null;
    if (!button) return;
    var action = button.getAttribute("data-action");
    if (action === "confirm-stage") confirmStage(button);
    else if (action === "focus-recipient") {
      var query = document.getElementById("recipient-query");
      if (query) query.focus();
    } else if (action === "focus-upload") {
      var file = document.getElementById("document-file");
      if (file) file.focus();
    } else if (action === "confirm-recipient") confirmRecipient(button);
    else if (action === "recipient-not-found") recipientNotFound(button);
    else if (action === "preview") preview(button);
    else if (action === "checkout") checkout(button);
    else if (action === "checkin") checkin(button);
    else if (action === "push-document") pushDocument(button);
    else if (action === "cancel") cancel(button);
  });

  var searchForm = document.getElementById("recipient-search-form");
  if (searchForm) searchForm.addEventListener("submit", searchRecipients);

  var uploadForm = document.getElementById("upload-form");
  if (uploadForm) uploadForm.addEventListener("submit", upload);

  showStoredFlash();
})();
