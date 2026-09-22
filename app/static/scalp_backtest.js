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
    fetch("/scalp/backtest/api/run/" + runId)
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        var wrap = document.getElementById("bt-run-progress");
        var bar = document.getElementById("bt-run-bar");
        var label = document.getElementById("bt-run-label");
        if (!wrap) return;
        wrap.hidden = false;
        setBar(bar, label, data.progress_pct || 0, pctFa(data.progress_pct || 0));
        if (data.status === "running") {
          setTimeout(function () {
            pollRun(runId);
          }, 800);
        } else {
          var sid =
            new URLSearchParams(window.location.search).get("scenario_id") ||
            "range_break";
          window.location.href =
            "/scalp/backtest?scenario_id=" +
            encodeURIComponent(sid) +
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
