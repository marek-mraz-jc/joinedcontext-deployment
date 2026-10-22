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

// T-5122: every frame loads its renderer (vega or MapLibre, 200-300 kB gzipped). Started together,
// seven charts made a phone download vega seven times and drew the page after 9.6 s. A frame names
// its address in data-src and starts once it is near the screen, one at a time, so each next frame
// takes the renderer from the cache. A frame that never reports loaded holds the rest 10 s at most.
// A chart's own template loads this file as well, so the queue starts once per page.
(function () {
  if (window.jcVizQueue) {
    return;
  }
  window.jcVizQueue = true;
  var waiting = Array.prototype.slice.call(document.querySelectorAll("iframe[data-jc-viz][data-src]"));
  var near = [];
  var busy = false;
  function next() {
    if (busy || near.length === 0) {
      return;
    }
    var frame = near.shift();
    var finished = false;
    busy = true;
    function done() {
      if (!finished) {
        finished = true;
        busy = false;
        next();
      }
    }
    frame.addEventListener("load", done);
    setTimeout(done, 10000);
    frame.setAttribute("src", frame.getAttribute("data-src"));
  }
  function approach(frame) {
    var at = waiting.indexOf(frame);
    if (at !== -1) {
      waiting.splice(at, 1);
      near.push(frame);
      next();
    }
  }
  if (!("IntersectionObserver" in window)) {
    waiting.slice().forEach(approach);
    return;
  }
  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) {
        observer.unobserve(entry.target);
        approach(entry.target);
      }
    });
  }, { rootMargin: "400px 0px" });
  waiting.forEach(function (frame) {
    observer.observe(frame);
  });
})();
