/* Compact maintenance case actions. */
"use strict";
(function () {
  var portal = window.portal;
  if (!portal) return;
  var caseId = document.body.getAttribute("data-case-id");
  var base = "/api/handovers/" + caseId;
  var scanInput = portal.$("[data-maint-scan]");
  if (scanInput) scanInput.addEventListener("change", function () {
    var file = scanInput.files && scanInput.files[0];
    if (!file) return;
    var status = portal.$("[data-maint-document-status]");
    var list = portal.$("[data-maint-document-list]");
    var data = new FormData();
    data.append("file", file);
    status.textContent = "Uploading " + file.name + "...";
    portal.request(base + "/document", { method: "POST", body: data })
      .then(function (document) {
        status.textContent = "Scan uploaded.";
        list.textContent = "";
        var link = portal.el("a", "link-quiet", "Download " + document.original_name);
        link.href = base + "/document";
        list.appendChild(link);
        scanInput.value = "";
      })
      .catch(function (error) { status.textContent = error.message; });
  });
  function stage(detail, name) {
    return (detail.stages || []).find(function (item) { return item.stage === name; }) || {};
  }

  function perform(action) {
    var result = portal.$("[data-maint-result]");
    result.textContent = "";
    return portal.request("/api/maintenance/cases/" + caseId + "/" + action, { method: "POST" })
      .then(function (detail) {
        renderActions(detail);
        var name = action === "set-status" ? "snipeit_status" : action === "take-back" ? "taken_back" : "ready_status";
        var operation = stage(detail, name);
        if (operation.status === "failed" || operation.status === "not_done") {
          result.textContent = operation.reason || "Failed";
          throw new Error(result.textContent);
        }
      })
      .catch(function (error) { result.textContent = error.message; });
  }

  function renderActions(detail) {
    var status = stage(detail, "snipeit_status");
    var taken = stage(detail, "taken_back");
    var ready = stage(detail, "ready_status");
    var holder = detail.device_holder_name || detail.recipient_snipeit_name;
    var definitions = {
      "set-status": {
        applicable: status.status !== "passed", done: status.status === "passed",
        doneLabel: "Maintenance", label: status.status === "failed" ? "Retry" : "Set Maintenance",
        onClick: function () { return perform("set-status"); },
      },
      "take-back": {
        applicable: !!holder && taken.status !== "passed", done: taken.status === "passed",
        doneLabel: "Checked in", label: taken.status === "failed" ? "Retry" : "Remove from user",
        onClick: function () { return perform("take-back"); },
      },
      "ready-status": {
        applicable: ready.status === "failed" || ready.status === "not_done",
        done: ready.status === "passed", doneLabel: "Ready to deploy", label: "Retry status",
        onClick: function () { return perform("ready-status"); },
      },
    };
    Object.keys(definitions).forEach(function (action) {
      portal.actionSlot(portal.$("[data-maint-action-slot='" + action + "']"), definitions[action]);
    });
    var menuHost = portal.$("[data-case-menu]");
    menuHost.textContent = "";
    menuHost.appendChild(portal.caseMenu(detail.id, detail.status, detail.maintenance_state));
  }

  portal.request(base).then(renderActions).catch(function (error) {
    portal.$("[data-maint-result]").textContent = error.message;
  });
})();
