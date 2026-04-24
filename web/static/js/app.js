/* CYT-NG — WebSocket connection & HTMX configuration */
(function () {
  "use strict";

  // ── SocketIO ──────────────────────────────────────────────
  const socket = io({ transports: ["websocket", "polling"] });
  const badge = document.getElementById("conn-status");

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

  // ── HTMX global config ───────────────────────────────────
  document.body.addEventListener("htmx:configRequest", function (evt) {
    // Ensure HX-Request header is always sent (for partial detection)
    evt.detail.headers["HX-Request"] = "true";
  });

  // Flash-style toast on HTMX errors
  document.body.addEventListener("htmx:responseError", function (evt) {
    console.error("HTMX error:", evt.detail);
  });
})();
