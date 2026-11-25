/* Maintenance-only dashboard helpers. */
"use strict";
(function () {
  var portal = window.portal;
  if (!portal) return;
  document.addEventListener("portal:refreshed", function () { portal.applyBarWidths(); });
  portal.applyBarWidths();
})();
