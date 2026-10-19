/**
 * Theme toggle — light / dark / system.
 *
 * The initial theme is applied by an inline script in <head> (before first
 * paint) so the page never flashes the wrong colours. This file only handles
 * the toggle button and keeps the <html> class in sync.
 *
 * States cycle: light → dark → system → light.
 *   light  — always light
 *   dark   — always dark
 *   system — follow the OS preference (prefers-color-scheme)
 *
 * The choice is persisted in localStorage under "theme".
 * A stored value of "system" (or no value) means "follow the OS".
 *
 * Exposed API (optional use from other scripts):
 *   window.theme.set('light' | 'dark' | 'system')
 *   window.theme.get()      → 'light' | 'dark' | 'system'
 *   window.theme.effective()→ 'light' | 'dark'
 */
"use strict";

(function () {
  var STORAGE_KEY = "theme";
  var root = document.documentElement;
  var media = window.matchMedia("(prefers-color-scheme: dark)");

  var ORDER = ["light", "dark", "system"];

  function readStored() {
    try {
      var v = localStorage.getItem(STORAGE_KEY);
      return ORDER.indexOf(v) === -1 ? "system" : v;
    } catch (e) {
      return "system";
    }
  }

  function writeStored(mode) {
    try {
      if (mode === "system") localStorage.removeItem(STORAGE_KEY);
      else localStorage.setItem(STORAGE_KEY, mode);
    } catch (e) { /* storage blocked — theme still works for this page */ }
  }

  function effective(mode) {
    if (mode === "dark") return "dark";
    if (mode === "light") return "light";
    return media.matches ? "dark" : "light";
  }

  function apply(mode, persist) {
    if (persist) writeStored(mode);
    root.classList.toggle("dark", effective(mode) === "dark");
    syncButtons(mode);
  }

  function iconFor(mode) {
    if (mode === "light") return "moon";
    if (mode === "dark") return "sun";
    return "monitor";
  }

  function syncButtons(mode) {
    var buttons = document.querySelectorAll("[data-theme-toggle]");
    var shown = iconFor(mode);
    var label =
      mode === "system" ? "Theme: system (click for light)" :
      mode === "light" ? "Theme: light (click for dark)" :
                         "Theme: dark (click for system)";

    buttons.forEach(function (btn) {
      btn.setAttribute("aria-label", label);
      btn.setAttribute("title", label);
      btn.setAttribute("data-theme", mode);
      btn.querySelectorAll("[data-theme-icon]").forEach(function (icon) {
        icon.classList.toggle("hidden", icon.getAttribute("data-theme-icon") !== shown);
      });
    });
  }

  function next(mode) {
    return ORDER[(ORDER.indexOf(mode) + 1) % ORDER.length];
  }

  // Delegated click — works for toggles added to the page later.
  document.addEventListener("click", function (e) {
    var btn = e.target.closest ? e.target.closest("[data-theme-toggle]") : null;
    if (!btn) return;
    e.preventDefault();
    apply(next(readStored()), true);
  });

  // Follow the OS while the user has not pinned a theme.
  var onSystemChange = function (e) {
    if (readStored() !== "system") return;
    root.classList.toggle("dark", e.matches);
  };
  if (media.addEventListener) media.addEventListener("change", onSystemChange);
  else if (media.addListener) media.addListener(onSystemChange);

  // Sync the icon of the toggle rendered in the HTML.
  function init() {
    var stored = readStored();
    root.classList.toggle("dark", effective(stored) === "dark");
    syncButtons(stored);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.theme = {
    set: function (mode) {
      if (ORDER.indexOf(mode) === -1) return;
      apply(mode, true);
    },
    get: readStored,
    effective: function () { return effective(readStored()); },
  };
})();
