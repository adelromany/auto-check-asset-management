/**
 * New-case registration.
 *
 * The server renders the form; this module posts it to the JSON API, uses the
 * per-session CSRF token from `/api/me`, and warns when the serial already has
 * an open case. All text is inserted with textContent.
 */
"use strict";

(function () {
  var form = document.getElementById("new-case-form");
  if (!form) return;

  var serialInput = document.getElementById("new-serial");
  var ticketInput = document.getElementById("new-ticket");
  var errorBox = document.getElementById("new-case-error");
  var errorText = document.getElementById("new-case-error-text");
  var activeBox = document.getElementById("active-case");
  var activeText = document.getElementById("active-case-text");
  var activeLink = document.getElementById("active-case-link");
  var matchBox = document.getElementById("snipeit-match");

  var handoverLabel = document.getElementById("label-kind-handover");
  var maintenanceLabel = document.getElementById("label-kind-maintenance");

  function updateKindVisuals(selected) {
    if (handoverLabel) {
      if (selected === "handover") {
        handoverLabel.className = "flex flex-col items-center justify-center gap-1.5 p-3 rounded-xl border-2 border-primary bg-primary/5 cursor-pointer text-xs font-semibold text-foreground transition-all";
      } else {
        handoverLabel.className = "flex flex-col items-center justify-center gap-1.5 p-3 rounded-xl border-2 border-border hover:border-primary/50 cursor-pointer text-xs font-semibold text-muted-foreground transition-all";
      }
    }
    if (maintenanceLabel) {
      if (selected === "maintenance") {
        maintenanceLabel.className = "flex flex-col items-center justify-center gap-1.5 p-3 rounded-xl border-2 border-primary bg-primary/5 cursor-pointer text-xs font-semibold text-foreground transition-all";
      } else {
        maintenanceLabel.className = "flex flex-col items-center justify-center gap-1.5 p-3 rounded-xl border-2 border-border hover:border-primary/50 cursor-pointer text-xs font-semibold text-muted-foreground transition-all";
      }
    }
  }

  document.querySelectorAll('input[name="kind"]').forEach(function (radio) {
    radio.addEventListener("change", function () {
      updateKindVisuals(radio.value);
    });
  });

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
    var init = {
      method: options.method || "GET",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    };
    if (init.method !== "GET" && window.HandoverShell) {
      var token = await window.HandoverShell.csrfToken();
      if (token) init.headers["X-CSRF-Token"] = token;
    }
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
      throw new Error(detailText(body) || "Request failed (" + response.status + ").");
    }
    return body;
  }

  function hide(element) {
    if (element) element.classList.add("hidden");
  }

  function showActive(active) {
    if (!activeBox || !activeText || !activeLink) return;
    if (!active) {
      hide(activeBox);
      return;
    }
    activeText.textContent =
      "Already open: " + (active.kind || "case") + " by " + (active.engineer_name || active.engineer_email || "engineer");
    activeLink.href = "/cases/" + encodeURIComponent(active.id);
    activeBox.classList.remove("hidden");
  }

  async function checkActive() {
    var serial = serialInput.value.trim();
    if (!serial) {
      showActive(null);
      if (matchBox) hide(matchBox);
      return;
    }
    try {
      var active = await request(
        "/api/handovers/active?serial=" + encodeURIComponent(serial)
      );
      showActive(active);
    } catch (error) {
      showActive(null);
    }

    // Lookup from Snipe-IT
    try {
      var device = await request("/api/snipeit/device?serial=" + encodeURIComponent(serial));
      if (device && device.found && matchBox) {
        matchBox.replaceChildren();
        if (device.model) {
          var chip1 = document.createElement("span");
          chip1.className = "badge bg-muted/60 text-[10px]";
          chip1.textContent = device.model;
          matchBox.appendChild(chip1);
        }
        if (device.asset_tag) {
          var chip2 = document.createElement("span");
          chip2.className = "badge bg-muted/60 text-[10px]";
          chip2.textContent = "Tag: " + device.asset_tag;
          matchBox.appendChild(chip2);
        }
        matchBox.classList.remove("hidden");
      }
    } catch (err) {
      /* Snipe-IT failure never blocks registration */
    }
  }

  if (serialInput) serialInput.addEventListener("blur", checkActive);

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    var button = form.querySelector("button[type=submit]");
    var serial = serialInput.value.trim();
    var ticket = ticketInput.value.trim();
    var kindRadio = form.querySelector('input[name="kind"]:checked');
    var kind = kindRadio ? kindRadio.value : "handover";

    hide(errorBox);
    if (!serial) {
      errorText.textContent = "A device serial is required.";
      errorBox.classList.remove("hidden");
      serialInput.focus();
      return;
    }

    if (button) button.disabled = true;
    try {
      var created = await request("/api/handovers", {
        method: "POST",
        json: {
          device_serial: serial,
          ticket_ref: ticket || null,
          kind: kind,
        },
      });
      window.location.assign("/cases/" + encodeURIComponent(created.id));
    } catch (error) {
      errorText.textContent = error.message;
      errorBox.classList.remove("hidden");
      if (button) button.disabled = false;
    }
  });
})();
