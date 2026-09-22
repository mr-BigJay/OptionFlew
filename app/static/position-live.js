(function () {
  var root = document.getElementById("pos-open-live");
  if (!root) return;

  var markEl = document.getElementById("pos-live-mark");
  var intervalMs = 4000;

  function fmtPnl(v) {
    if (v == null || Number.isNaN(v)) return "—";
    var n = Number(v);
    var s = (n >= 0 ? "+" : "") + n.toFixed(2);
    return s + " USDT";
  }

  function applyPnlClass(el, v) {
    el.classList.remove("pos", "neg");
    if (v == null) return;
    el.classList.add(Number(v) >= 0 ? "pos" : "neg");
  }

  function tick() {
    fetch("/position/api/live", { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (r) {
        if (!r.ok) throw new Error("live");
        return r.json();
      })
      .then(function (data) {
        if (markEl && data.mark != null) {
          markEl.textContent = Number(data.mark).toLocaleString("en-US", { maximumFractionDigits: 0 });
        }
        var byId = {};
        (data.positions || []).forEach(function (p) {
          byId[p.id] = p;
        });
        root.querySelectorAll("[data-pos-id]").forEach(function (card) {
          var id = Number(card.getAttribute("data-pos-id"));
          var p = byId[id];
          var pnlEl = card.querySelector(".pos-live-pnl");
          if (!pnlEl) return;
          if (!p) {
            card.classList.add("pos-trade-gone");
            return;
          }
          pnlEl.textContent = fmtPnl(p.pnl_usdt);
          applyPnlClass(pnlEl, p.pnl_usdt);
        });
        if (data.closed > 0) {
          var gone = root.querySelectorAll(".pos-trade-gone");
          if (gone.length) {
            window.setTimeout(function () {
              window.location.reload();
            }, 800);
          }
        }
        var badge = document.querySelector('.pos-seg a[href*="tab=open"] em');
        if (badge) {
          if (data.open_count > 0) badge.textContent = String(data.open_count);
          else badge.remove();
        } else if (data.open_count > 0) {
          var link = document.querySelector('.pos-seg a[href*="tab=open"]');
          if (link) {
            var em = document.createElement("em");
            em.textContent = String(data.open_count);
            link.appendChild(em);
          }
        }
      })
      .catch(function () {
        /* silent — next tick */
      });
  }

  tick();
  window.setInterval(tick, intervalMs);
})();
