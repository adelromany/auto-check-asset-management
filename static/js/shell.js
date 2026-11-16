/**
 * Shared page shell: signed-in identity, omnibox shortcut and CSRF token.
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
    var name = me.name || me.email || "Engineer";
    var container = document.getElementById("user-info");
    if (container) {
      var display = container.querySelector(".user-display-name");
      if (display) {
        display.textContent = name;
      } else {
        container.textContent = name;
      }
    }
  });

  /** Resolve the per-session CSRF token delivered by GET /api/me. */
  function csrfToken() {
    return mePromise.then(function () {
      return csrf;
    });
  }

  // Keyboard shortcut '/' to focus global omnibox search
  document.addEventListener("keydown", function (event) {
    if (event.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) {
      event.preventDefault();
      var searchInput = document.getElementById("global-search");
      if (searchInput) {
        searchInput.focus();
        searchInput.select();
      }
    }
  });

  window.HandoverShell = { csrfToken: csrfToken };
})();
