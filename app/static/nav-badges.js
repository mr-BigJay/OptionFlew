(function () {
  function setBadge(key, n) {
    var link = document.querySelector('.bottom-nav__item[data-nav="' + key + '"]');
    if (!link) return;
    if (link.classList.contains("active")) {
      n = 0;
    }
    var icon = link.querySelector(".nav-icon");
    if (!icon) return;
    var el = icon.querySelector('[data-badge="' + key + '"]');
    if (n > 0) {
      if (!el) {
        el = document.createElement("span");
        el.className = "nav-badge";
        el.setAttribute("data-badge", key);
        icon.appendChild(el);
      }
      el.textContent = String(n);
    } else if (el) {
      el.remove();
    }
  }

  function poll() {
    fetch("/api/nav/badges", { credentials: "same-origin" })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        if (!data) return;
        setBadge("patterns", data.patterns || 0);
        setBadge("reports", data.reports || 0);
        setBadge("position", data.position || 0);
      })
      .catch(function () {});
  }

  document.addEventListener("DOMContentLoaded", function () {
    if (!document.getElementById("bottom-nav")) return;
    poll();
    setInterval(poll, 20000);
  });
})();
