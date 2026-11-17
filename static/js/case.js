/**
 * case.js — the case page drawers.
 *
 * Every operation tile opens a drawer. Inside, each control either performs
 * its action (with a toast and a state refresh) or is disabled with a
 * visible reason. One drawer at a time; Esc closes it.
 */
"use strict";

(function () {
  var portal = window.portal;
  var caseId = document.body.getAttribute("data-case-id") || "";
  var kind = document.body.getAttribute("data-case-kind") || "handover";

  var STAGE_LABELS = {
    device_prepared: "Device prepared",
    user_signed_in: "User signed in",
    agent_report: "Agent report",
    software_check: "Software",
    recipient_check: "Recipient",
    checkout: "Checkout",
    report_printed: "Print form",
    user_signed: "Signed paper",
    document_scanned: "Scan",
    document_pushed: "Push",
    received: "Received",
    diagnosis: "Diagnosis",
    snipeit_status: "Snipe-IT status",
    sent_out: "Sent out",
    returned: "Returned",
  };

  var PRESETS = ["Not applicable", "Device not available", "Will do later"];

  function casePath() {
    return "/api/handovers/" + caseId;
  }

  function refreshPage(message, kindOfToast) {
    if (message) portal.toast(message, kindOfToast || "success");
    window.location.reload();
  }

  function confirmOperation(operation) {
    return portal.apiJson(casePath() + "/operations/" + operation + "/confirm", {
      method: "POST",
    });
  }

  function markNotDone(operation, reason) {
    return portal.apiJson(casePath() + "/operations/" + operation + "/not-done", {
      method: "POST",
      body: JSON.stringify({ reason: reason }),
    });
  }

  function retryOperation(operation) {
    return portal.apiJson(casePath() + "/operations/" + operation + "/retry", {
      method: "POST",
    });
  }

  function maintenanceFields(payload) {
    return portal.apiJson(casePath() + "/maintenance", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  // -- drawer scaffolding -----------------------------------------------------
  function note(text) {
    var node = portal.el("p", "field-hint", text);
    return node;
  }

  function notDoneSection(operation) {
    var wrap = portal.el("div", "stack-sm notdone-section");
    var heading = portal.el("h3", "drawer-sub", "Mark as not done");
    wrap.appendChild(heading);
    var input = portal.textInput("reason", "Reason (3–300 characters)", { maxlength: 300 });
    var chips = portal.el("div", "chip-row");
    PRESETS.forEach(function (preset) {
      var chip = portal.el("button", "chip chip-plain", preset);
      chip.type = "button";
      chip.addEventListener("click", function () {
        input.value = preset;
      });
      chips.appendChild(chip);
    });
    var submit = portal.formActions("Not done", {});
    wrap.appendChild(input);
    wrap.appendChild(chips);
    submit.__primary.addEventListener("click", function (event) {
      event.preventDefault();
      var reason = input.value.trim();
      if (reason.length < 3) {
        portal.toast("Give a reason of at least 3 characters.", "error");
        return;
      }
      portal.setBusy(submit, true);
      markNotDone(operation, reason)
        .then(function () { refreshPage("Marked as not done."); })
        .catch(function (error) {
          portal.setBusy(submit, false);
          portal.toast(error.message, "error");
        });
    });
    wrap.appendChild(submit);
    return wrap;
  }

  function retrySection(operation) {
    var wrap = portal.el("div", "stack-sm");
    var heading = portal.el("h3", "drawer-sub", "Retry");
    wrap.appendChild(heading);
    var actions = portal.formActions("Retry operation", {});
    actions.__primary.addEventListener("click", function (event) {
      event.preventDefault();
      portal.setBusy(actions, true);
      retryOperation(operation)
        .then(function () { refreshPage("Operation reset to pending."); })
        .catch(function (error) {
          portal.setBusy(actions, false);
          portal.toast(error.message, "error");
        });
    });
    wrap.appendChild(actions);
    return wrap;
  }

  function drawerFor(operation, state, build) {
    var title = STAGE_LABELS[operation] || operation;
    var drawer = portal.drawerForm(title, {});
    var form = drawer.__form;
    form.setAttribute("data-op-form", operation);
    var stateChip = portal.el(
      "span",
      "badge badge-" + (state === "passed" ? "success" : state === "failed" ? "destructive" : state === "not_done" ? "warning" : "outline"),
      state === "passed" ? "Done" : state === "failed" ? "Failed" : state === "not_done" ? "Not done" : "Pending"
    );
    form.appendChild(stateChip);
    build(form, state);
    if (state !== "passed") {
      form.appendChild(notDoneSection(operation));
    } else {
      form.appendChild(retrySection(operation));
    }
    if (state === "failed" || state === "not_done") {
      form.appendChild(retrySection(operation));
    }
    return drawer;
  }

  // -- per-operation drawers ----------------------------------------------------
  function openOp(operation) {
    var tile = portal.$('[data-op-tile="' + operation + '"]');
    var state = tile ? tile.className.match(/op-tile-(\w+)/) : null;
    var status = state ? state[1] : "pending";

    switch (operation) {
      case "agent_report": return openAgentReport(status);
      case "software_check": return openSoftwareCheck(status);
      case "recipient_check": return openRecipient(status);
      case "checkout": return openCheckout(status);
      case "document_scanned": return openScan(status);
      case "document_pushed": return openPush(status);
      case "diagnosis": return openDiagnosis(status);
      case "sent_out": return openSendOut(status);
      case "returned": return openReceiveBack(status);
      case "snipeit_status": return openSnipeitStatus(status);
      default: return openSimple(operation, status);
    }
  }

  function openSimple(operation, status) {
    return drawerFor(operation, status, function (form, state) {
      if (state === "pending") {
        var actions = portal.formActions("Confirm");
        form.appendChild(note("One click records this step."));
        form.appendChild(actions);
        actions.__primary.addEventListener("click", function (event) {
          event.preventDefault();
          portal.setBusy(actions, true);
          confirmOperation(operation)
            .then(function () { refreshPage(STAGE_LABELS[operation] + " done."); })
            .catch(function (error) {
              portal.setBusy(actions, false);
              portal.toast(error.message, "error");
            });
        });
      }
    });
  }

  function openAgentReport(status) {
    return drawerFor("agent_report", status, function (form, state) {
      if (state === "pending") {
        var sync = portal.formActions("Sync now");
        form.appendChild(note("The employee's PC runs one short command; you stay here."));
        form.appendChild(sync);
        sync.__primary.addEventListener("click", function (event) {
          event.preventDefault();
          portal.closeDrawer();
          if (window.syncFlow) window.syncFlow.open({ handoverId: caseId });
          else portal.toast("Sync is not available on this page.", "error");
        });
        var printWrap = portal.disabledButton(
          "Print form",
          "Run the device check first — the printable form needs the agent report."
        );
        form.appendChild(printWrap);
      } else {
        var printButton = portal.actionButton("Print form", "btn-default");
        printButton.addEventListener("click", function () {
          fetch(casePath() + "/report", { credentials: "same-origin" })
            .then(function (res) {
              if (!res.ok) throw new Error("The agent report is not available yet.");
              return res.blob().then(function (blob) {
                var url = URL.createObjectURL(blob);
                window.open(url, "_blank");
                portal.toast("Form opened for printing.", "success");
              });
            })
            .catch(function (error) {
              portal.toast(error.message, "error");
            });
        });
        form.appendChild(printButton);
      }
    });
  }

  function openSoftwareCheck(status) {
    return drawerFor("software_check", status, function (form, state) {
      if (state === "pending") {
        form.appendChild(note("The software list is evaluated from the agent report."));
        var sync = portal.formActions("Sync now");
        form.appendChild(sync);
        sync.__primary.addEventListener("click", function (event) {
          event.preventDefault();
          portal.closeDrawer();
          if (window.syncFlow) window.syncFlow.open({ handoverId: caseId });
          else portal.toast("Sync is not available on this page.", "error");
        });
      } else if (state === "failed") {
        var heading = portal.el("h3", "drawer-sub", "Override");
        form.appendChild(heading);
        var input = portal.textInput("reason", "Why override? (10–500 characters)", { maxlength: 500 });
        var actions = portal.formActions("Override");
        actions.__primary.addEventListener("click", function (event) {
          event.preventDefault();
          var reason = input.value.trim();
          if (reason.length < 10) {
            portal.toast("Give a justification of at least 10 characters.", "error");
            return;
          }
          portal.setBusy(actions, true);
          portal.apiJson(casePath() + "/software-check/override", {
            method: "POST",
            body: JSON.stringify({ reason: reason }),
          })
            .then(function () { refreshPage("Software check overridden."); })
            .catch(function (error) {
              portal.setBusy(actions, false);
              portal.toast(error.message, "error");
            });
        });
        form.appendChild(input);
        form.appendChild(actions);
      } else if (state === "not_done") {
        var reevaluate = portal.formActions("Re-evaluate");
        form.appendChild(reevaluate);
        reevaluate.__primary.addEventListener("click", function (event) {
          event.preventDefault();
          portal.setBusy(reevaluate, true);
          portal.apiJson(casePath() + "/software-check/reevaluate", { method: "POST" })
            .then(function () { refreshPage("Software checks re-evaluated."); })
            .catch(function (error) {
              portal.setBusy(reevaluate, false);
              portal.toast(error.message, "error");
            });
        });
      }
    });
  }

  function openRecipient(status) {
    return drawerFor("recipient_check", status, function (form, state) {
      if (state === "passed") return;
      var input = portal.textInput("q", "Search name or email", { maxlength: 200 });
      var searchRow = portal.buttonRow([portal.actionButton("Search")]);
      var results = portal.el("div", "stack-sm recipient-results");
      var notFound = portal.formActions("No Snipe-IT user", { secondaryLabel: "" });
      form.appendChild(portal.field("Find the recipient in Snipe-IT", input));
      form.appendChild(searchRow);
      form.appendChild(results);
      searchRow.querySelector("button").addEventListener("click", function () {
        var q = input.value.trim();
        if (!q) {
          portal.toast("Type a name or email first.", "error");
          return;
        }
        results.textContent = "";
        var searching = portal.el("p", "muted", "Searching…");
        results.appendChild(searching);
        portal.request(casePath() + "/recipient/search?q=" + encodeURIComponent(q), { method: "POST" })
          .then(function (result) {
            results.textContent = "";
            var users = result.results || [];
            if (!users.length) {
              results.appendChild(portal.el("p", "muted", "No Snipe-IT user found."));
              return;
            }
            users.slice(0, 5).forEach(function (user) {
              var row = portal.el("div", "recipient-row");
              var label = portal.el("span", "", (user.name || "") + " " + (user.email || ""));
              var pick = portal.actionButton("Confirm", "btn-default btn-sm");
              pick.addEventListener("click", function () {
                portal.setBusy(pick.parentNode, true);
                portal.apiJson(casePath() + "/recipient/confirm", {
                  method: "POST",
                  body: JSON.stringify({ snipeit_user_id: user.id }),
                })
                  .then(function () { refreshPage("Recipient confirmed."); })
                  .catch(function (error) {
                    portal.setBusy(pick.parentNode, false);
                    portal.toast(error.message, "error");
                  });
              });
              row.appendChild(label);
              row.appendChild(pick);
              results.appendChild(row);
            });
          })
          .catch(function (error) {
            results.textContent = "";
            results.appendChild(portal.el("p", "muted", error.message));
            portal.toast(error.message, "error");
          });
      });
      notFound.__primary.addEventListener("click", function (event) {
        event.preventDefault();
        portal.setBusy(notFound, true);
        portal.apiJson(casePath() + "/recipient/confirm", {
          method: "POST",
          body: JSON.stringify({ not_found: true }),
        })
          .then(function () { refreshPage("Recipient recorded as not found."); })
          .catch(function (error) {
            portal.setBusy(notFound, false);
            portal.toast(error.message, "error");
          });
      });
      form.appendChild(notFound);
    });
  }

  function openCheckout(status) {
    return drawerFor("checkout", status, function (form, state) {
      if (state === "pending") {
        var confirmed = document.body.getAttribute("data-recipient-confirmed") === "true";
        if (!confirmed) {
          form.appendChild(portal.disabledButton(
            "Checkout",
            "Confirm the recipient first — checkout assigns the device to them."
          ));
          return;
        }
        var actions = portal.formActions("Checkout in Snipe-IT");
        form.appendChild(actions);
        actions.__primary.addEventListener("click", function (event) {
          event.preventDefault();
          portal.setBusy(actions, true);
          portal.request(casePath() + "/checkout", { method: "POST" })
            .then(function () { refreshPage("Checkout done in Snipe-IT."); })
            .catch(function (error) {
              portal.setBusy(actions, false);
              portal.toast(error.message, "error");
            });
        });
      }
    });
  }

  function openScan(status) {
    return drawerFor("document_scanned", status, function (form, state) {
      if (state === "passed") return;
      var input = portal.el("input", "input");
      input.type = "file";
      input.name = "file";
      input.accept = ".pdf,.png,.jpeg,.jpg";
      form.appendChild(portal.field("Signed paper scan", input));
      var actions = portal.formActions("Attach scan");
      form.appendChild(actions);
      form.addEventListener("submit", function (event) {
        event.preventDefault();
        if (!input.files || !input.files.length) {
          portal.toast("Choose a PDF, PNG or JPEG file first.", "error");
          return;
        }
        var data = new FormData();
        data.append("file", input.files[0]);
        portal.setBusy(actions, true);
        portal.request(casePath() + "/document", { method: "POST", body: data })
          .then(function () { refreshPage("Scan attached."); })
          .catch(function (error) {
            portal.setBusy(actions, false);
            portal.toast(error.message, "error");
          });
      });
    });
  }

  function openPush(status) {
    return drawerFor("document_pushed", status, function (form, state) {
      if (state === "pending") {
        var hasDocument = document.body.getAttribute("data-has-document") === "true";
        if (!hasDocument) {
          form.appendChild(portal.disabledButton(
            "Push to Snipe-IT",
            "Attach the signed scan first — there is no document to push."
          ));
          return;
        }
        var actions = portal.formActions("Push to Snipe-IT");
        form.appendChild(actions);
        actions.__primary.addEventListener("click", function (event) {
          event.preventDefault();
          portal.setBusy(actions, true);
          portal.request(casePath() + "/document/push", { method: "POST" })
            .then(function () { refreshPage("Pushed to Snipe-IT."); })
            .catch(function (error) {
              portal.setBusy(actions, false);
              portal.toast(error.message, "error");
            });
        });
      }
    });
  }

  function openDiagnosis(status) {
    return drawerFor("diagnosis", status, function (form, state) {
      if (state === "pending") {
        var category = portal.selectInput("diagnosis_category", []);
        var noteInput = portal.textInput("diagnosis_note", "Note (optional)", { maxlength: 300 });
        form.appendChild(portal.field("Category", category));
        form.appendChild(portal.field("Note", noteInput));
        var actions = portal.formActions("Record diagnosis");
        form.appendChild(actions);
        portal.request("/api/handovers/maintenance/categories")
          .then(function (cats) {
            while (category.firstChild) category.removeChild(category.firstChild);
            portal.selectInput("diagnosis_category", (cats || []).map(function (c) { return c.name; }))
              .querySelectorAll("option").forEach(function (o) { category.appendChild(o); });
          }).catch(function () { /* the free-text still works */ });
        actions.__primary.addEventListener("click", function (event) {
          event.preventDefault();
          portal.setBusy(actions, true);
          var payload = {};
          if (category.value) payload.diagnosis_category = category.value;
          if (noteInput.value.trim()) payload.diagnosis_note = noteInput.value.trim();
          maintenanceFields(payload)
            .then(function () { return confirmOperation("diagnosis"); })
            .then(function () { refreshPage("Diagnosis recorded."); })
            .catch(function (error) {
              portal.setBusy(actions, false);
              portal.toast(error.message, "error");
            });
        });
      }
    });
  }

  function openSnipeitStatus(status) {
    return drawerFor("snipeit_status", status, function (form, state) {
      if (state === "pending") {
        var actions = portal.formActions("Mark in Snipe-IT");
        form.appendChild(note("Sets the Snipe-IT status label for this state. The label names come from the environment."));
        form.appendChild(actions);
        actions.__primary.addEventListener("click", function (event) {
          event.preventDefault();
          portal.setBusy(actions, true);
          portal.apiJson(casePath() + "/maintenance/status-label", { method: "POST" })
            .then(function (res) {
              if (res.updated === true) {
                return confirmOperation("snipeit_status").then(function () {
                  refreshPage("Snipe-IT status updated.");
                });
              }
              return markNotDone(
                "snipeit_status",
                "Snipe-IT status not updated (label not configured or Snipe-IT unavailable)"
              ).then(function () { refreshPage("Snipe-IT status not updated.", "info"); });
            })
            .catch(function (error) {
              portal.setBusy(actions, false);
              portal.toast(error.message, "error");
            });
        });
      }
    });
  }

  function openSendOut(status) {
    return drawerFor("sent_out", status, function (form, state) {
      if (state !== "pending") return;
      var vendor = portal.selectInput("vendor", []);
      var reference = portal.textInput("reference", "Reference number", { maxlength: 100 });
      var expected = portal.textInput("expected_return_date", "", { type: "date" });
      var accessories = portal.textInput("accessories", "Accessories sent (optional)", { maxlength: 200 });
      var condition = portal.textInput("condition_notes", "Condition at send (optional)", { maxlength: 200 });
      form.appendChild(portal.field("Vendor", vendor));
      form.appendChild(portal.field("Reference", reference));
      form.appendChild(portal.field("Expected return", expected));
      form.appendChild(portal.field("Accessories", accessories));
      form.appendChild(portal.field("Condition", condition));
      var actions = portal.formActions("Send");
      form.appendChild(actions);
      portal.request("/api/handovers/maintenance/vendors").then(function (vendors) {
        while (vendor.firstChild) vendor.removeChild(vendor.firstChild);
        portal.selectInput("vendor", (vendors || []).filter(function (v) { return v.active; }).map(function (v) { return v.name; }))
          .querySelectorAll("option").forEach(function (o) { vendor.appendChild(o); });
      }).catch(function () { /* select stays empty; the step still works */ });
      actions.__primary.addEventListener("click", function (event) {
        event.preventDefault();
        portal.setBusy(actions, true);
        var payload = {};
        ["vendor", "reference", "expected_return_date", "accessories", "condition_notes"].forEach(function (key) {
          var control = form.querySelector('[name="' + key + '"]');
          if (control && control.value.trim()) payload[key] = control.value.trim();
        });
        maintenanceFields(payload)
          .then(function () { return confirmOperation("sent_out"); })
          .then(function () {
            return portal.apiJson(casePath() + "/maintenance/status-label", { method: "POST" })
              .then(function (res) {
                if (res.updated !== true) {
                  portal.toast("Snipe-IT status not updated", "info");
                  return markNotDone(
                    "snipeit_status",
                    "Snipe-IT status not updated (label not configured or Snipe-IT unavailable)"
                  );
                }
                return confirmOperation("snipeit_status").catch(function () { /* optional */ });
              })
              .catch(function () { /* optional */ });
          })
          .then(function () { refreshPage("Sent to vendor."); })
          .catch(function (error) {
            portal.setBusy(actions, false);
            portal.toast(error.message, "error");
          });
      });
    });
  }

  function openReceiveBack(status) {
    return drawerFor("returned", status, function (form, state) {
      if (state !== "pending") return;
      var outcome = portal.selectInput("outcome", [
        { value: "repaired", label: "Repaired" },
        { value: "replaced", label: "Replaced" },
        { value: "unrepairable", label: "Unrepairable" },
      ]);
      var condition = portal.textInput("condition_notes", "Condition at return (optional)", { maxlength: 200 });
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
      var actions = portal.formActions("Receive");
      form.appendChild(actions);
      actions.__primary.addEventListener("click", function (event) {
        event.preventDefault();
        portal.setBusy(actions, true);
        var payload = {};
        ["outcome", "condition_notes", "cost", "warranty"].forEach(function (key) {
          var control = form.querySelector('[name="' + key + '"]');
          if (control && control.value.trim()) payload[key] = control.value.trim();
        });
        maintenanceFields(payload)
          .then(function () { return confirmOperation("returned"); })
          .then(function () { refreshPage("Device received back."); })
          .catch(function (error) {
            portal.setBusy(actions, false);
            portal.toast(error.message, "error");
          });
      });
    });
  }

  // -- cancel case (destructive: ask once) ---------------------------------------
  function openCancel() {
    var drawer = portal.drawerForm("Cancel case?", {});
    var form = drawer.__form;
    form.appendChild(note("The case is closed as cancelled. This cannot be undone."));
    var actions = portal.formActions("Yes, cancel", { secondaryLabel: "Keep case" });
    form.appendChild(actions);
    actions.__primary.addEventListener("click", function (event) {
      event.preventDefault();
      portal.setBusy(actions, true);
      portal.apiJson(casePath() + "/cancel", { method: "POST" })
        .then(function () { refreshPage("Case cancelled."); })
        .catch(function (error) {
          portal.setBusy(actions, false);
          portal.toast(error.message, "error");
        });
    });
    if (actions.__secondary) {
      actions.__secondary.addEventListener("click", function () {
        portal.closeDrawer();
      });
    }
  }

  // -- sync drawer ---------------------------------------------------------------
  function openSync() {
    if (window.syncFlow) {
      window.syncFlow.open({ handoverId: caseId });
    } else {
      portal.toast("Sync is not available.", "error");
    }
  }

  function boot() {
    portal.$all("[data-op-tile]").forEach(function (tile) {
      tile.addEventListener("click", function () {
        openOp(tile.getAttribute("data-op-tile"));
      });
    });
    var cancel = portal.$("[data-case-cancel]");
    if (cancel) cancel.addEventListener("click", openCancel);
    var sync = portal.$("[data-sync-open]");
    if (sync) sync.addEventListener("click", openSync);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
