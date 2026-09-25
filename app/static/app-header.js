(function () {
  function placeMenuDropdown(details) {
    var btn = details.querySelector("summary");
    var menu = details.querySelector(".app-header__dropdown");
    if (!btn || !menu) return;
    var rect = btn.getBoundingClientRect();
    var gap = 6;
    var pad = 8;
    menu.style.top = Math.round(rect.bottom + gap) + "px";
    var width = menu.offsetWidth || 168;
    var left = rect.left;
    if (left + width > window.innerWidth - pad) {
      left = window.innerWidth - width - pad;
    }
    if (left < pad) left = pad;
    menu.style.left = Math.round(left) + "px";
    menu.style.right = "auto";
  }

  function bindMenu(details) {
    details.addEventListener("toggle", function () {
      if (details.open) {
        placeMenuDropdown(details);
      }
    });
  }

  document.querySelectorAll(".app-header__menu").forEach(bindMenu);

  window.addEventListener(
    "resize",
    function () {
      document.querySelectorAll(".app-header__menu[open]").forEach(placeMenuDropdown);
    },
    { passive: true }
  );

  document.addEventListener("click", function (e) {
    document.querySelectorAll(".app-header__menu[open]").forEach(function (el) {
      if (!el.contains(e.target)) el.removeAttribute("open");
    });
  });
})();
