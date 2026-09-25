(function () {
  "use strict";

  var mount = document.getElementById("v2-chart");
  var payloadEl = document.getElementById("v2-payload");
  var captionEl = document.getElementById("v2-caption");
  if (!mount || !payloadEl || typeof LightweightCharts === "undefined") return;

  var payload = {};
  try {
    payload = JSON.parse(payloadEl.textContent || "{}");
  } catch (e) {
    payload = {};
  }

  mount.style.direction = "ltr";
  var chart = LightweightCharts.createChart(mount, {
    width: Math.max(280, mount.clientWidth || 320),
    height: Math.max(280, mount.clientHeight || 420),
    layout: {
      background: { color: "#121a26" },
      textColor: "#90a4ae",
    },
    grid: {
      vertLines: { color: "rgba(42,52,65,0.6)" },
      horzLines: { color: "rgba(42,52,65,0.6)" },
    },
    rightPriceScale: {
      borderColor: "#2a3441",
      scaleMargins: { top: 0.08, bottom: 0.08 },
    },
    timeScale: {
      borderColor: "#2a3441",
      timeVisible: true,
      secondsVisible: false,
      rightOffset: 2,
    },
  });

  var candles = chart.addCandlestickSeries({
    upColor: "#34d399",
    downColor: "#f87171",
    borderVisible: false,
    wickUpColor: "#34d399",
    wickDownColor: "#f87171",
  });
  var line = chart.addLineSeries({
    color: "#ffb74d",
    lineWidth: 2,
    priceLineVisible: false,
    lastValueVisible: true,
    crosshairMarkerVisible: false,
  });

  var priceLo = 0;
  var priceHi = 1;

  candles.applyOptions({
    autoscaleInfoProvider: function () {
      var pad = Math.max((priceHi - priceLo) * 0.08, 20);
      return {
        priceRange: {
          minValue: priceLo - pad,
          maxValue: priceHi + pad,
        },
      };
    },
  });

  function paint(data) {
    var rows = ((data && data.candles) || []).slice();
    var pts = (data && data.line) || [];
    priceLo = Infinity;
    priceHi = -Infinity;
    rows.forEach(function (c) {
      if (typeof c.low === "number") priceLo = Math.min(priceLo, c.low);
      if (typeof c.high === "number") priceHi = Math.max(priceHi, c.high);
    });
    pts.forEach(function (p) {
      if (typeof p.value === "number") {
        priceLo = Math.min(priceLo, p.value);
        priceHi = Math.max(priceHi, p.value);
      }
    });
    if (!isFinite(priceLo) || !isFinite(priceHi)) {
      priceLo = 0;
      priceHi = 1;
    }
    if (pts.length && rows.length && rows[rows.length - 1].time < pts[pts.length - 1].time) {
      rows.push({ time: pts[pts.length - 1].time });
    }
    candles.setData(rows);
    line.setData(pts.length >= 2 ? pts : []);
    if (captionEl && data && data.caption) captionEl.textContent = data.caption;
    chart.timeScale().fitContent();
  }

  function resize() {
    chart.applyOptions({
      width: Math.max(280, mount.clientWidth || 320),
      height: Math.max(280, mount.clientHeight || 420),
    });
  }

  paint(payload);
  window.addEventListener("resize", resize, { passive: true });

  window.setInterval(function () {
    fetch("/api/v2/chart", { credentials: "same-origin" })
      .then(function (r) {
        return r.ok ? r.json() : null;
      })
      .then(function (data) {
        if (data) paint(data);
      })
      .catch(function () {});
  }, 60000);
})();
