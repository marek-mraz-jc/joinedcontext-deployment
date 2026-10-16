// The catalogue's assistant (T-4204, AG-114): Escape closes it and gives focus back to its
// button; on a phone, where the open frame takes the whole screen (jc-theme.css), the page behind
// is inert so focus and a screen reader stay in the chat. Without script the button still opens
// and closes it.
(function () {
  var box = document.querySelector("details.jc-assistant");
  if (!box) {
    return;
  }
  var phone = window.matchMedia("(max-width: 40rem)");
  var silenced = [];
  function silence(on) {
    silenced.forEach(function (el) { el.inert = false; });
    silenced = [];
    if (!on || !phone.matches) {
      return;
    }
    for (var node = box; node && node !== document.body; node = node.parentElement) {
      Array.prototype.forEach.call(node.parentElement.children, function (el) {
        if (el !== node && !el.inert) {
          el.inert = true;
          silenced.push(el);
        }
      });
    }
  }
  box.addEventListener("toggle", function () { silence(box.open); });
  // The chat says how tall its content is (T-4283, Architecture/22 §4); the frame takes that
  // height, the stylesheet keeps it inside the window. Only this frame's own page is heard.
  var frame = box.querySelector("iframe");
  var origin = frame ? new URL(frame.src, location.href).origin : null;
  window.addEventListener("message", function (event) {
    if (!frame || event.source !== frame.contentWindow || event.origin !== origin) return;
    var data = event.data;
    if (!data || data.type !== "jc-assistant-height") return;
    var height = Number(data.height);
    if (isFinite(height) && height > 0) frame.style.setProperty("--jc-h", Math.ceil(height) + "px");
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && box.open) {
      box.open = false;
      box.querySelector("summary").focus();
    }
  });
})();
