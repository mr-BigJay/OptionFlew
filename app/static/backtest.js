(function () {
  function pctFa(n) {
    return new Intl.NumberFormat("fa-IR").format(n) + "٪";
  }

  function setBar(barEl, labelEl, pct, msg) {
    if (barEl) barEl.style.width = Math.min(100, Math.max(0, pct)) + "%";
    if (labelEl) labelEl.textContent = msg || pctFa(pct);
  }

  function pollHistory() {
    fetch("/backtest/api/history")
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        var dl = data.download || {};
        var wrap = document.getElementById("history-dl-progress");
        if (!wrap) return;
        if (dl.running) {
          wrap.hidden = false;
          setBar(
            document.getElementById("history-dl-bar"),
            document.getElementById("history-dl-label"),
            dl.progress_pct || 0,
            dl.message || ""
          );
          setTimeout(pollHistory, 1500);
        } else {
          if (wrap.getAttribute("data-was-running") === "1") {
            window.location.href = "/backtest";
          }
          wrap.hidden = true;
        }
      })
      .catch(function () {});
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
    var histWrap = document.getElementById("history-dl-progress");
    if (histWrap && !histWrap.hidden) {
      histWrap.setAttribute("data-was-running", "1");
      pollHistory();
    }
    if (window.location.search.indexOf("dl=started") !== -1) {
      if (histWrap) {
        histWrap.hidden = false;
        histWrap.setAttribute("data-was-running", "1");
      }
      pollHistory();
    }

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
