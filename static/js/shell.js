/**
 * Shared page shell: signed-in identity, header clock and the CSRF token.
 *
 * One responsibility, no data rendering: every value is inserted with
 * textContent so the page stays safe under Jinja/CSP rules.
 */
"use strict";

(function () {
  function setText(id, text) {
    var element = document.getElementById(id);
    if (element) element.textContent = text;
  }

  var csrf = "";

  var mePromise = fetch("/api/me", {
    headers: { Accept: "application/json" },
    credentials: "same-origin",
  })
    .then(function (response) {
      csrf = response.headers.get("X-CSRF-Token") || "";
      return response.ok ? response.json() : null;
    })
    .catch(function () {
      return null;
    });

  mePromise.then(function (me) {
    if (!me) return;
    setText("user-info", me.name ? me.name + " · " + me.email : me.email || "");
  });

  /** Resolve the per-session CSRF token delivered by GET /api/me. */
  function csrfToken() {
    return mePromise.then(function () {
      return csrf;
    });
  }

  function tick() {
    var clock = document.getElementById("clock");
    if (clock) clock.textContent = new Date().toLocaleTimeString();
  }

  tick();
  setInterval(tick, 1000);

  window.HandoverShell = { csrfToken: csrfToken };
})();
