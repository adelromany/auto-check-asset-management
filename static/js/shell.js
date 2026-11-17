/**
 * shell.js — the shared behaviour of every screen.
 *
 * Owns: the portal API helper (CSRF), toasts, the drawer system, the
 * omnibox, the user menu, keyboard shortcuts, list auto-refresh and the
 * dashboard count-up. Page modules (dashboard.js, case.js, ...) build on
 * window.portal. No inline scripts or styles (strict CSP); only
 * textContent / DOM node moves, never innerHTML with data.
 */
"use strict";

(function () {
  var portal = (window.portal = {});

  // -- tiny DOM helpers -----------------------------------------------------
  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }
  portal.el = el;

  function $(selector, root) {
    return (root || document).querySelector(selector);
  }
  portal.$ = $;

  function $all(selector, root) {
    return Array.prototype.slice.call(
      (root || document).querySelectorAll(selector)
    );
  }
  portal.$all = $all;

  // -- API helper with CSRF -------------------------------------------------
  var csrfToken = null;

  function fetchMe() {
    return fetch("/api/me", { credentials: "same-origin" }).then(function (res) {
      if (!res.ok) return null;
      csrfToken = res.headers.get("X-CSRF-Token") || csrfToken;
      return res.json();
    });
  }
  portal.fetchMe = fetchMe;

  function request(path, options) {
    options = options || {};
    var headers = Object.assign({}, options.headers || {});
    if (
      options.method &&
      options.method !== "GET" &&
      csrfToken &&
      path.indexOf("/api/session/") !== 0
    ) {
      headers["X-CSRF-Token"] = csrfToken;
    }
    var init = Object.assign({}, options, {
      headers: headers,
      credentials: "same-origin",
    });
    return fetch(path, init).then(function (res) {
      if (res.status === 403 && options.method && options.method !== "GET") {
        // The CSRF token may be stale; refresh once and retry.
        return fetchMe().then(function () {
          if (csrfToken) {
            headers["X-CSRF-Token"] = csrfToken;
            return fetch(path, Object.assign({}, options, {
              headers: headers,
              credentials: "same-origin",
            }));
          }
          return res;
        });
      }
      return res;
    }).then(function (res) {
      if (res.status === 204) return {};
      return res.json().catch(function () {
        return {};
      }).then(function (body) {
        if (!res.ok) {
          var message = body && body.detail ? body.detail : "Request failed (" + res.status + ")";
          if (Array.isArray(message)) message = message.map(function (e) { return e.msg || ""; }).join(", ");
          var error = new Error(typeof message === "string" ? message : JSON.stringify(message));
          error.status = res.status;
          throw error;
        }
        return body;
      });
    });
  }
  portal.request = request;

  function apiJson(path, options) {
    return request(path, Object.assign({}, options, {
      headers: Object.assign(
        { "Content-Type": "application/json" },
        (options && options.headers) || {}
      ),
    }));
  }
  portal.apiJson = apiJson;

  // -- toasts ----------------------------------------------------------------
  function toast(message, kind) {
    var stack = $("#toast-stack");
    if (!stack) return;
    var node = el("div", "toast" + (kind ? " toast-" + kind : ""), message);
    node.setAttribute("data-toast", kind || "info");
    node.setAttribute("role", "status");
    stack.appendChild(node);
    setTimeout(function () {
      if (node.parentNode) node.parentNode.removeChild(node);
    }, 4500);
  }
  portal.toast = toast;

  // -- drawers ----------------------------------------------------------------
  var openDrawerEl = null;
  var lastFocus = null;

  function openDrawer(title, bodyNode, options) {
    options = options || {};
    closeDrawer();
    lastFocus = document.activeElement;
    var overlay = el("div", "drawer-overlay");
    overlay.setAttribute("data-drawer-overlay", "");
    var drawer = el("aside", "drawer");
    drawer.setAttribute("data-drawer", "");
    drawer.setAttribute("data-open", "true");
    drawer.setAttribute("role", "dialog");
    drawer.setAttribute("aria-label", title);

    var head = el("div", "drawer-head");
    var heading = el("h2", "drawer-title", title);
    var close = el("button", "btn btn-ghost btn-icon", "×");
    close.type = "button";
    close.setAttribute("data-drawer-close", "");
    close.setAttribute("aria-label", "Close");
    head.appendChild(heading);
    head.appendChild(close);

    drawer.appendChild(head);
    drawer.appendChild(bodyNode);

    function onClose() {
      closeDrawer();
      if (options.onClose) options.onClose();
    }
    overlay.addEventListener("click", onClose);
    close.addEventListener("click", onClose);

    var root = $("#drawer-root");
    root.appendChild(overlay);
    root.appendChild(drawer);
    openDrawerEl = drawer;
    document.body.classList.add("drawer-open");
    var first = drawer.querySelector("input, select, textarea, button");
    if (first) first.focus();
    return drawer;
  }
  portal.openDrawer = openDrawer;

  function closeDrawer() {
    if (openDrawerEl) {
      var root = $("#drawer-root");
      var overlay = $("[data-drawer-overlay]", root);
      if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);
      openDrawerEl.parentNode.removeChild(openDrawerEl);
      openDrawerEl = null;
      document.body.classList.remove("drawer-open");
      if (lastFocus && lastFocus.focus) lastFocus.focus();
      lastFocus = null;
    }
  }
  portal.closeDrawer = closeDrawer;

  function drawerForm(title, options) {
    var body = el("div", "drawer-body");
    var form = el("form", "drawer-form stack");
    body.appendChild(form);
    var drawer = openDrawer(title, body, options);
    drawer.__form = form;
    return drawer;
  }
  portal.drawerForm = drawerForm;

  function field(labelText, input, hint) {
    var wrap = el("label", "field");
    var cap = el("span", "field-label", labelText);
    wrap.appendChild(cap);
    wrap.appendChild(input);
    if (hint) {
      var note = el("span", "field-hint", hint);
      wrap.appendChild(note);
    }
    return wrap;
  }
  portal.field = field;

  function textInput(name, placeholder, opts) {
    opts = opts || {};
    var input = el("input", "input");
    input.name = name;
    input.type = opts.type || "text";
    if (placeholder) input.placeholder = placeholder;
    if (opts.value !== undefined) input.value = opts.value;
    if (opts.required) input.required = true;
    if (opts.maxlength) input.maxLength = opts.maxlength;
    return input;
  }
  portal.textInput = textInput;

  function selectInput(name, values, current) {
    var select = el("select", "input");
    select.name = name;
    values.forEach(function (item) {
      var value = typeof item === "string" ? item : item.value;
      var label = typeof item === "string" ? item : item.label;
      var option = el("option", "", label);
      option.value = value;
      if (current && current === value) option.selected = true;
      select.appendChild(option);
    });
    return select;
  }
  portal.selectInput = selectInput;

  function formActions(primaryLabel, opts) {
    opts = opts || {};
    var row = el("div", "form-actions");
    var primary = el("button", "btn btn-default", primaryLabel);
    primary.type = "submit";
    primary.setAttribute("data-primary", "");
    row.appendChild(primary);
    if (opts.secondaryLabel) {
      var secondary = el("button", "btn btn-outline", opts.secondaryLabel);
      secondary.type = "button";
      secondary.setAttribute("data-secondary", "");
      row.appendChild(secondary);
      row.__secondary = secondary;
    }
    row.__primary = primary;
    return row;
  }
  portal.formActions = formActions;

  function setBusy(row, busy) {
    if (row && row.__primary) {
      row.__primary.disabled = !!busy;
      if (row.__secondary) row.__secondary.disabled = !!busy;
    }
  }
  portal.setBusy = setBusy;

  function buttonRow(children) {
    var row = el("div", "button-row");
    children.forEach(function (child) { row.appendChild(child); });
    return row;
  }
  portal.buttonRow = buttonRow;

  function actionButton(label, kind) {
    var btn = el("button", "btn " + (kind || "btn-outline"), label);
    btn.type = "button";
    return btn;
  }
  portal.actionButton = actionButton;

  function disabledButton(label, reason) {
    var btn = el("button", "btn btn-outline", label);
    btn.type = "button";
    btn.disabled = true;
    btn.title = reason;
    btn.setAttribute("aria-disabled", "true");
    var wrap = el("div", "disabled-reason");
    wrap.setAttribute("data-disabled-reason", reason);
    wrap.appendChild(btn);
    var note = el("span", "field-hint", reason);
    wrap.appendChild(note);
    return wrap;
  }
  portal.disabledButton = disabledButton;

  // -- registration drawer (new handover / new maintenance) -------------------
  function openNewCase(kind, options) {
    options = options || {};
    var isMaintenance = kind === "maintenance";
    var title = isMaintenance ? "New maintenance" : "New handover";
    var drawer = portal.drawerForm(title, {});
    var form = drawer.__form;
    form.setAttribute("data-new-case-form", "");
    form.setAttribute("data-kind", kind);

    var serial = portal.textInput("device_serial", "Serial number", { required: true, maxlength: 100 });
    var match = portal.el("div", "snipe-match", "");
    match.setAttribute("data-snipe-match", "");
    serial.addEventListener("input", function () {
      match.textContent = "";
      match.removeAttribute("data-state");
      var value = serial.value.trim();
      if (value.length < 3) return;
      fetch("/api/snipeit/device?serial=" + encodeURIComponent(value), {
        credentials: "same-origin",
      }).then(function (res) { return res.ok ? res.json() : null; })
        .then(function (device) {
          if (!device) return;
          if (device.found) {
            match.textContent = "Snipe-IT: " + (device.asset_tag || "") + " " + (device.model || "");
            match.setAttribute("data-state", "ok");
          } else {
            match.textContent = "Not found in Snipe-IT";
            match.setAttribute("data-state", "miss");
          }
        }).catch(function () { /* Snipe-IT optional at registration */ });
    });

    var ticket = portal.textInput("ticket_ref", "Ticket (optional)", { maxlength: 100 });
    var actions = portal.formActions("Register");
    form.appendChild(portal.field("Serial", serial, isMaintenance ? "The device that needs repair" : "The device leaving or returning"));
    form.appendChild(match);
    form.appendChild(portal.field("Ticket", ticket));
    form.appendChild(actions);

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var serialValue = serial.value.trim();
      if (!serialValue) {
        portal.toast("Enter a serial first.", "error");
        return;
      }
      portal.setBusy(actions, true);
      var payload = {
        device_serial: serialValue,
        kind: kind,
      };
      if (ticket.value.trim()) payload.ticket_ref = ticket.value.trim();
      portal.apiJson("/api/handovers", { method: "POST", body: JSON.stringify(payload) })
        .then(function (created) {
          window.location.href = (kind === "maintenance" ? "/maintenance/" : "/handovers/") + created.id;
        })
        .catch(function (error) {
          portal.setBusy(actions, false);
          portal.toast(error.message, "error");
          var existing = $("#snipe-active", form);
          if (error.status === 409) {
            // one active case per serial — say it plainly
            portal.toast("This serial already has an active case.", "error");
          }
        });
    });
    serial.focus();
    return drawer;
  }
  portal.openNewCase = openNewCase;

  // -- omnibox -----------------------------------------------------------------
  function setupOmnibox() {
    var box = $("#omnibox");
    if (!box) return;
    var input = $("#omnibox-input");
    var results = $("#omnibox-results");
    var timer = null;

    function hide() {
      results.hidden = true;
      results.textContent = "";
    }

    function group(title, items, build) {
      var section = portal.el("div", "omnibox-group");
      section.appendChild(portal.el("div", "omnibox-group-title", title));
      items.forEach(function (item) {
        var link = portal.el("a", "omnibox-item");
        link.href = item.href;
        build(link, item);
        section.appendChild(link);
      });
      return section;
    }

    function search(q) {
      if (!q || q.length < 2) { hide(); return; }
      portal.apiJson("/api/handovers?q=" + encodeURIComponent(q) + "&page_size=10")
        .then(function (list) {
          results.textContent = "";
          results.hidden = false;
          var handovers = (list.items || []).filter(function (r) { return (r.kind || "handover") === "handover"; });
          var maintenances = (list.items || []).filter(function (r) { return r.kind === "maintenance"; });
          if (handovers.length) {
            results.appendChild(group("Handovers", handovers.map(function (r) {
              return {
                href: "/handovers/" + r.id,
                serial: r.device_serial,
                who: r.recipient_snipeit_name || r.recipient_reported_username || r.engineer_name,
              };
            }), function (link, item) {
              link.appendChild(portal.el("span", "omnibox-serial mono", item.serial));
              link.appendChild(portal.el("span", "omnibox-who", item.who || ""));
            }));
          }
          if (maintenances.length) {
            results.appendChild(group("Maintenance", maintenances.map(function (r) {
              return {
                href: "/maintenance/" + r.id,
                serial: r.device_serial,
                who: r.recipient_snipeit_name || r.recipient_reported_username || r.engineer_name,
              };
            }), function (link, item) {
              link.appendChild(portal.el("span", "omnibox-serial mono", item.serial));
              link.appendChild(portal.el("span", "omnibox-who", item.who || ""));
            }));
          }
          if (q.length >= 3) {
            fetch("/api/snipeit/device?serial=" + encodeURIComponent(q), { credentials: "same-origin" })
              .then(function (res) { return res.ok ? res.json() : null; })
              .then(function (device) {
                if (!device || !device.found) return;
                results.appendChild(group("Devices", [{
                  href: "/handovers?q=" + encodeURIComponent(device.serial || q),
                  serial: device.serial || q,
                  who: (device.asset_tag || "") + " " + (device.model || ""),
                }], function (link, item) {
                  link.appendChild(portal.el("span", "omnibox-serial mono", item.serial));
                  link.appendChild(portal.el("span", "omnibox-who", item.who));
                }));
              }).catch(function () { /* device lookup optional */ });
          }
          if (!results.childNodes.length) {
            results.appendChild(portal.el("div", "omnibox-empty", "No match"));
          }
        })
        .catch(function () { hide(); });
    }

    input.addEventListener("input", function () {
      clearTimeout(timer);
      var q = input.value.trim();
      timer = setTimeout(function () { search(q); }, 200);
    });
    input.addEventListener("keydown", function (event) {
      if (event.key === "Escape") { hide(); input.blur(); }
      if (event.key === "Enter") {
        var first = results.querySelector("a.omnibox-item");
        if (first) {
          event.preventDefault();
          window.location.href = first.href;
        }
      }
    });
    box.addEventListener("focusout", function (event) {
      if (!box.contains(event.relatedTarget)) hide();
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "/" && !event.defaultPrevented) {
        var target = event.target;
        var typing = target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT" || target.isContentEditable);
        if (!typing) {
          event.preventDefault();
          input.focus();
          input.select();
        }
      }
      if (event.key.toLowerCase() === "n" && !event.ctrlKey && !event.metaKey && !event.altKey) {
        var t = event.target;
        var busyTyping = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
        if (!busyTyping) {
          var trigger = $("[data-new-shortcut]");
          if (trigger) {
            event.preventDefault();
            trigger.click();
          }
        }
      }
      if (event.key === "Escape") {
        portal.closeDrawer();
        var pop = $("#user-menu-pop");
        if (pop && !pop.hidden) toggleUserMenu(false);
      }
    });
  }

  // -- user menu ---------------------------------------------------------------
  function toggleUserMenu(force) {
    var pop = $("#user-menu-pop");
    var button = $("#user-menu-button");
    if (!pop || !button) return;
    var show = force !== undefined ? force : pop.hidden;
    pop.hidden = !show;
    button.setAttribute("aria-expanded", show ? "true" : "false");
  }

  function setupUserMenu() {
    var button = $("#user-menu-button");
    if (button) {
      button.addEventListener("click", function () { toggleUserMenu(); });
    }
    document.addEventListener("click", function (event) {
      var menu = $("#user-menu");
      if (menu && !menu.contains(event.target)) toggleUserMenu(false);
    });
  }

  // -- back button (error page) -------------------------------------------------
  document.addEventListener("click", function (event) {
    var back = event.target.closest ? event.target.closest("[data-back]") : null;
    if (!back) return;
    event.preventDefault();
    if (window.history.length > 1) window.history.back();
    else window.location.href = "/";
  });

  // -- user identity -------------------------------------------------------------
  function hydrateUser() {
    fetchMe().then(function (user) {
      if (!user) return;
      portal.$all("[data-user-name]").forEach(function (node) {
        node.textContent = user.name || user.email || "Engineer";
      });
      portal.$all("[data-user-email]").forEach(function (node) {
        node.textContent = user.email || "";
      });
      portal.$all("[data-user-avatar]").forEach(function (node) {
        var name = user.name || user.email || "?";
        var initials = name.trim().split(/[\s.@]+/).filter(Boolean).slice(0, 2)
          .map(function (part) { return part.charAt(0).toUpperCase(); }).join("");
        node.textContent = initials || "?";
      });
      document.body.setAttribute("data-user-email", user.email || "");
    }).catch(function () { /* anonymous is fine when SSO is off */ });
  }

  // -- auto refresh ----------------------------------------------------------------
  function setupAutoRefresh() {
    var region = $("[data-refresh-region]");
    var seconds = region ? parseInt(region.getAttribute("data-refresh") || "15", 10) : 0;
    if (!region || !seconds) return;
    var indicator = $("[data-updated]");

    function bump() {
      if (indicator) indicator.textContent = "Updated just now";
      var stamp = indicator ? indicator.getAttribute("data-stamp") : null;
      if (stamp) indicator.setAttribute("data-stamp", String(Date.now()));
    }

    function tick() {
      var drawerOpen = !!$("[data-drawer]");
      var focusInRegion = region.contains(document.activeElement) &&
        document.activeElement.tagName !== "A";
      var formDirty = region.querySelector("form[data-new-case-form]");
      if (drawerOpen || focusInRegion || formDirty) return;
      fetch(window.location.href, {
        credentials: "same-origin",
        headers: { "X-Refresh": "partial" },
      }).then(function (res) {
        if (!res.ok) return null;
        return res.text();
      }).then(function (text) {
        if (!text) return;
        var parsed = new DOMParser().parseFromString(text, "text/html");
        var fresh = parsed.querySelector("[data-refresh-region]");
        if (!fresh) return;
        region.parentNode.replaceChild(fresh, region);
        portal.$all = $all; // keep helper identities fresh for page modules
        bump();
        document.dispatchEvent(new CustomEvent("portal:refreshed"));
      }).catch(function () { /* keep the stale view; next tick retries */ });
    }
    setInterval(tick, seconds * 1000);
  }

  // -- count-up ----------------------------------------------------------------------
  function setupCountUp() {
    var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    portal.$all("[data-countup]").forEach(function (node) {
      var target = parseInt(node.getAttribute("data-value") || node.textContent || "0", 10);
      if (isNaN(target)) target = 0;
      if (reduced) { node.textContent = String(target); return; }
      var start = null;
      var duration = 300;
      function step(ts) {
        if (!start) start = ts;
        var progress = Math.min(1, (ts - start) / duration);
        var value = Math.round(target * progress);
        node.textContent = String(value);
        if (progress < 1) window.requestAnimationFrame(step);
      }
      node.textContent = "0";
      window.requestAnimationFrame(step);
    });
  }

  // -- boot ---------------------------------------------------------------------------
  function boot() {
    setupOmnibox();
    setupUserMenu();
    hydrateUser();
    setupAutoRefresh();
    setupCountUp();
    var openNew = document.body.getAttribute("data-open-new");
    if (openNew) portal.openNewCase(openNew);
    portal.$all("[data-new-shortcut]").forEach(function (trigger) {
      trigger.addEventListener("click", function () {
        portal.openNewCase(trigger.getAttribute("data-new-shortcut"));
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
