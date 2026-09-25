(function () {
  "use strict";

  var root = document.getElementById("indicator-detail");
  if (!root) return;

  var indicatorId = root.getAttribute("data-indicator-id");
  var language = root.getAttribute("data-language") || "pine";
  var tf = root.getAttribute("data-chart-tf") || "15m";
  var mount = document.getElementById("indicator-live-mount");
  var panesMount = document.getElementById("indicator-live-panes");
  var hint = document.getElementById("indicator-live-hint");
  var modalRoot = document.getElementById("indicator-modals");
  var tvForm = document.getElementById("tv-settings-form");
  var tvEmpty = document.getElementById("tv-modal-empty");
  var storageKey = "indicator-tv-settings:" + indicatorId;

  var tvFields = [];
  try {
    var fieldsEl = document.getElementById("indicator-tv-fields");
    tvFields = JSON.parse((fieldsEl && fieldsEl.textContent) || "[]");
  } catch (e) {
    tvFields = [];
  }

  function loadSettings() {
    try {
      var raw = localStorage.getItem(storageKey);
      if (raw) return JSON.parse(raw);
    } catch (e) {}
    var defaults = {};
    tvFields.forEach(function (f) {
      defaults[f.id] = f.default;
    });
    return defaults;
  }

  function saveSettings(obj) {
    try {
      localStorage.setItem(storageKey, JSON.stringify(obj));
    } catch (e) {}
  }

  function readSettingsFromForm() {
    var out = loadSettings();
    if (!tvForm) return out;
    tvForm.querySelectorAll("[data-tv-field]").forEach(function (el) {
      var id = el.getAttribute("data-tv-field");
      if (el.type === "checkbox") out[id] = el.checked;
      else if (el.type === "number") out[id] = parseFloat(el.value);
      else out[id] = el.value;
    });
    return out;
  }

  function buildTvForm() {
    if (!tvForm) return;
    tvForm.innerHTML = "";
    if (language !== "pine" || !tvFields.length) {
      if (tvEmpty) tvEmpty.hidden = false;
      return;
    }
    if (tvEmpty) tvEmpty.hidden = true;
    var settings = loadSettings();
    tvFields.forEach(function (f) {
      var wrap = document.createElement("label");
      wrap.className = "indicator-tv-field";
      var title = document.createElement("span");
      title.textContent = f.title || f.id;
      wrap.appendChild(title);
      var input;
      if (f.type === "bool") {
        input = document.createElement("input");
        input.type = "checkbox";
        input.checked = !!settings[f.id];
      } else if (f.type === "color") {
        input = document.createElement("input");
        input.type = "color";
        var c = String(settings[f.id] || f.default || "#7E57C2");
        if (c.charAt(0) !== "#") c = "#7E57C2";
        input.value = c.length > 7 ? c.slice(0, 7) : c;
      } else if (f.type === "int" || f.type === "float") {
        input = document.createElement("input");
        input.type = "number";
        input.step = f.type === "int" ? "1" : "0.01";
        if (f.min != null) input.min = String(f.min);
        if (f.max != null) input.max = String(f.max);
        input.value = settings[f.id] != null ? settings[f.id] : f.default;
      } else {
        input = document.createElement("input");
        input.type = "text";
        input.dir = "ltr";
        input.value = settings[f.id] != null ? settings[f.id] : f.default || "";
      }
      input.setAttribute("data-tv-field", f.id);
      wrap.appendChild(input);
      tvForm.appendChild(wrap);
    });
  }

  function openModal(name) {
    if (!modalRoot) return;
    modalRoot.hidden = false;
    document.body.classList.add("modal-open");
    modalRoot.querySelectorAll(".app-modal").forEach(function (m) {
      m.hidden = true;
    });
    var panel = document.getElementById("modal-" + name);
    if (panel) panel.hidden = false;
    if (name === "tv") buildTvForm();
  }

  function closeModals() {
    if (!modalRoot) return;
    modalRoot.hidden = true;
    document.body.classList.remove("modal-open");
  }

  root.querySelectorAll("[data-modal-open]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      openModal(btn.getAttribute("data-modal-open"));
    });
  });
  if (modalRoot) {
    modalRoot.querySelectorAll("[data-modal-close]").forEach(function (el) {
      el.addEventListener("click", closeModals);
    });
  }

  var copyBtn = document.getElementById("copy-indicator-src");
  if (copyBtn) {
    copyBtn.addEventListener("click", function () {
      var hidden = document.getElementById("indicator-src-hidden");
      var pre = document.getElementById("indicator-src");
      var text = (hidden && hidden.value) || (pre && pre.textContent) || "";
      navigator.clipboard.writeText(text).then(function () {
        copyBtn.textContent = "کپی شد ✓";
        setTimeout(function () {
          copyBtn.textContent = "کپی کل سورس";
        }, 2000);
      });
    });
  }

  var applyTv = document.getElementById("tv-settings-apply");
  if (applyTv) {
    applyTv.addEventListener("click", function () {
      var s = readSettingsFromForm();
      saveSettings(s);
      closeModals();
      refreshChart();
    });
  }

  root.querySelectorAll(".indicator-tf-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      tf = btn.getAttribute("data-tf") || "15m";
      root.querySelectorAll(".indicator-tf-btn").forEach(function (b) {
        b.classList.toggle("on", b === btn);
      });
      refreshChart();
    });
  });

  function refreshChart() {
    if (!mount || !indicatorId) return;
    if (hint) {
      hint.hidden = false;
      hint.textContent = "در حال بارگذاری چارت…";
    }
    var settings = readSettingsFromForm();
    saveSettings(settings);
    fetch("/api/indicators/" + indicatorId + "/live-chart", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ timeframe: tf, settings: settings }),
    })
      .then(function (r) {
        return r.json().then(function (j) {
          return { ok: r.ok, j: j };
        });
      })
      .then(function (res) {
        if (!res.ok || !res.j || !res.j.candles) {
          if (hint) hint.textContent = "دادهٔ کندل در دسترس نیست یا اجرای اندیکاتور ممکن نشد.";
          return;
        }
        if (hint) hint.hidden = true;
        if (window.IndicatorChart) {
          window.IndicatorChart.mount(mount, panesMount, res.j);
        }
      })
      .catch(function () {
        if (hint) hint.textContent = "خطا در بارگذاری چارت.";
      });
  }

  buildTvForm();
  refreshChart();
})();
