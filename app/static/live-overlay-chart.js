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

  function timeToUnix(t) {
    if (typeof t === "number") return t;
    return null;
  }

  function formatSignedNum(n, digits) {
    var d = digits != null ? digits : 2;
    var abs = Math.abs(n).toLocaleString("en-US", {
      minimumFractionDigits: d,
      maximumFractionDigits: d,
    });
    if (n > 0) return abs;
    if (n < 0) return "−" + abs;
    return abs;
  }

  function formatDurationTv(sec) {
    var s = Math.round(sec);
    if (s === 0) return "0";
    var sign = s < 0 ? "−" : "";
    s = Math.abs(s);
    if (s < 3600) return sign + Math.max(1, Math.round(s / 60)) + "m";
    if (s < 86400) return sign + Math.round(s / 3600) + "h";
    return sign + Math.round(s / 86400) + "d";
  }

  function setupMeasure(chart, series, mount, payload) {
    var wrap = mount.closest(".live-ov-chart-wrap");
    if (!wrap) return;
    var inner = mount.closest(".live-ov-chart-inner");
    if (!inner && mount.parentNode) {
      inner = document.createElement("div");
      inner.className = "live-ov-chart-inner";
      mount.parentNode.insertBefore(inner, mount);
      inner.appendChild(mount);
    }
    if (!inner) return;
    var payloadId = mount.getAttribute("data-payload-id");
    var btn = wrap.querySelector('[data-measure-for="' + payloadId + '"]');
    var readout = wrap.querySelector(".live-ov-measure-readout");
    if (!btn) return;

    var candles = payload.candles || [];
    var active = false;
    var dragging = false;
    var savedA = null;
    var savedB = null;
    var markerId = "live-ov-arr-" + String(payloadId).replace(/[^a-zA-Z0-9_-]/g, "");

    var layer = inner.querySelector(".live-ov-measure-layer");
    if (!layer) {
      layer = document.createElement("div");
      layer.className = "live-ov-measure-layer";
      layer.setAttribute("aria-hidden", "true");
      inner.appendChild(layer);
    }

    var shade = document.createElement("div");
    shade.className = "live-ov-measure-shade";
    shade.style.display = "none";
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    var hLine = document.createElementNS("http://www.w3.org/2000/svg", "line");
    var vLine = document.createElementNS("http://www.w3.org/2000/svg", "line");
    svg.appendChild(hLine);
    svg.appendChild(vLine);
    shade.appendChild(svg);
    var tag = document.createElement("div");
    tag.className = "live-ov-measure-tag";
    layer.appendChild(shade);
    layer.appendChild(tag);

    var stepSec = candleStepSec(candles);

    function setPanZoom(enabled) {
      chart.applyOptions({
        handleScroll: enabled,
        handleScale: enabled,
      });
    }

    function setReadout(text) {
      if (readout) readout.textContent = text || "";
    }

    function hideMeasure() {
      shade.style.display = "none";
      tag.textContent = "";
      tag.className = "live-ov-measure-tag";
      savedA = null;
      savedB = null;
    }

    function plotWidth() {
      var ts = chart.timeScale();
      if (typeof ts.width === "function") {
        var pw = ts.width();
        if (pw > 0) return pw;
      }
      return mount.clientWidth || 1;
    }

    function plotHeight() {
      return mount.clientHeight || 1;
    }

    function clientToPixel(clientX, clientY) {
      var rect = mount.getBoundingClientRect();
      var pw = plotWidth();
      var ph = plotHeight();
      return {
        x: Math.max(0, Math.min(pw, clientX - rect.left)),
        y: Math.max(0, Math.min(ph, clientY - rect.top)),
      };
    }

    function extrapolateTime(x, pw) {
      var ts = chart.timeScale();
      var vis = ts.getVisibleRange && ts.getVisibleRange();
      if (!vis) return null;
      var tFrom = timeToUnix(vis.from);
      var tTo = timeToUnix(vis.to);
      if (tFrom == null || tTo == null) return null;
      var frac = pw > 0 ? x / pw : 0;
      return Math.round(tFrom + (tTo - tFrom) * frac);
    }

    function dataFromPixel(x, y) {
      var ts = chart.timeScale();
      var pw = plotWidth();
      var ph = plotHeight();
      x = Math.max(0, Math.min(pw, x));
      y = Math.max(0, Math.min(ph, y));

      var price = series.coordinateToPrice(y);
      if (price == null || !isFinite(price)) return null;

      var logical = typeof ts.coordinateToLogical === "function" ? ts.coordinateToLogical(x) : null;
      var time = null;
      if (typeof ts.coordinateToTime === "function") {
        time = ts.coordinateToTime(x);
      }
      if (time == null && logical != null && typeof series.dataByIndex === "function") {
        var bar = series.dataByIndex(Math.round(logical));
        if (bar) time = bar.time;
      }
      if (time == null && logical != null && typeof ts.coordinateToLogical === "function") {
        var logL = ts.coordinateToLogical(0);
        var logR = ts.coordinateToLogical(pw);
        if (logL != null && logR != null && logR !== logL) {
          var frac = x / pw;
          logical = logL + (logR - logL) * frac;
          if (typeof series.dataByIndex === "function") {
            var bar2 = series.dataByIndex(Math.round(logical));
            if (bar2) time = bar2.time;
          }
        }
      }
      var tUnix = timeToUnix(time);
      if (tUnix == null) tUnix = extrapolateTime(x, pw);
      if (tUnix == null) return null;
      return { time: tUnix, price: price, logical: logical };
    }

    function pointFromClient(clientX, clientY) {
      var px = clientToPixel(clientX, clientY);
      return dataFromPixel(px.x, px.y);
    }

    function pixelOf(pt) {
      var x = chart.timeScale().timeToCoordinate(pt.time);
      var y = series.priceToCoordinate(pt.price);
      if (x == null || y == null) return null;
      return { x: x, y: y };
    }

    function paintMeasureBox(pxA, pxB, dataA, dataB) {
      var left = Math.min(pxA.x, pxB.x);
      var right = Math.max(pxA.x, pxB.x);
      var top = Math.min(pxA.y, pxB.y);
      var bottom = Math.max(pxA.y, pxB.y);
      var w = Math.max(1, right - left);
      var h = Math.max(1, bottom - top);

      var priceA =
        dataA && isFinite(dataA.price) ? dataA.price : series.coordinateToPrice(pxA.y);
      var priceB =
        dataB && isFinite(dataB.price) ? dataB.price : series.coordinateToPrice(pxB.y);
      if (priceA == null || priceB == null || !isFinite(priceA) || !isFinite(priceB)) return;

      var dPrice = priceB - priceA;
      var pct = priceA !== 0 ? (dPrice / priceA) * 100 : 0;
      var up = dPrice >= 0;
      var theme = up ? "up" : "down";
      var stroke = up ? "rgba(41, 98, 255, 0.95)" : "rgba(239, 83, 80, 0.95)";

      var ts = chart.timeScale();
      var l0 =
        dataA && dataA.logical != null
          ? dataA.logical
          : ts.coordinateToLogical(pxA.x);
      var l1 =
        dataB && dataB.logical != null
          ? dataB.logical
          : ts.coordinateToLogical(pxB.x);
      if (l0 == null) l0 = 0;
      if (l1 == null) l1 = 0;
      var dBars = Math.round(l1 - l0);
      var tA = dataA ? dataA.time : extrapolateTime(pxA.x, plotWidth());
      var tB = dataB ? dataB.time : extrapolateTime(pxB.x, plotWidth());
      var dSec = tA != null && tB != null ? tB - tA : 0;

      shade.className = "live-ov-measure-shade " + theme;
      shade.style.display = "block";
      shade.style.left = left + "px";
      shade.style.top = top + "px";
      shade.style.width = w + "px";
      shade.style.height = h + "px";

      var ax = pxA.x - left;
      var ay = pxA.y - top;
      var hx = pxB.x >= pxA.x ? w : 0;
      var vy = pxB.y >= pxA.y ? h : 0;
      hLine.setAttribute("x1", ax);
      hLine.setAttribute("y1", ay);
      hLine.setAttribute("x2", hx);
      hLine.setAttribute("y2", ay);
      vLine.setAttribute("x1", ax);
      vLine.setAttribute("y1", ay);
      vLine.setAttribute("x2", ax);
      vLine.setAttribute("y2", vy);
      hLine.setAttribute("stroke", stroke);
      vLine.setAttribute("stroke", stroke);
      hLine.setAttribute("stroke-width", "1");
      vLine.setAttribute("stroke-width", "1");
      hLine.setAttribute("marker-end", "url(#" + markerId + ")");
      vLine.setAttribute("marker-end", "url(#" + markerId + ")");

      if (!svg.querySelector("defs")) {
        var defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
        var marker = document.createElementNS("http://www.w3.org/2000/svg", "marker");
        marker.setAttribute("id", markerId);
        marker.setAttribute("markerWidth", "6");
        marker.setAttribute("markerHeight", "6");
        marker.setAttribute("refX", "5");
        marker.setAttribute("refY", "3");
        marker.setAttribute("orient", "auto");
        var path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute("d", "M0,0 L6,3 L0,6 Z");
        path.setAttribute("fill", stroke);
        marker.appendChild(path);
        defs.appendChild(marker);
        svg.insertBefore(defs, svg.firstChild);
      } else {
        var arr = svg.querySelector("path");
        if (arr) arr.setAttribute("fill", stroke);
      }

      var line1 = formatSignedNum(dPrice, 2) + " (" + formatSignedNum(pct, 2) + "%)";
      var barLabel = dBars + " bars, " + formatDurationTv(dSec);
      if (Math.abs(dBars) <= 1 && Math.abs(dSec) < stepSec * 2) {
        barLabel = dBars + " bar";
      }

      tag.className = "live-ov-measure-tag " + theme;
      tag.innerHTML =
        '<div class="l1">' + line1 + '</div><div class="l2">' + barLabel + "</div>";

      tag.style.left = left + w / 2 + "px";
      if (up) {
        tag.style.top = top - 6 + "px";
        tag.style.transform = "translate(-50%, -100%)";
      } else {
        tag.style.top = bottom + 6 + "px";
        tag.style.transform = "translate(-50%, 0)";
      }

      setReadout(line1 + " · " + barLabel);
    }

    function renderMeasure(a, b) {
      if (!a || !b) return;
      savedA = a;
      savedB = b;
      var pa = pixelOf(a);
      var pb = pixelOf(b);
      if (!pa || !pb) return;
      paintMeasureBox(pa, pb, a, b);
    }

    function renderMeasureDrag(pxA, pxB, dataA, dataB) {
      if (dataA && dataB) {
        savedA = dataA;
        savedB = dataB;
      }
      paintMeasureBox(pxA, pxB, dataA, dataB);
    }

    function repaintIfSaved() {
      if (dragging) return;
      if (savedA && savedB) renderMeasure(savedA, savedB);
    }

    chart.timeScale().subscribeVisibleTimeRangeChange(repaintIfSaved);
    window.addEventListener("resize", repaintIfSaved, { passive: true });

    var dragPointerId = null;
    var anchorPx = null;
    var anchorData = null;

    function blockTouchScroll(e) {
      if (dragging) e.preventDefault();
    }

    function bindDragListeners() {
      window.addEventListener("pointermove", onWindowPointerMove, { passive: false });
      window.addEventListener("pointerup", onWindowPointerUp);
      window.addEventListener("pointercancel", onWindowPointerCancel);
      window.addEventListener("mousemove", onWindowMouseMove, { passive: false });
      window.addEventListener("mouseup", onWindowMouseUp);
      document.addEventListener("selectstart", blockTouchScroll);
      document.addEventListener("touchmove", blockTouchScroll, { passive: false });
    }

    function unbindDragListeners() {
      window.removeEventListener("pointermove", onWindowPointerMove);
      window.removeEventListener("pointerup", onWindowPointerUp);
      window.removeEventListener("pointercancel", onWindowPointerCancel);
      window.removeEventListener("mousemove", onWindowMouseMove);
      window.removeEventListener("mouseup", onWindowMouseUp);
      document.removeEventListener("selectstart", blockTouchScroll);
      document.removeEventListener("touchmove", blockTouchScroll);
    }

    function finishDrag(e) {
      if (!dragging) return;
      dragging = false;
      unbindDragListeners();
      try {
        if (layer.releasePointerCapture && dragPointerId != null) {
          layer.releasePointerCapture(dragPointerId);
        }
      } catch (err) {
        /* ignore */
      }
      var didMeasure = false;
      if (anchorPx && e) {
        var endPx = clientToPixel(e.clientX, e.clientY);
        var endData = dataFromPixel(endPx.x, endPx.y);
        renderMeasureDrag(anchorPx, endPx, anchorData, endData);
        didMeasure = true;
      } else if (anchorPx && anchorData && savedA && savedB) {
        renderMeasure(savedA, savedB);
        didMeasure = true;
      }
      anchorPx = null;
      anchorData = null;
      dragPointerId = null;
      if (active && didMeasure) leaveMeasureToolAfterUse();
    }

    function dragMove(clientX, clientY) {
      if (!dragging || !anchorPx || !anchorData) return;
      var endPx = clientToPixel(clientX, clientY);
      var endData = dataFromPixel(endPx.x, endPx.y);
      renderMeasureDrag(anchorPx, endPx, anchorData, endData);
    }

    function onWindowPointerMove(e) {
      if (!dragging || e.pointerId !== dragPointerId) return;
      e.preventDefault();
      dragMove(e.clientX, e.clientY);
    }

    function onWindowMouseMove(e) {
      if (!dragging || dragPointerId != null) return;
      e.preventDefault();
      dragMove(e.clientX, e.clientY);
    }

    function onWindowPointerUp(e) {
      if (e.pointerId !== dragPointerId) return;
      finishDrag(e);
    }

    function onWindowPointerCancel(e) {
      if (e.pointerId !== dragPointerId) return;
      finishDrag(e);
    }

    function onWindowMouseUp(e) {
      if (dragPointerId != null || !dragging) return;
      finishDrag(e);
    }

    function leaveMeasureToolAfterUse() {
      active = false;
      btn.classList.remove("on");
      btn.setAttribute("aria-pressed", "false");
      wrap.classList.remove("measure-on");
      layer.setAttribute("aria-hidden", "true");
      setPanZoom(true);
      setReadout("");
    }

    function deactivate() {
      active = false;
      finishDrag(null);
      unbindDragListeners();
      btn.classList.remove("on");
      btn.setAttribute("aria-pressed", "false");
      wrap.classList.remove("measure-on");
      layer.setAttribute("aria-hidden", "true");
      setPanZoom(true);
      hideMeasure();
      setReadout("");
    }

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
      layer.setAttribute("aria-hidden", "false");
      hideMeasure();
      setPanZoom(false);
      setReadout("کلیک کنید، بکشید، رها کنید (مثل TradingView)");
    });

    function onPointerDown(e) {
      if (!active || e.button !== 0) return;
      var px = clientToPixel(e.clientX, e.clientY);
      var data = dataFromPixel(px.x, px.y);
      if (!data) {
        var py = series.coordinateToPrice(px.y);
        if (py == null || !isFinite(py)) return;
        data = {
          time: extrapolateTime(px.x, plotWidth()) || (candles.length ? candles[candles.length - 1].time : 0),
          price: py,
          logical: chart.timeScale().coordinateToLogical(px.x),
        };
      }
      e.preventDefault();
      e.stopPropagation();
      dragging = true;
      dragPointerId = e.pointerId;
      anchorPx = px;
      anchorData = data;
      renderMeasureDrag(anchorPx, anchorPx, anchorData, anchorData);
      bindDragListeners();
      if (layer.setPointerCapture) {
        try {
          layer.setPointerCapture(e.pointerId);
        } catch (err2) {
          /* ignore */
        }
      }
    }

    layer.addEventListener("pointerdown", onPointerDown, { passive: false });

    window.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && active) deactivate();
    });
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

  function candleAutoscale(original) {
    var base = original ? original() : null;
    if (!base || !base.priceRange) return base;
    return { priceRange: base.priceRange };
  }

  function ignoreAutoscale() {
    return null;
  }

  function fmtNum(n, digits) {
    return Number(n).toLocaleString("en-US", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  }

  function drawPositionBox(chart, series, mount, payload) {
    var box = payload.position_box;
    if (!box || !mount.parentElement) return function () {};
    var layer = document.createElement("div");
    layer.className = "live-ov-pos-layer";
    layer.style.cssText =
      "position:absolute;inset:0;pointer-events:none;overflow:hidden;z-index:3;";
    mount.parentElement.appendChild(layer);

    function zone(top, height, color) {
      var el = document.createElement("div");
      el.style.cssText =
        "position:absolute;left:" +
        "0;background:" +
        color +
        ";border:1px solid " +
        color.replace("0.045", "0.55") +
        ";box-sizing:border-box;";
      return el;
    }

    function tag(text, bg) {
      var el = document.createElement("div");
      el.textContent = text;
      el.style.cssText =
        "position:absolute;transform:translate(-50%,-50%);padding:2px 6px;border-radius:3px;font:11px/1.3 ui-sans-serif,system-ui,sans-serif;color:#fff;white-space:nowrap;background:" +
        bg +
        ";";
      return el;
    }

    function handle(x, y) {
      var el = document.createElement("div");
      el.style.cssText =
        "position:absolute;width:7px;height:7px;margin:-4px 0 0 -4px;background:#2962ff;border:1px solid #fff;box-sizing:border-box;";
      el.style.left = x + "px";
      el.style.top = y + "px";
      return el;
    }

    function paint() {
      layer.innerHTML = "";
      var yE = series.priceToCoordinate(box.entry);
      var yTp = series.priceToCoordinate(box.tp);
      var ySl = series.priceToCoordinate(box.sl);
      var x1 = chart.timeScale().timeToCoordinate(box.time);
      var plotW = chart.timeScale().width();
      if (yE == null || yTp == null || ySl == null || x1 == null || !plotW) return;
      var x2 = Math.max(x1 + 72, plotW - 4);
      var profitTop = Math.min(yE, yTp);
      var profitH = Math.max(2, Math.abs(yTp - yE));
      var stopTop = Math.min(yE, ySl);
      var stopH = Math.max(2, Math.abs(ySl - yE));
      var green = "rgba(8,153,129,0.045)";
      var red = "rgba(242,54,69,0.045)";
      var profit = zone(profitTop, profitH, green);
      var stop = zone(stopTop, stopH, red);
      [profit, stop].forEach(function (el) {
        el.style.left = x1 + "px";
        el.style.width = Math.max(8, x2 - x1) + "px";
      });
      profit.style.top = profitTop + "px";
      profit.style.height = profitH + "px";
      stop.style.top = stopTop + "px";
      stop.style.height = stopH + "px";
      var entryLine = document.createElement("div");
      entryLine.style.cssText =
        "position:absolute;height:0;border-top:1px solid rgba(226,232,240,0.85);";
      entryLine.style.left = x1 + "px";
      entryLine.style.width = Math.max(8, x2 - x1) + "px";
      entryLine.style.top = yE + "px";
      var distTp = Math.abs(box.tp - box.entry);
      var distSl = Math.abs(box.sl - box.entry);
      var pctTp = (distTp / box.entry) * 100;
      var pctSl = (distSl / box.entry) * 100;
      var qty = Number(box.qty) || 0;
      var pnlTp = qty * distTp;
      var pnlSl = qty * distSl;
      var rr = distSl > 0 ? distTp / distSl : 0;
      var tpText =
        fmtNum(distTp, 2) +
        " (" +
        fmtNum(pctTp, 3) +
        "%)" +
        (qty ? " " + fmtNum(pnlTp, 2) : "");
      var slText =
        fmtNum(distSl, 2) +
        " (" +
        fmtNum(pctSl, 3) +
        "%)" +
        (qty ? " " + fmtNum(pnlSl, 2) : "");
      var tpTag = tag(tpText, "#089981");
      var slTag = tag(slText, "#f23645");
      var midTag = tag(fmtNum(rr, 2), "rgba(8,153,129,0.92)");
      var midX = (x1 + x2) / 2;
      var boxTop = Math.min(profitTop, stopTop);
      var boxBot = Math.max(profitTop + profitH, stopTop + stopH);
      function placeOutside(el, yLevel) {
        el.style.left = midX + "px";
        if (yLevel < yE) {
          el.style.top = boxTop - 6 + "px";
          el.style.transform = "translate(-50%, -100%)";
        } else {
          el.style.top = boxBot + 6 + "px";
          el.style.transform = "translate(-50%, 0)";
        }
      }
      placeOutside(tpTag, yTp);
      placeOutside(slTag, ySl);
      midTag.style.left = midX + "px";
      midTag.style.top = yE + "px";
      layer.appendChild(profit);
      layer.appendChild(stop);
      layer.appendChild(entryLine);
      layer.appendChild(tpTag);
      layer.appendChild(slTag);
      layer.appendChild(midTag);
      [x1, x2].forEach(function (x) {
        [Math.min(profitTop, stopTop), Math.max(profitTop + profitH, stopTop + stopH)].forEach(
          function (y) {
            layer.appendChild(handle(x, y));
          }
        );
        layer.appendChild(handle(x, yE));
      });
    }

    var scheduled = false;
    function schedule() {
      if (scheduled) return;
      scheduled = true;
      requestAnimationFrame(function () {
        scheduled = false;
        paint();
      });
    }
    chart.timeScale().subscribeVisibleLogicalRangeChange(schedule);
    chart.timeScale().subscribeVisibleTimeRangeChange(schedule);
    if (typeof chart.timeScale().subscribeSizeChange === "function") {
      chart.timeScale().subscribeSizeChange(schedule);
    }
    ["wheel", "touchmove", "pointermove", "pointerup", "mouseup"].forEach(function (ev) {
      mount.addEventListener(ev, schedule, { passive: true });
    });
    if (typeof ResizeObserver !== "undefined") {
      new ResizeObserver(schedule).observe(mount);
    }
    return paint;
  }

  function initMount(mount) {
    if (mount.dataset.liveChartReady === "1") return;
    var payload = readPayload(mount);
    if (!payload || !payload.candles || !payload.candles.length) return;
    if (typeof LightweightCharts === "undefined") return;

    mount.dataset.liveChartReady = "1";
    mount.style.direction = "ltr";
    var w = mount.clientWidth || 320;
    var chartH = Math.max(280, mount.clientHeight || 320);
    var chart = LightweightCharts.createChart(mount, {
      width: w,
      height: chartH,
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
        autoScale: true,
        scaleMargins: { top: 0.04, bottom: 0.04 },
      },
      localization: {
        locale: "fa-IR",
        timeFormatter: function (time) {
          return formatAxisTime(time, true);
        },
      },
      timeScale: {
        borderColor: "#2a3441",
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 6,
        fixLeftEdge: false,
        lockVisibleTimeRangeOnResize: false,
        tickMarkFormatter: function (time, tickMarkType) {
          return formatAxisTime(time, tickMarkType < 3);
        },
      },
    });

    var ov = payload.overlays || {};

    var series = chart.addCandlestickSeries({
      upColor: "#34d399",
      downColor: "#f87171",
      borderVisible: false,
      wickUpColor: "#34d399",
      wickDownColor: "#f87171",
      autoscaleInfoProvider: candleAutoscale,
    });
    series.setData(payload.candles);
    var levelsOnly = mount.getAttribute("data-levels-only") === "1";
    function keepTradeLevel(label) {
      if (!levelsOnly) return true;
      var t = String(label || "").trim().toLowerCase();
      return t === "entry" || t === "sl" || t === "tp";
    }
    (ov.hlines || []).forEach(function (hl) {
      if (!hl || typeof hl.price !== "number") return;
      if (!keepTradeLevel(hl.label)) return;
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
        autoscaleInfoProvider: ignoreAutoscale,
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
        autoscaleInfoProvider: ignoreAutoscale,
      });
      ls.setData(ln.points);
    });

    if (ov.markers && ov.markers.length) {
      var markers = ov.markers;
      if (levelsOnly) {
        markers = markers.filter(function (mk) {
          return keepTradeLevel(mk && mk.text);
        });
      }
      if (markers.length) series.setMarkers(markers);
    }

    function candleIndexAt(time, side) {
      var cs = payload.candles || [];
      if (!cs.length) return 0;
      if (side === "from") {
        for (var i = 0; i < cs.length; i++) {
          if (cs[i].time >= time) return i;
        }
        return cs.length - 1;
      }
      for (var j = cs.length - 1; j >= 0; j--) {
        if (cs[j].time <= time) return j;
      }
      return 0;
    }

    var applyingView = false;
    var userPanned = false;

    function applyViewport() {
      if (userPanned) {
        chart.applyOptions({ width: Math.max(280, mount.clientWidth || w) });
        return;
      }
      chart.priceScale("right").applyOptions({
        autoScale: true,
        scaleMargins: { top: 0.04, bottom: 0.04 },
      });
      var cs = payload.candles || [];
      var plotW = Math.max(280, mount.clientWidth || w);
      chart.applyOptions({ width: plotW });
      if (cs.length < 2) return;
      var vp = payload.viewport;
      var end = cs.length - 1;
      if (vp && vp.to != null) {
        end = candleIndexAt(vp.to, "to");
        end = Math.min(cs.length - 1, end + 6);
      }
      var spacing = 6;
      var capacity = Math.max(24, Math.floor((plotW - 52) / spacing));
      var fromIdx = Math.max(0, end - capacity + 1);
      var barsInView = end - fromIdx + 1;
      if (barsInView < capacity) {
        spacing = Math.max(2, (plotW - 52) / barsInView);
      }
      applyingView = true;
      chart.timeScale().applyOptions({
        barSpacing: spacing,
        rightOffset: 1,
        fixLeftEdge: false,
      });
      try {
        chart.timeScale().setVisibleLogicalRange({ from: fromIdx, to: end });
      } catch (e) {
        chart.timeScale().fitContent();
      }
      applyingView = false;
      paintPosition();
    }

    var loadingOlder = false;
    var historyDone = false;
    chart.timeScale().subscribeVisibleLogicalRangeChange(function (range) {
      if (!applyingView && range) userPanned = true;
      if (!range || loadingOlder || historyDone || applyingView) return;
      if (range.from > 12) return;
      var first = payload.candles && payload.candles[0];
      if (!first) return;
      loadingOlder = true;
      var tf = payload.timeframe || "5m";
      fetch(
        "/api/chart/live/history?tf=" + encodeURIComponent(tf) + "&before=" + first.time,
        { credentials: "same-origin" }
      )
        .then(function (r) {
          return r.ok ? r.json() : null;
        })
        .then(function (data) {
          var older = (data && data.candles) || [];
          if (!older.length) {
            historyDone = true;
            return;
          }
          var seen = {};
          payload.candles.forEach(function (c) {
            seen[c.time] = 1;
          });
          var fresh = [];
          older.forEach(function (c) {
            if (!seen[c.time]) fresh.push(c);
          });
          if (!fresh.length) {
            historyDone = true;
            return;
          }
          fresh.sort(function (a, b) {
            return a.time - b.time;
          });
          var prev = chart.timeScale().getVisibleLogicalRange();
          payload.candles = fresh.concat(payload.candles);
          series.setData(payload.candles);
          if (prev) {
            chart.timeScale().setVisibleLogicalRange({
              from: prev.from + fresh.length,
              to: prev.to + fresh.length,
            });
          }
        })
        .catch(function () {})
        .then(function () {
          loadingOlder = false;
        });
    });

    requestAnimationFrame(function () {
      requestAnimationFrame(applyViewport);
    });

    var paintPosition = drawPositionBox(chart, series, mount, payload);
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
            payload.candles = data.candles;
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
        applyViewport();
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
