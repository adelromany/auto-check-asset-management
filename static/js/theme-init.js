/**
 * Apply the stored theme before first paint.
 *
 * Loaded synchronously in <head> so it runs before the body is rendered and
 * the page never flashes the wrong theme. Kept separate from theme.js so the
 * pages work under a self-only Content-Security-Policy (no inline script).
 */
(function () {
  try {
    var stored = localStorage.getItem("theme");
    var prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    var dark = stored === "dark" || (stored !== "light" && prefersDark);
    document.documentElement.classList.toggle("dark", dark);
  } catch (e) {
    /* storage blocked — fall back to light */
  }
})();
