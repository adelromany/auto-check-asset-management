/* Tiny SVG chart helpers for the handover dashboard. No libraries. */
"use strict";
(function () {
  var NS = "http://www.w3.org/2000/svg";

  function svgEl(tag, attrs) {
    var node = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (key) {
      node.setAttribute(key, String(attrs[key]));
    });
    return node;
  }

  function text(x, y, value, cls, anchor) {
    var node = svgEl("text", { x: x, y: y, class: cls || "chart-axis", "text-anchor": anchor || "middle" });
    node.textContent = value;
    return node;
  }

  function maxOf(points) {
    var max = 0;
    points.forEach(function (point) {
      max = Math.max(max, point.started || 0, point.completed || 0);
    });
    return max;
  }

  function perDay(host, points) {
    host.textContent = "";
    var list = Array.isArray(points) ? points : [];
    var max = maxOf(list);
    if (!list.length || max === 0) {
      var empty = document.createElement("div");
      empty.className = "chart-empty";
      empty.textContent = "No data";
      host.appendChild(empty);
      return;
    }
    var width = 720;
    var height = 220;
    var left = 36;
    var right = 10;
    var top = 12;
    var bottom = 28;
    var plotWidth = width - left - right;
    var plotHeight = height - top - bottom;
    var svg = svgEl("svg", {
      viewBox: "0 0 " + width + " " + height,
      class: "chart-svg",
      role: "img",
      "aria-label": "Handovers started and completed per day",
      preserveAspectRatio: "none",
    });

    var steps = 4;
    for (var step = 0; step <= steps; step += 1) {
      var value = Math.round((max * step) / steps);
      var y = top + plotHeight - (plotHeight * step) / steps;
      svg.appendChild(svgEl("line", {
        x1: left, y1: y, x2: width - right, y2: y, class: "chart-grid",
      }));
      svg.appendChild(text(left - 6, y + 3, String(value), "chart-axis", "end"));
    }

    var group = plotWidth / list.length;
    var barWidth = Math.max(2, Math.min(12, group * 0.34));
    list.forEach(function (point, index) {
      var center = left + group * index + group / 2;
      var started = point.started || 0;
      var completed = point.completed || 0;
      var startedHeight = (started / max) * plotHeight;
      var completedHeight = (completed / max) * plotHeight;
      var startedBar = svgEl("rect", {
        x: center - barWidth - 1,
        y: top + plotHeight - startedHeight,
        width: barWidth,
        height: Math.max(started ? 1 : 0, startedHeight),
        rx: 1,
        class: "chart-series-started",
      });
      startedBar.appendChild(svgEl("title", {})).textContent =
        point.day + " · Started " + started;
      svg.appendChild(startedBar);
      var completedBar = svgEl("rect", {
        x: center + 1,
        y: top + plotHeight - completedHeight,
        width: barWidth,
        height: Math.max(completed ? 1 : 0, completedHeight),
        rx: 1,
        class: "chart-series-completed",
      });
      completedBar.appendChild(svgEl("title", {})).textContent =
        point.day + " · Completed " + completed;
      svg.appendChild(completedBar);
    });

    if (list.length > 2) {
      [0, Math.floor((list.length - 1) / 2), list.length - 1].forEach(function (index) {
        svg.appendChild(text(
          left + group * index + group / 2,
          height - 8,
          String(list[index].day || "").slice(5),
          "chart-axis"
        ));
      });
    } else if (list.length === 1) {
      svg.appendChild(text(
        left + plotWidth / 2,
        height - 8,
        String(list[0].day || "").slice(5),
        "chart-axis"
      ));
    }

    host.appendChild(svg);
  }

  function sparkline(host, values) {
    if (!host) return;
    host.textContent = "";
    var list = Array.isArray(values) ? values : [];
    var max = Math.max.apply(null, list.concat([0]));
    var width = 120;
    var height = 24;
    var step = list.length > 1 ? width / (list.length - 1) : width;
    var svg = svgEl("svg", {
      viewBox: "0 0 " + width + " " + height,
      class: "spark-svg",
      "aria-hidden": "true",
      preserveAspectRatio: "none",
    });
    var points = list.map(function (value, index) {
      var ratio = max ? value / max : 0;
      return (index * step).toFixed(1) + "," + (height - 2 - ratio * (height - 4)).toFixed(1);
    });
    if (!max) {
      svg.appendChild(svgEl("line", {
        x1: 0, y1: height - 2, x2: width, y2: height - 2, class: "chart-spark-line",
      }));
    } else {
      svg.appendChild(svgEl("polyline", {
        points: points.join(" "), class: "chart-spark-line",
      }));
    }
    host.appendChild(svg);
  }

  window.dashboardCharts = { perDay: perDay, sparkline: sparkline };
})();
