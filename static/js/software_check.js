"use strict";

(function () {
  var main = document.querySelector("main[data-handover-id]");
  if (!main) return;
  var base = "/api/handovers/" + encodeURIComponent(main.getAttribute("data-handover-id"));
  var shell = window.HandoverShell;

  async function post(path, body) {
    var headers = { Accept: "application/json", "Content-Type": "application/json" };
    if (shell) {
      var token = await shell.csrfToken();
      if (token) headers["X-CSRF-Token"] = token;
    }
    var response = await fetch(base + path, {
      method: "POST", credentials: "same-origin", headers: headers,
      body: JSON.stringify(body || {}),
    });
    var data = null;
    try { data = await response.json(); } catch (error) { /* response has no JSON */ }
    if (!response.ok) {
      var message = data && data.detail;
      if (Array.isArray(message)) message = message.map(function (item) { return item.msg || String(item); }).join("; ");
      throw new Error(typeof message === "string" ? message : "Software check request failed.");
    }
    return data;
  }

  function toast(message, error) {
    var stack = document.getElementById("toast-stack");
    if (!stack) { window.location.reload(); return; }
    var item = document.createElement("div");
    item.className = "toast " + (error ? "toast-error" : "toast-success");
    item.setAttribute("role", error ? "alert" : "status");
    item.textContent = message;
    stack.appendChild(item);
    window.setTimeout(function () { item.remove(); }, 6000);
  }

  document.querySelectorAll("[data-software-override]").forEach(function (form) {
    form.addEventListener("submit", async function (event) {
      event.preventDefault();
      var textarea = form.elements.reason;
      var reason = textarea.value.trim();
      textarea.setCustomValidity(reason.length < 10 || reason.length > 500 ? "Enter 10–500 non-space characters." : "");
      if (!form.reportValidity()) return;
      if (!window.confirm("Skip the failed software check? This records your reason in the audit trail.")) return;
      var button = form.querySelector("button[type=submit]");
      button.disabled = true;
      try {
        await post("/software-check/override", { reason: reason });
        window.location.reload();
      } catch (error) {
        toast(error.message, true);
        button.disabled = false;
      }
    });
  });

  document.querySelectorAll('[data-action="reevaluate-software"]').forEach(function (button) {
    button.addEventListener("click", async function () {
      button.disabled = true;
      try {
        await post("/software-check/reevaluate");
        window.location.reload();
      } catch (error) {
        toast(error.message, true);
        button.disabled = false;
      }
    });
  });
})();
