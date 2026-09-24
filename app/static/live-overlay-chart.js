(function () {
  "use strict";

  function readPayload(mount) {
    var id = mount.getAttribute("data-payload-id");
    if (!id) return null;
    var el = document.getElementById(id);
    if (!el) return null;
    try {
      return JSON.parse(el.textContent || "{}");
    } catch (e) {
      return null;
    }
  }

  function lineStyle(style) {
    if (style === "solid") return 0;
    if (style === "dotted") return 1;
    return 2;
  }

  function fmtNum(n) {
    return Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 2 });
  }

  function barCountBetween(candles, t0, t1) {
    if (!candles || !candles.length) return 0;
    var a = t0;
    var b = t1;
    if (a > b) {
      var tmp = a;
      a = b;
      b = tmp;
    }
    var n = 0;
    for (var i = 0; i < candles.length; i++) {
      var t = candles[i].time;
      if (t >= a && t <= b) n++;
    }
    return n;
  }

  function setupMeasure(chart, series, mount, payload) {
    var wrap = mount.closest(".live-ov-chart-wrap");
    if (!wrap) return;
    var payloadId = mount.getAttribute("data-payload-id");
    var btn = wrap.querySelector('[data-measure-for="' + payloadId + '"]');
    var readout = wrap.querySelector(".live-ov-measure-readout");
    if (!btn) return;

    var active = false;
    var ptA = null;
    var measureSeries = null;

    function clearLine() {
      if (measureSeries) {
        chart.removeSeries(measureSeries);
        measureSeries = null;
      }
    }

    function setReadout(text) {
      if (readout) readout.textContent = text || "";
    }

    btn.addEventListener("click", function () {
      active = !active;
      btn.classList.toggle("on", active);
      btn.setAttribute("aria-pressed", active ? "true" : "false");
      ptA = null;
      clearLine();
      if (active) {
        setReadout("نقطهٔ اول را روی چارت بزنید");
      } else {
        setReadout("");
      }
    });

    chart.subscribeClick(function (param) {
      if (!active || !param.point || param.time == null) return;
      var price = series.coordinateToPrice(param.point.y);
      if (price == null || !isFinite(price)) return;

      if (!ptA) {
        ptA = { time: param.time, price: price };
        clearLine();
        setReadout("نقطهٔ دوم را بزنید");
        return;
      }

      var ptB = { time: param.time, price: price };
      var t0 = ptA.time <= ptB.time ? ptA.time : ptB.time;
      var t1 = ptA.time <= ptB.time ? ptB.time : ptA.time;
      var p0 = ptA.time <= ptB.time ? ptA.price : ptB.price;
      var p1 = ptA.time <= ptB.time ? ptB.price : ptA.price;
      var dPrice = p1 - p0;
      var pct = p0 !== 0 ? (dPrice / p0) * 100 : 0;
      var bars = barCountBetween(payload.candles, t0, t1);
      var sign = dPrice >= 0 ? "+" : "−";

      clearLine();
      measureSeries = chart.addLineSeries({
        color: "#a78bfa",
        lineWidth: 2,
        lineStyle: 0,
        crosshairMarkerVisible: true,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      measureSeries.setData([
        { time: t0, value: p0 },
        { time: t1, value: p1 },
      ]);

      setReadout(
        sign +
          fmtNum(dPrice) +
          " USDT (" +
          sign +
          Math.abs(pct).toFixed(2) +
          "٪) · " +
          bars +
          " کندل"
      );
      ptA = null;
    });
  }

  function initMount(mount) {
    if (mount.dataset.liveChartReady === "1") return;
    var payload = readPayload(mount);
    if (!payload || !payload.candles || !payload.candles.length) return;
    if (typeof LightweightCharts === "undefined") return;

    mount.dataset.liveChartReady = "1";
    var w = mount.clientWidth || 320;
    var chart = LightweightCharts.createChart(mount, {
      width: w,
      height: Math.max(300, mount.clientHeight || 360),
      layout: {
        background: { color: "#121a26" },
        textColor: "#90a4ae",
      },
      grid: {
        vertLines: { color: "rgba(42,52,65,0.6)" },
        horzLines: { color: "rgba(42,52,65,0.6)" },
      },
      rightPriceScale: { borderColor: "#2a3441" },
      timeScale: { borderColor: "#2a3441", timeVisible: true, secondsVisible: false },
    });

    var series = chart.addCandlestickSeries({
      upColor: "#34d399",
      downColor: "#f87171",
      borderVisible: false,
      wickUpColor: "#34d399",
      wickDownColor: "#f87171",
    });
    series.setData(payload.candles);

    var ov = payload.overlays || {};
    (ov.hlines || []).forEach(function (hl) {
      if (!hl || typeof hl.price !== "number") return;
      series.createPriceLine({
        price: hl.price,
        color: hl.color || "#78909c",
        lineWidth: 1,
        lineStyle: lineStyle(hl.style),
        axisLabelVisible: true,
        title: hl.label || "",
      });
    });

    (ov.segments || []).forEach(function (seg) {
      if (!seg || seg.t0 == null) return;
      var ls = chart.addLineSeries({
        color: seg.color || "#ef5350",
        lineWidth: seg.width != null ? seg.width : 1,
        lineStyle: 0,
        crosshairMarkerVisible: false,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      ls.setData([
        { time: seg.t0, value: seg.p0 },
        { time: seg.t1, value: seg.p1 },
      ]);
    });

    (ov.lines || []).forEach(function (ln) {
      if (!ln || !ln.points || !ln.points.length) return;
      var ls = chart.addLineSeries({
        color: ln.color || "#ffb74d",
        lineWidth: ln.width != null ? ln.width : 1,
        lineStyle: 0,
        crosshairMarkerVisible: false,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      ls.setData(ln.points);
    });

    if (ov.markers && ov.markers.length) {
      series.setMarkers(ov.markers);
    }

    function applyViewport() {
      var vp = payload.viewport;
      if (vp && vp.priceMin != null && vp.priceMax != null) {
        series.applyOptions({
          autoscaleInfoProvider: function () {
            return {
              priceRange: {
                minValue: vp.priceMin,
                maxValue: vp.priceMax,
              },
            };
          },
        });
      }
      if (vp && vp.fitTime) {
        chart.timeScale().fitContent();
        return;
      }
      if (!vp || vp.from == null || vp.to == null) {
        chart.timeScale().fitContent();
        return;
      }
      try {
        chart.timeScale().setVisibleRange({
          from: vp.from,
          to: vp.to,
        });
      } catch (e) {
        chart.timeScale().fitContent();
      }
    }

    requestAnimationFrame(function () {
      requestAnimationFrame(applyViewport);
    });

    setupMeasure(chart, series, mount, payload);

    var pollUrl = mount.getAttribute("data-poll-url");
    if (pollUrl) {
      window.setInterval(function () {
        fetch(pollUrl, { credentials: "same-origin" })
          .then(function (r) {
            return r.ok ? r.json() : null;
          })
          .then(function (data) {
            if (!data || !data.candles) return;
            series.setData(data.candles);
            if (data.mark != null && typeof data.mark === "number") {
              /* mark line refresh omitted — full reload would duplicate price lines */
            }
          })
          .catch(function () {});
      }, 45000);
    }

    window.addEventListener(
      "resize",
      function () {
        chart.applyOptions({ width: mount.clientWidth });
      },
      { passive: true }
    );
  }

  function boot() {
    document.querySelectorAll("[data-live-overlay-chart]").forEach(initMount);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
