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
      "Serial " + active.device_serial + " already has an open case. Finish or close it first.";
    activeLink.href = "/cases/" + encodeURIComponent(active.id);
    activeBox.classList.remove("hidden");
  }

  async function checkActive() {
    var serial = serialInput.value.trim();
    if (!serial) {
      showActive(null);
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
  }

  if (serialInput) serialInput.addEventListener("blur", checkActive);

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    var button = form.querySelector("button[type=submit]");
    var serial = serialInput.value.trim();
    var ticket = ticketInput.value.trim();

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
          kind: "handover",
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
