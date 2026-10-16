// The copy button of the live API box (T-2744). Without script the address is a read-only
// field or block a person selects and copies by hand, so nothing depends on this file.
document.addEventListener("click", function (event) {
  var button = event.target.closest("[data-jc-copy]");
  if (!button || !navigator.clipboard) {
    return;
  }
  var field = document.getElementById(button.getAttribute("data-jc-copy"));
  var status = document.getElementById("jc-copy-status");
  navigator.clipboard.writeText(field.value !== undefined ? field.value : field.textContent).then(function () {
    var copied = button.getAttribute("data-jc-copied");
    if (status) {
      status.textContent = copied;
    }
    // A button with its own label says so where the eye is, then goes back (T-4284).
    var label = button.querySelector(".jc-code-copy-label");
    if (label && copied) {
      var was = label.getAttribute("data-label") || label.textContent;
      label.setAttribute("data-label", was);
      label.textContent = copied;
      setTimeout(function () {
        label.textContent = was;
      }, 2000);
    }
  });
});
