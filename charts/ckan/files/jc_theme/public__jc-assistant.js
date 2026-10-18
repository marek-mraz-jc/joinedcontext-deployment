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
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && box.open) {
      box.open = false;
      box.querySelector("summary").focus();
    }
  });
})();
