/**
 * Handovers dashboard: filters, KPI tiles and the table.
 *
 * The page is server-rendered first; this module only refreshes the same
 * data when a filter changes. Every value is inserted with textContent or
 * createElement — never innerHTML with data.
 */
"use strict";

(function () {
  var STATUS_LABELS = {
    draft: "Draft",
    in_progress: "In progress",
    stalled: "Stalled",
    completed: "Completed",
    cancelled: "Cancelled",
  };

  var STATUS_BADGES = {
    draft: "badge-secondary",
    in_progress: "badge-default",
    stalled: "badge-warning",
    completed: "badge-success",
    cancelled: "badge-outline",
  };

  var STAGE_LABELS = {
    device_prepared: "Device prepared",
    user_signed_in: "User signed in",
    agent_report: "Agent report",
    recipient_check: "Recipient check",
    checkout: "Checkout",
    report_printed: "Report printed",
    user_signed: "User signed",
    document_scanned: "Scan uploaded",
    document_pushed: "Pushed to Snipe-IT",
  };

  var form = document.getElementById("filter-form");
  var preset = document.getElementById("range-preset");
  var fromInput = document.getElementById("filter-from");
  var toInput = document.getElementById("filter-to");
  var rowsBody = document.getElementById("handover-rows");
  var alertBox = document.getElementById("dashboard-alert");
  var alertText = document.getElementById("dashboard-alert-text");
  var filterSummary = document.getElementById("filter-summary");
  var newForm = document.getElementById("new-handover-form");

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

  function showAlert(message) {
    if (!alertBox || !alertText) return;
    alertText.textContent = message;
    alertBox.classList.remove("hidden");
  }

  function hideAlert() {
    if (alertBox) alertBox.classList.add("hidden");
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

  async function api(path, options) {
    options = options || {};
    var init = {
      method: options.method || "GET",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    };
    if (options.json !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.json);
    }
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

  // -- dates ------------------------------------------------------------
  function isoDate(date) {
    var year = date.getFullYear();
    var month = String(date.getMonth() + 1).padStart(2, "0");
    var day = String(date.getDate()).padStart(2, "0");
    return year + "-" + month + "-" + day;
  }

  function startOfWeek(now) {
    var date = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    var offset = (date.getDay() + 6) % 7;
    date.setDate(date.getDate() - offset);
    return date;
  }

  function rangeFor(name) {
    var now = new Date();
    var today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    if (name === "day") return { from: isoDate(today), to: isoDate(today) };
    if (name === "week") {
      return { from: isoDate(startOfWeek(now)), to: isoDate(today) };
    }
    if (name === "month") {
      return {
        from: isoDate(new Date(now.getFullYear(), now.getMonth(), 1)),
        to: isoDate(today),
      };
    }
    if (name === "year") {
      return {
        from: isoDate(new Date(now.getFullYear(), 0, 1)),
        to: isoDate(today),
      };
    }
    return { from: "", to: "" };
  }

  function syncDateInputs() {
    var range = rangeFor(preset.value);
    fromInput.value = range.from;
    toInput.value = range.to;
  }

  function queryString(values) {
    var params = new URLSearchParams();
    Object.keys(values).forEach(function (key) {
      if (values[key]) params.set(key, values[key]);
    });
    var text = params.toString();
    return text ? "?" + text : "";
  }

  // -- rendering --------------------------------------------------------
  function statusBadge(status) {
    var badge = document.createElement("span");
    badge.className = "badge " + (STATUS_BADGES[status] || "badge-secondary");
    badge.textContent = STATUS_LABELS[status] || status;
    return badge;
  }

  function progressCell(stages) {
    var wrap = document.createElement("span");
    wrap.className = "inline-flex items-center gap-2";

    var dots = document.createElement("span");
    dots.className = "stage-dots";
    dots.setAttribute("aria-hidden", "true");
    var passed = 0;
    stages.forEach(function (item) {
      if (item.status === "passed") passed += 1;
      var dot = document.createElement("span");
      dot.className = "stage-dot stage-dot-" + item.status;
      dot.title = (STAGE_LABELS[item.stage] || item.stage) + ": " + item.status;
      dots.appendChild(dot);
    });

    var count = document.createElement("span");
    count.className = "text-xs tabular-nums text-muted-foreground";
    count.textContent = passed + "/" + stages.length;

    wrap.appendChild(dots);
    wrap.appendChild(count);
    return wrap;
  }

  function missingText(item) {
    if (item.handover.status === "cancelled") return "Cancelled";
    if (!item.missing_steps || item.missing_steps.length === 0) return "Complete";
    return item.missing_steps[0].hint;
  }

  function rowFor(item) {
    var row = document.createElement("tr");
    row.className = "table-row";

    var statusCell = document.createElement("td");
    statusCell.className = "table-cell";
    statusCell.appendChild(statusBadge(item.handover.status));
    row.appendChild(statusCell);

    var serialCell = document.createElement("td");
    serialCell.className = "table-cell";
    var link = document.createElement("a");
    link.className = "font-mono text-xs underline-offset-4 hover:underline";
    link.href = "/handovers/" + item.handover.id;
    link.setAttribute("dir", "ltr");
    link.textContent = item.handover.device_serial;
    serialCell.appendChild(link);
    row.appendChild(serialCell);

    var recipientCell = document.createElement("td");
    recipientCell.className = "table-cell";
    recipientCell.textContent =
      item.handover.recipient_snipeit_username ||
      item.handover.recipient_reported_username ||
      "—";
    row.appendChild(recipientCell);

    var engineerCell = document.createElement("td");
    engineerCell.className = "table-cell text-xs text-muted-foreground";
    engineerCell.textContent = item.handover.engineer_email;
    row.appendChild(engineerCell);

    var progress = document.createElement("td");
    progress.className = "table-cell";
    progress.appendChild(progressCell(item.stages || []));
    row.appendChild(progress);

    var missing = document.createElement("td");
    missing.className = "table-cell text-xs";
    missing.textContent = missingText(item);
    row.appendChild(missing);

    return row;
  }

  function singleRow(text, extraClass) {
    var row = document.createElement("tr");
    var cell = document.createElement("td");
    cell.colSpan = 6;
    cell.className =
      "table-cell py-10 text-center text-sm text-muted-foreground" +
      (extraClass ? " " + extraClass : "");
    cell.textContent = text;
    row.appendChild(cell);
    return row;
  }

  function renderLoading() {
    var row = document.createElement("tr");
    var cell = document.createElement("td");
    cell.colSpan = 6;
    cell.className = "table-cell py-10";
    var skeleton = document.createElement("div");
    skeleton.className = "skeleton mx-auto h-4 w-40";
    cell.appendChild(skeleton);
    row.appendChild(cell);
    rowsBody.replaceChildren(row);
  }

  function renderRows(items) {
    if (!items.length) {
      rowsBody.replaceChildren(singleRow("No handovers match these filters."));
      return;
    }
    var fragment = document.createDocumentFragment();
    items.forEach(function (item) {
      fragment.appendChild(rowFor(item));
    });
    rowsBody.replaceChildren(fragment);
  }

  function updateKpis(summary) {
    var completed = document.getElementById("kpi-completed");
    var inProgress = document.getElementById("kpi-in-progress");
    var stalled = document.getElementById("kpi-stalled");
    var total = document.getElementById("kpi-total");
    if (completed) completed.textContent = summary.completed;
    if (inProgress) inProgress.textContent = summary.by_status.in_progress || 0;
    if (stalled) stalled.textContent = summary.by_status.stalled || 0;
    if (total) total.textContent = summary.total;
  }

  // -- loading ----------------------------------------------------------
  async function load() {
    var status = document.getElementById("filter-status").value;
    var engineer = document.getElementById("filter-engineer").value.trim();
    var from = fromInput.value;
    var to = toInput.value;

    if (from && to && from > to) {
      showToast("The start date must be before the end date.", "error");
      return;
    }

    hideAlert();
    renderLoading();
    try {
      var range = queryString({ from: from, to: to });
      var rowsQuery = queryString({
        status: status,
        engineer: engineer,
        from: from,
        to: to,
        page_size: "100",
      });
      var results = await Promise.all([
        api("/api/dashboard/handovers/summary" + range),
        api("/api/dashboard/handovers" + rowsQuery),
      ]);
      updateKpis(results[0]);
      renderRows(results[1].items);
      if (filterSummary) {
        filterSummary.textContent =
          "Showing " +
          results[1].total +
          " handover" +
          (results[1].total === 1 ? "" : "s") +
          ".";
      }
    } catch (error) {
      renderRows([]);
      showAlert(error.message);
      showToast(error.message, "error");
    }
  }

  // -- events -----------------------------------------------------------
  if (form) {
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      load();
    });
  }

  if (preset) {
    preset.addEventListener("change", function () {
      if (preset.value !== "custom") {
        syncDateInputs();
        load();
      }
    });
  }

  var reset = document.getElementById("filter-reset");
  if (reset) {
    reset.addEventListener("click", function (event) {
      event.preventDefault();
      form.reset();
      fromInput.value = "";
      toInput.value = "";
      load();
    });
  }

  if (newForm) {
    newForm.addEventListener("submit", async function (event) {
      event.preventDefault();
      var button = newForm.querySelector("button[type=submit]");
      var serial = document.getElementById("new-serial").value.trim();
      var ticket = document.getElementById("new-ticket").value.trim();
      if (!serial) {
        showToast("A device serial is required.", "error");
        return;
      }
      if (button) button.disabled = true;
      try {
        var created = await api("/api/handovers", {
          method: "POST",
          json: { device_serial: serial, ticket_ref: ticket || null },
        });
        showToast("Handover created.", "success");
        window.location.assign("/handovers/" + created.id);
      } catch (error) {
        showToast(error.message, "error");
        if (button) button.disabled = false;
      }
    });
  }
})();
