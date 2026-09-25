(function () {
  "use strict";

  function lineStyle(style) {
    if (style === "solid") return 0;
    if (style === "dotted") return 1;
    return 2;
  }

  function baseChartOptions(width, height) {
    return {
      width: width,
      height: height,
      layout: { background: { color: "#121a26" }, textColor: "#90a4ae" },
      grid: {
        vertLines: { color: "rgba(42,52,65,0.6)" },
        horzLines: { color: "rgba(42,52,65,0.6)" },
      },
      rightPriceScale: { borderColor: "#2a3441" },
      timeScale: {
        borderColor: "#2a3441",
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 6,
      },
    };
  }

  function applyOverlays(chart, candleSeries, overlays) {
    var ov = overlays || {};
    (ov.hlines || []).forEach(function (hl) {
      if (!hl || typeof hl.price !== "number") return;
      candleSeries.createPriceLine({
        price: hl.price,
        color: hl.color || "#78909c",
        lineWidth: 1,
        lineStyle: lineStyle(hl.style),
        axisLabelVisible: true,
        title: hl.label || "",
      });
    });
    (ov.lines || []).forEach(function (ln) {
      if (!ln || !ln.points || !ln.points.length) return;
      var ls = chart.addLineSeries({
        color: ln.color || "#42a5f5",
        lineWidth: ln.width != null ? ln.width : 1,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      ls.setData(ln.points);
    });
  }

  function mountIndicatorChart(mount, panesMount, payload) {
    if (!mount || !payload || !payload.candles || !payload.candles.length) return null;
    if (typeof LightweightCharts === "undefined") return null;
    mount.innerHTML = "";
    if (panesMount) panesMount.innerHTML = "";

    var w = mount.clientWidth || 320;
    var mainH = Math.max(240, Math.min(360, window.innerHeight * 0.38));
    var chart = LightweightCharts.createChart(mount, baseChartOptions(w, mainH));
    var candles = chart.addCandlestickSeries({
      upColor: "#26a69a",
      downColor: "#ef5350",
      borderVisible: false,
      wickUpColor: "#26a69a",
      wickDownColor: "#ef5350",
      priceLineVisible: false,
      lastValueVisible: true,
    });
    candles.setData(payload.candles);
    applyOverlays(chart, candles, payload.overlays);

    var charts = [chart];
    (payload.panes || []).forEach(function (pane, idx) {
      if (!panesMount) return;
      var wrap = document.createElement("div");
      wrap.className = "indicator-pane-wrap";
      panesMount.appendChild(wrap);
      var ph = Math.max(100, Math.min(160, window.innerHeight * 0.18));
      var pc = LightweightCharts.createChart(wrap, baseChartOptions(w, ph));
      charts.push(pc);
      (pane.series || []).forEach(function (ser) {
        var ls = pc.addLineSeries({
          color: ser.color || "#7E57C2",
          lineWidth: 2,
          title: ser.name || pane.label || "",
          priceLineVisible: false,
          lastValueVisible: true,
        });
        ls.setData(ser.points || []);
      });
      (pane.levels || []).forEach(function (lv) {
        pc.addLineSeries({
          color: "rgba(120,144,156,0.45)",
          lineWidth: 1,
          lineStyle: 2,
          priceLineVisible: false,
          lastValueVisible: false,
        }).setData([
          { time: payload.candles[0].time, value: lv },
          { time: payload.candles[payload.candles.length - 1].time, value: lv },
        ]);
      });
      if (pane.min != null && pane.max != null) {
        pc.priceScale("right").applyOptions({
          autoScale: false,
          scaleMargins: { top: 0.08, bottom: 0.08 },
        });
      }
    });

    chart.timeScale().fitContent();
    charts.slice(1).forEach(function (c) {
      c.timeScale().fitContent();
    });

    function sync(from, toList) {
      from.timeScale().subscribeVisibleLogicalRangeChange(function (range) {
        toList.forEach(function (other) {
          if (other !== from) other.timeScale().setVisibleLogicalRange(range);
        });
      });
    }
    sync(chart, charts.slice(1));

    if (typeof ResizeObserver !== "undefined") {
      new ResizeObserver(function () {
        var nw = mount.clientWidth || w;
        charts.forEach(function (c) {
          c.applyOptions({ width: nw });
        });
      }).observe(mount);
    }

    return { main: chart, all: charts };
  }

  window.IndicatorChart = { mount: mountIndicatorChart };
})();
