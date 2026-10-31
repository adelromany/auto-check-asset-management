/**
 * Shared page shell: the signed-in identity and the header clock.
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

  fetch("/api/me", { headers: { Accept: "application/json" } })
    .then(function (response) {
      return response.ok ? response.json() : null;
    })
    .then(function (me) {
      if (!me) return;
      setText("user-info", me.name ? me.name + " · " + me.email : me.email || "");
    })
    .catch(function () {
      /* the header identity is cosmetic; a failure must not break the page */
    });

  function tick() {
    var clock = document.getElementById("clock");
    if (clock) clock.textContent = new Date().toLocaleTimeString();
  }

  tick();
  setInterval(tick, 1000);
})();
