(function () {
  function pctFa(n) {
    return new Intl.NumberFormat("fa-IR").format(n) + "٪";
  }

  function setBar(barEl, labelEl, pct, msg) {
    if (barEl) barEl.style.width = Math.min(100, Math.max(0, pct)) + "%";
    if (labelEl) labelEl.textContent = msg || pctFa(pct);
  }

  function pollRun(runId) {
    if (!runId) return;
    fetch("/backtest/api/run/" + runId)
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        var wrap = document.getElementById("bt-run-progress");
        var bar = document.getElementById("bt-run-bar");
        var label = document.getElementById("bt-run-label");
        if (!wrap) return;
        wrap.hidden = false;
        var pct = data.progress_pct || 0;
        var msg = pctFa(pct);
        if (data.status === "running" && pct >= 40 && pct < 100) {
          msg = pctFa(pct) + " · پردازش/نمودار";
        }
        setBar(bar, label, pct, msg);
        if (data.status === "running") {
          setTimeout(function () {
            pollRun(runId);
          }, 800);
        } else {
          window.location.href =
            "/backtest?tab=" +
            encodeURIComponent(new URLSearchParams(window.location.search).get("tab") || "triangle") +
            "&run_id=" +
            runId;
        }
      })
      .catch(function () {});
  }

  document.addEventListener("DOMContentLoaded", function () {
    var runWrap = document.getElementById("bt-run-progress");
    var runId = runWrap && runWrap.getAttribute("data-run-id");
    if (runId && runId !== "0") {
      var activeRun = document.querySelector(".bt-finding");
      if (!activeRun) {
        pollRun(runId);
      }
    }
  });
})();
