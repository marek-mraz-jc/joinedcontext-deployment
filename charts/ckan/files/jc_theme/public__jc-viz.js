// The charts' frames (T-4641): the renderer's host page says how tall it is. Only a message from
// that frame itself, from the renderer's own origin, sets its height.
window.addEventListener("message", function (event) {
  var data = event.data || {};
  if (data.type !== "jc-viz-height" || typeof data.height !== "number") {
    return;
  }
  document.querySelectorAll("iframe[data-jc-viz]").forEach(function (frame) {
    if (frame.contentWindow === event.source && frame.getAttribute("data-jc-viz") === event.origin) {
      frame.style.height = Math.min(Math.max(Math.round(data.height), 120), 2000) + "px";
    }
  });
});
