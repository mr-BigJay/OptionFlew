(function () {
  function pctFa(n) {
    return new Intl.NumberFormat("fa-IR").format(n) + "٪";
  }

  function setProgress(row, pct) {
    var bar = row.querySelector("[data-progress-bar]");
    var label = row.querySelector("[data-progress-label]");
    var p = Math.min(100, Math.max(0, pct || 0));
    if (bar) bar.style.width = p + "%";
    if (label) label.textContent = pctFa(p);
  }

  function applyRunRow(row, data) {
    if (!row || !data) return;
    var status = data.status;
    row.setAttribute("data-status", status);
    row.classList.remove("status-running", "status-done", "status-error", "status-cancelled");
    row.classList.add("status-" + status);

    if (status === "running") {
      setProgress(row, data.progress_pct);
      return;
    }

    var wrap = row.closest(".bt-archive-row-wrap");
    if (wrap) {
      var stopForm = wrap.querySelector(".bt-archive-stop-form");
      if (stopForm) stopForm.remove();
    }

    var body = row.querySelector(".bt-archive-body");
    if (!body) return;
    var prog = row.querySelector("[data-progress-wrap]");
    if (prog) prog.remove();

    var badge = row.querySelector(".bt-archive-badge");
    if (badge) {
      badge.classList.remove("running", "done", "error", "cancelled");
      if (status === "cancelled") {
        badge.textContent = "متوقف";
        badge.classList.add("cancelled");
      } else if (status === "error") {
        badge.textContent = "خطا";
        badge.classList.add("error");
      } else {
        badge.textContent = "تمام";
        badge.classList.add("done");
      }
    }

    if (body.querySelector("[data-stats-wrap]")) return;

    var stats = document.createElement("div");
    stats.className = "bt-archive-line3";
    stats.setAttribute("data-stats-wrap", "");
    if (status === "error" || status === "cancelled") {
      stats.innerHTML =
        '<span class="bt-stat-fail">' +
        (data.error_message
          ? String(data.error_message).slice(0, 80)
          : status === "cancelled"
            ? "متوقف توسط کاربر"
            : "اجرای بکتست ناموفق") +
        "</span>";
    } else {
      stats.innerHTML =
        '<span class="bt-stat-ok">موفق <bdi dir="ltr">' +
        (data.success_count || 0) +
        '</bdi></span> <span class="bt-stat-fail">ناموفق <bdi dir="ltr">' +
        (data.fail_count || 0) +
        '</bdi></span> <span class="muted">کل <bdi dir="ltr">' +
        (data.findings_count || 0) +
        "</bdi></span>";
    }
    body.appendChild(stats);
  }

  function pollArchive() {
    var rows = document.querySelectorAll(".bt-archive-row[data-status='running']");
    if (!rows.length) return;

    fetch("/backtest/api/runs")
      .then(function (r) {
        return r.json();
      })
      .then(function (payload) {
        var byId = {};
        (payload.runs || []).forEach(function (run) {
          byId[String(run.id)] = run;
        });
        rows.forEach(function (row) {
          var id = row.getAttribute("data-run-id");
          var data = byId[id];
          if (data) applyRunRow(row, data);
        });
        if (document.querySelector(".bt-archive-row[data-status='running']")) {
          setTimeout(pollArchive, 900);
        }
      })
      .catch(function () {
        setTimeout(pollArchive, 2000);
      });
  }

  document.addEventListener("DOMContentLoaded", function () {
    if (document.getElementById("bt-archive-list")) {
      pollArchive();
    }
  });
})();
