/* Theme switch shared by every page: the palette lives in styles.css, this only flips
   `data-theme` on <html>, remembers the choice and keeps the toggle labels in sync. */
(function () {
  var STORAGE_KEY = "rwx-theme";
  var root = document.documentElement;
  var DARK = "#241a30";
  var LIGHT = "#fff6ea";

  function stored() {
    try {
      var value = localStorage.getItem(STORAGE_KEY);
      return value === "light" || value === "dark" ? value : null;
    } catch (error) {
      return null;
    }
  }

  function preferred() {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }

  function apply(theme) {
    root.setAttribute("data-theme", theme);
    var dark = theme === "dark";
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", dark ? DARK : LIGHT);
    var label = dark ? "切换到亮色主题" : "切换到暗色主题";
    var buttons = document.querySelectorAll(".theme-toggle");
    for (var index = 0; index < buttons.length; index += 1) {
      buttons[index].setAttribute("aria-pressed", String(dark));
      buttons[index].setAttribute("aria-label", label);
      buttons[index].setAttribute("title", label);
    }
  }

  apply(stored() || preferred());
  // The toggle lives in <body>; this script runs in <head>, so sync the labels once it exists.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { apply(root.getAttribute("data-theme")); });
  } else {
    apply(root.getAttribute("data-theme"));
  }

  function toggle() {
    var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    try { localStorage.setItem(STORAGE_KEY, next); } catch (error) { /* private mode */ }
    apply(next);
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest(".theme-toggle");
    if (button) toggle();
  });
})();
