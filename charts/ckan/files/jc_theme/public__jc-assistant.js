// The catalogue's assistant (T-4204, AG-114): Escape or the ✕ in the chat's header (T-4635)
// closes it and gives focus back to its button; the chat's expand button (T-4658) grows it to the
// window and back. On a phone, or expanded, where the open frame takes the screen (jc-theme.css),
// the page behind is inert so focus and a screen reader stay in the chat. Without script the
// button still opens and closes it.
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
    if (!on || !(phone.matches || box.classList.contains("jc-full"))) {
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
  function close() {
    box.open = false;
    box.querySelector("summary").focus();
  }
  box.addEventListener("toggle", function () { silence(box.open); });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && box.open) {
      close();
    }
  });
  // The ✕ in the chat's header (T-4635) and its expand button (T-4658): the frame says close or
  // full / panel and carries nothing else; only the frame this page opened, from its own origin,
  // is heard.
  var frame = box.querySelector("iframe");
  var origin = frame ? new URL(frame.src, location.href).origin : null;
  window.addEventListener("message", function (event) {
    var data = event.data;
    if (box.open && frame && event.source === frame.contentWindow && event.origin === origin &&
        data && data.type === "jc-assistant-close") {
      close();
    } else if (frame && event.source === frame.contentWindow && event.origin === origin &&
        data && data.type === "jc-assistant-size" && (data.size === "full" || data.size === "panel")) {
      box.classList.toggle("jc-full", data.size === "full");
      silence(box.open);
    }
  });
})();
