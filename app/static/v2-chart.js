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

  function tehranParts(time) {
    var sec = typeof time === "number" ? time : time && time.timestamp;
    if (!sec) return null;
    var d = new Date(sec * 1000);
    return {
      date: new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
        timeZone: "Asia/Tehran",
        month: "numeric",
        day: "numeric",
      }).format(d),
      clock: new Intl.DateTimeFormat("en-GB", {
        timeZone: "Asia/Tehran",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }).format(d),
    };
  }

  function formatAxisTime(time, withDate) {
    var p = tehranParts(time);
    if (!p) return "";
    return withDate ? p.date + " " + p.clock : p.clock;
  }

  mount.style.direction = "ltr";
  var chart = LightweightCharts.createChart(mount, {
    autoSize: true,
    layout: {
      background: { color: "#121a26" },
      textColor: "#90a4ae",
      attributionLogo: false,
    },
    grid: {
      vertLines: { color: "rgba(42,52,65,0.6)" },
      horzLines: { color: "rgba(42,52,65,0.6)" },
    },
    rightPriceScale: {
      borderColor: "#2a3441",
      scaleMargins: { top: 0.08, bottom: 0.08 },
    },
    localization: {
      locale: "fa-IR",
      timeFormatter: function (time) {
        return formatAxisTime(time, true);
      },
    },
    timeScale: {
      borderColor: "#2a3441",
      visible: true,
      timeVisible: true,
      secondsVisible: false,
      rightOffset: 4,
      fixLeftEdge: true,
      tickMarkFormatter: function (time, tickMarkType) {
        return formatAxisTime(time, tickMarkType < 3);
      },
    },
  });

  var candles = chart.addCandlestickSeries({
    upColor: "#34d399",
    downColor: "#f87171",
    borderVisible: false,
    wickUpColor: "#34d399",
    wickDownColor: "#f87171",
  });
  var nearLine = chart.addLineSeries({
    color: "rgba(255,183,77,0.55)",
    lineWidth: 2,
    lineStyle: 2,
    priceLineVisible: false,
    lastValueVisible: true,
    crosshairMarkerVisible: false,
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

  function barStepSec(rows) {
    if (rows.length < 2) return 900;
    var d = rows[1].time - rows[0].time;
    return d > 0 ? d : 900;
  }

  function withFutureWhitespace(rows, pts, nearPts) {
    if (!rows.length) return rows;
    var step = barStepSec(rows);
    var lastT = rows[rows.length - 1].time;
    var endT = lastT;
    [pts, nearPts].forEach(function (series) {
      if (series.length >= 2) {
        endT = Math.max(endT, series[series.length - 1].time);
      }
    });
    if (endT <= lastT) return rows.slice();
    var out = rows.slice();
    var seen = {};
    out.forEach(function (c) {
      seen[c.time] = 1;
    });
    var t = lastT + step;
    while (t <= endT + step) {
      if (!seen[t]) out.push({ time: t });
      t += step;
    }
    return out;
  }

  function applyViewport(rows, pts, nearPts) {
    if (!rows.length) return;
    var step = barStepSec(rows);
    var end = rows.length - 1;
    var lineBars = 0;
    var lastT = rows[rows.length - 1].time;
    [pts, nearPts].forEach(function (series) {
      if (series.length >= 2) {
        var endT = series[series.length - 1].time;
        lineBars = Math.max(lineBars, Math.ceil((endT - lastT) / step));
      }
    });
    lineBars = Math.max(8, lineBars);
    var to = end + lineBars;
    var plotW = Math.max(280, mount.clientWidth || 320);
    var barsInView = Math.max(1, to + 1);
    var spacing = Math.max(3, Math.min(14, (plotW - 56) / barsInView));
    chart.timeScale().applyOptions({
      barSpacing: spacing,
      rightOffset: 4,
      fixLeftEdge: true,
      timeVisible: true,
      visible: true,
    });
    chart.timeScale().setVisibleLogicalRange({ from: 0, to: to });
  }

  function paint(data) {
    var rows = ((data && data.candles) || []).slice();
    var pts = (data && data.line) || [];
    var nearPts = (data && data.near_line) || [];
    var displayRows = withFutureWhitespace(rows, pts, nearPts);
    priceLo = Infinity;
    priceHi = -Infinity;
    rows.forEach(function (c) {
      if (typeof c.low === "number") priceLo = Math.min(priceLo, c.low);
      if (typeof c.high === "number") priceHi = Math.max(priceHi, c.high);
    });
    [pts, nearPts].forEach(function (series) {
      series.forEach(function (p) {
        if (typeof p.value === "number") {
          priceLo = Math.min(priceLo, p.value);
          priceHi = Math.max(priceHi, p.value);
        }
      });
    });
    if (!isFinite(priceLo) || !isFinite(priceHi)) {
      priceLo = 0;
      priceHi = 1;
    }
    candles.setData(displayRows);
    nearLine.setData(nearPts.length >= 2 ? nearPts : []);
    line.setData(pts.length >= 2 ? pts : []);
    if (captionEl && data && data.caption) captionEl.textContent = data.caption;
    applyViewport(displayRows, pts, nearPts);
  }

  paint(payload);

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
