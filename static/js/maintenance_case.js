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
  document.addEventListener("click", function (event) {
    var button = event.target.closest ? event.target.closest("[data-maint-action]") : null;
    if (!button || !caseId) return;
    var action = button.getAttribute("data-maint-action");
    var result = portal.$("[data-maint-result]");
    button.disabled = true;
    portal.request("/api/maintenance/cases/" + caseId + "/" + action, { method: "POST" })
      .then(function (detail) {
        var stage = action === "set-status" ? "snipeit_status" : action === "take-back" ? "taken_back" : "ready_status";
        var operation = (detail.stages || []).find(function (item) { return item.stage === stage; });
        if (operation && (operation.status === "failed" || operation.status === "not_done")) {
          result.textContent = operation.reason || (operation.status === "not_done" ? "Not assigned" : "Failed");
          result.className = "badge badge-destructive";
          return;
        }
        result.textContent = "Done";
        result.className = "badge badge-success";
        if (action === "take-back") {
          var remove = portal.$("[data-maint-action='take-back']");
          if (remove) remove.remove();
        }
      })
      .catch(function (error) {
        result.textContent = error.message;
        result.className = "badge badge-destructive";
      })
      .then(function () { button.disabled = false; });
  });
})();
