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

  function nearestCandle(candles, time) {
    if (!candles || !candles.length) return null;
    var best = candles[0];
    var bestD = Math.abs(best.time - time);
    for (var i = 1; i < candles.length; i++) {
      var d = Math.abs(candles[i].time - time);
      if (d < bestD) {
        bestD = d;
        best = candles[i];
      }
    }
    return best;
  }

  function snapToCandle(candle, price) {
    var o = candle.open;
    var h = candle.high;
    var l = candle.low;
    var c = candle.close;
    var best = o;
    if (Math.abs(h - price) < Math.abs(best - price)) best = h;
    if (Math.abs(l - price) < Math.abs(best - price)) best = l;
    if (Math.abs(c - price) < Math.abs(best - price)) best = c;
    return { time: candle.time, price: best };
  }

  function candleStepSec(candles) {
    if (!candles || candles.length < 2) return 300;
    return Math.max(60, Math.abs(candles[1].time - candles[0].time));
  }

  function durationFa(candles, t0, t1) {
    var a = Math.min(t0, t1);
    var b = Math.max(t0, t1);
    var bars = barCountBetween(candles, a, b);
    if (bars <= 1) return "1 کندل";
    var sec = candleStepSec(candles) * (bars - 1);
    if (sec < 3600) return bars + " کندل · " + Math.round(sec / 60) + " دقیقه";
    if (sec < 86400) {
      var h = Math.floor(sec / 3600);
      var m = Math.round((sec % 3600) / 60);
      return bars + " کندل · " + h + "س " + (m > 0 ? m + "د" : "");
    }
    return bars + " کندل · " + Math.round(sec / 86400) + " روز";
  }

  function measureReadout(candles, p0, p1, t0, t1) {
    var dPrice = p1 - p0;
    var pct = p0 !== 0 ? (dPrice / p0) * 100 : 0;
    var sign = dPrice >= 0 ? "+" : "−";
    return (
      sign +
      fmtNum(dPrice) +
      " (" +
      sign +
      Math.abs(pct).toFixed(2) +
      "%) · " +
      durationFa(candles, t0, t1)
    );
  }

  function timeToUnix(t) {
    if (typeof t === "number") return t;
    return null;
  }

  function setupMeasure(chart, series, mount, payload) {
    var wrap = mount.closest(".live-ov-chart-wrap");
    if (!wrap) return;
    var payloadId = mount.getAttribute("data-payload-id");
    var btn = wrap.querySelector('[data-measure-for="' + payloadId + '"]');
    var readout = wrap.querySelector(".live-ov-measure-readout");
    if (!btn) return;

    var candles = payload.candles || [];
    var active = false;
    var dragging = false;
    var startPt = null;
    var lastCross = null;
    var lineSeries = null;
    var bandTop = null;
    var bandBot = null;

    function setPanZoom(enabled) {
      chart.applyOptions({
        handleScroll: enabled,
        handleScale: enabled,
      });
    }

    function removeSeries(ref) {
      if (ref) {
        chart.removeSeries(ref);
      }
      return null;
    }

    function clearGraphics() {
      lineSeries = removeSeries(lineSeries);
      bandTop = removeSeries(bandTop);
      bandBot = removeSeries(bandBot);
    }

    function setReadout(text) {
      if (readout) readout.textContent = text || "";
    }

    function pointFromXY(x, y) {
      var ts = chart.timeScale();
      var time = null;
      if (typeof ts.coordinateToTime === "function") {
        time = ts.coordinateToTime(x);
      }
      if (time == null && typeof ts.coordinateToLogical === "function") {
        var logical = ts.coordinateToLogical(x);
        if (logical != null && typeof series.dataByIndex === "function") {
          var bar = series.dataByIndex(Math.round(logical));
          if (bar) time = bar.time;
        }
      }
      var tUnix = timeToUnix(time);
      if (tUnix == null) return null;
      var price = series.coordinateToPrice(y);
      if (price == null || !isFinite(price)) return null;
      var candle = nearestCandle(candles, tUnix);
      if (!candle) return null;
      return snapToCandle(candle, price);
    }

    function pointFromClient(clientX, clientY) {
      var rect = mount.getBoundingClientRect();
      return pointFromXY(clientX - rect.left, clientY - rect.top);
    }

    function pointFromCrosshair(param) {
      if (!param || param.time == null || !param.point) return null;
      return pointFromXY(param.point.x, param.point.y);
    }

    function ensureLineSeries(color, style, width) {
      return chart.addLineSeries({
        color: color,
        lineWidth: width,
        lineStyle: style,
        crosshairMarkerVisible: false,
        priceLineVisible: false,
        lastValueVisible: false,
      });
    }

    function drawMeasure(a, b) {
      if (!a || !b) return;
      var t0 = a.time <= b.time ? a.time : b.time;
      var t1 = a.time <= b.time ? b.time : a.time;
      var p0 = a.time <= b.time ? a.price : b.price;
      var p1 = a.time <= b.time ? b.price : a.price;
      var pHi = Math.max(p0, p1);
      var pLo = Math.min(p0, p1);
      var up = p1 >= p0;
      var col = up ? "#34d399" : "#f87171";
      var bandCol = up ? "rgba(52, 211, 153, 0.7)" : "rgba(248, 113, 113, 0.7)";

      if (!lineSeries) lineSeries = ensureLineSeries(col, 0, 2);
      else lineSeries.applyOptions({ color: col });
      lineSeries.setData([
        { time: t0, value: a.time <= b.time ? a.price : b.price },
        { time: t1, value: a.time <= b.time ? b.price : a.price },
      ]);

      if (!bandBot) bandBot = ensureLineSeries(bandCol, 2, 1);
      else bandBot.applyOptions({ color: bandCol });
      if (!bandTop) bandTop = ensureLineSeries(bandCol, 2, 1);
      else bandTop.applyOptions({ color: bandCol });
      bandBot.setData([
        { time: t0, value: pLo },
        { time: t1, value: pLo },
      ]);
      bandTop.setData([
        { time: t0, value: pHi },
        { time: t1, value: pHi },
      ]);

      setReadout(measureReadout(candles, p0, p1, t0, t1));
    }

    function deactivate() {
      active = false;
      dragging = false;
      startPt = null;
      btn.classList.remove("on");
      btn.setAttribute("aria-pressed", "false");
      wrap.classList.remove("measure-on");
      setPanZoom(true);
      clearGraphics();
      setReadout("");
    }

    chart.subscribeCrosshairMove(function (param) {
      if (param.time != null && param.point) lastCross = param;
      if (dragging && startPt && param.time != null && param.point) {
        var end = pointFromCrosshair(param);
        if (end) drawMeasure(startPt, end);
      }
    });

    btn.addEventListener("click", function (e) {
      e.preventDefault();
      if (active) {
        deactivate();
        return;
      }
      active = true;
      btn.classList.add("on");
      btn.setAttribute("aria-pressed", "true");
      wrap.classList.add("measure-on");
      clearGraphics();
      setPanZoom(false);
      setReadout("کلیک و بکشید روی چارت");
    });

    function onPointerDown(e) {
      if (!active || e.button !== 0) return;
      var pt = pointFromClient(e.clientX, e.clientY) || pointFromCrosshair(lastCross);
      if (!pt) {
        setReadout("اول نشانگر را روی چارت بگذارید، بعد کلیک و بکشید");
        return;
      }
      e.preventDefault();
      e.stopPropagation();
      dragging = true;
      startPt = pt;
      if (mount.setPointerCapture) mount.setPointerCapture(e.pointerId);
      drawMeasure(startPt, startPt);
    }

    function onPointerMove(e) {
      if (!dragging || !startPt) return;
      var pt = pointFromClient(e.clientX, e.clientY) || pointFromCrosshair(lastCross);
      if (pt) drawMeasure(startPt, pt);
    }

    function onPointerUp(e) {
      if (!dragging) return;
      dragging = false;
      try {
        if (mount.releasePointerCapture) mount.releasePointerCapture(e.pointerId);
      } catch (err) {
        /* ignore */
      }
      if (startPt) {
        var pt = pointFromClient(e.clientX, e.clientY) || pointFromCrosshair(lastCross);
        if (pt) drawMeasure(startPt, pt);
      }
      startPt = null;
    }

    mount.addEventListener("pointerdown", onPointerDown, true);
    mount.addEventListener("pointermove", onPointerMove, true);
    mount.addEventListener("pointerup", onPointerUp, true);
    mount.addEventListener("pointercancel", onPointerUp, true);

    window.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && active) deactivate();
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
