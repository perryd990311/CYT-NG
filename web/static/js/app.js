/* CYT-NG — WebSocket connection & HTMX configuration */

// ── Local-time conversion (runs first, independent of SocketIO) ──
(function () {
  "use strict";

  function convertLocalTimes(root) {
    (root || document).querySelectorAll("time.localtime").forEach(function (el) {
      var iso = el.getAttribute("datetime");
      if (!iso) return;
      var d = new Date(iso);
      if (isNaN(d)) return;
      var fmt = el.getAttribute("data-fmt") || "short";
      var pad = function (n) { return n < 10 ? "0" + n : n; };
      var s = d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate())
            + " " + pad(d.getHours()) + ":" + pad(d.getMinutes());
      if (fmt === "long") s += ":" + pad(d.getSeconds());
      el.textContent = s;
    });
  }

  // Run on page load
  convertLocalTimes();

  // Re-run after every HTMX swap (for partials loaded dynamically)
  document.body.addEventListener("htmx:afterSwap", function (evt) {
    convertLocalTimes(evt.detail.target);
  });
})();

// ── SocketIO & HTMX config ──────────────────────────────────
(function () {
  "use strict";

  if (typeof io === "undefined") {
    console.warn("SocketIO not loaded — real-time updates disabled");
    return;
  }

  var socket = io({ transports: ["websocket", "polling"] });
  var badge = document.getElementById("conn-status");

  function setStatus(html) {
    if (badge) badge.innerHTML = html;
  }

  socket.on("connect", function () {
    setStatus('<i class="bi bi-circle-fill text-success"></i> connected');
  });

  socket.on("disconnect", function () {
    setStatus('<i class="bi bi-circle-fill text-danger"></i> disconnected');
  });

  // Real-time device update — refresh the device list partial + sparkline
  socket.on("device_update", function () {
    var el = document.getElementById("device-list");
    if (el) htmx.trigger(el, "refresh");
    if (typeof window.refreshSparkline === "function") window.refreshSparkline();
  });

  // Real-time status update — refresh status bar
  socket.on("status_update", function () {
    var el = document.getElementById("status-bar");
    if (el) htmx.trigger(el, "refresh");
  });

  // Expose for console debugging
  window.cytSocket = socket;
})();

// ── HTMX global config ─────────────────────────────────────
(function () {
  "use strict";

  document.body.addEventListener("htmx:configRequest", function (evt) {
    // Ensure HX-Request header is always sent (for partial detection)
    evt.detail.headers["HX-Request"] = "true";
  });

  // Flash-style toast on HTMX errors
  document.body.addEventListener("htmx:responseError", function (evt) {
    console.error("HTMX error:", evt.detail);
  });
})();
