// The copy button of the live API box (T-2744). Without script the address is a read-only
// field a person selects and copies by hand, so nothing depends on this file.
document.addEventListener("click", function (event) {
  var button = event.target.closest("[data-jc-copy]");
  if (!button || !navigator.clipboard) {
    return;
  }
  var field = document.getElementById(button.getAttribute("data-jc-copy"));
  var status = document.getElementById("jc-copy-status");
  navigator.clipboard.writeText(field.value).then(function () {
    if (status) {
      status.textContent = button.getAttribute("data-jc-copied");
    }
  });
});
