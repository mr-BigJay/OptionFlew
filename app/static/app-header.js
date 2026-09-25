(function () {
  document.addEventListener("click", function (e) {
    document.querySelectorAll(".app-header__menu[open]").forEach(function (el) {
      if (!el.contains(e.target)) el.removeAttribute("open");
    });
  });
})();
