(function () {
  function pctFa(n) {
    return new Intl.NumberFormat("fa-IR").format(Math.round(n)) + "٪";
  }

  function setBar(barEl, labelEl, pct, msg) {
    var p = Math.min(100, Math.max(0, pct));
    if (barEl) barEl.style.width = p + "%";
    if (labelEl) {
      var text = msg || "";
      if (text.indexOf("٪") === -1 && p > 0 && p < 100) {
        text = text ? text + " · " + pctFa(p) : pctFa(p);
      }
      labelEl.textContent = text || pctFa(p);
    }
  }

  function pollHistory() {
    fetch("/menu/candles/api/status")
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
          setTimeout(pollHistory, 800);
        } else {
          if (wrap.getAttribute("data-was-running") === "1") {
            window.location.href = "/menu/candles";
            return;
          }
          wrap.hidden = true;
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
    if (window.location.search.indexOf("dl=started") !== -1 || window.location.search.indexOf("dl=busy") !== -1) {
      if (histWrap) {
        histWrap.hidden = false;
        histWrap.setAttribute("data-was-running", "1");
      }
      pollHistory();
    }
  });
})();
