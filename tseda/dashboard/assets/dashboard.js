/* Dashboard tseda: biểu đồ SVG tự vẽ, không thư viện ngoài.
 * Mọi chuỗi lấy từ dữ liệu (tên cột, giá trị, thông điệp) đi qua textContent, không qua innerHTML.
 * Mỗi biểu đồ có bảng dữ liệu đi kèm (dạng bảng) và tooltip cũng hiện khi lấy focus bằng bàn phím.
 */
(function () {
  "use strict";

  // ---------- dữ liệu nhúng ----------
  const DATA = JSON.parse(document.getElementById("tseda-data").textContent);
  const META = DATA.meta;
  const COLS = DATA.columns;
  const BY = new Map(COLS.map((c) => [c.name, c]));
  const NROWS = META.sample_rows;
  const SEV_RANK = { CRITICAL: 0, WARN: 1, INFO: 2 };
  const SEV_ICON = { CRITICAL: "✖", WARN: "▲", INFO: "ⓘ" };
  const SEV_LABEL = { CRITICAL: "Nghiêm trọng", WARN: "Cảnh báo", INFO: "Thông tin" };
  const SVGNS = "http://www.w3.org/2000/svg";
  // Biến thể cùng khóa chuẩn hóa được gộp về một thực thể (xem tseda/capability/entity.py).
  const ENT_MAP = META.entity_map || {};
  const entName = (v) => (ENT_MAP[String(v)] !== undefined ? ENT_MAP[String(v)] : String(v));

  const state = {
    tab: "overview",
    filters: new Map(),
    idx: [],
    col: null,
    tsMeasure: null,
    tsAgg: "mean",
    tsMode: "total",
    sev: "ALL",
  };

  // ---------- tiện ích DOM ----------
  const $ = (id) => document.getElementById(id);

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }

  function svg(tag, attrs, parent) {
    const n = document.createElementNS(SVGNS, tag);
    for (const k in attrs || {}) {
      const v = attrs[k];
      if (v !== null && v !== undefined) n.setAttribute(k, String(v));
    }
    if (parent) parent.appendChild(n);
    return n;
  }

  function fmt(v, digits) {
    if (v === null || v === undefined) return "—";
    if (typeof v === "boolean") return v ? "Đúng" : "Sai";
    if (typeof v === "number") {
      if (!isFinite(v)) return "—";
      const a = Math.abs(v);
      if (a !== 0 && (a >= 1e7 || a < 1e-3)) return v.toExponential(2);
      const d = digits !== undefined ? digits : a >= 100 ? 0 : a >= 1 ? 2 : 3;
      return v.toLocaleString("vi-VN", { maximumFractionDigits: d });
    }
    return String(v);
  }

  function fmtAxis(v) {
    const a = Math.abs(v);
    if (a >= 1e6) return fmt(v / 1e6, 1) + "M";
    if (a >= 1e3) return fmt(v / 1e3, 1) + "k";
    return fmt(v, a >= 10 ? 0 : 2);
  }

  function pct(v) {
    if (v === null || v === undefined || !isFinite(v)) return "—";
    return (v * 100).toLocaleString("vi-VN", { maximumFractionDigits: 1 }) + "%";
  }

  function trunc(s, n) {
    s = String(s);
    return s.length > n ? s.slice(0, Math.max(1, n - 1)) + "…" : s;
  }

  function displayLevel(v) {
    if (typeof v === "boolean") return v ? "Đúng" : "Sai";
    return trunc(String(v), 40);
  }

  function widthOf(node) {
    const w = node.clientWidth;
    return Math.min(1100, Math.max(260, w || 640));
  }

  function niceCeil(v) {
    if (!(v > 0)) return 1;
    const p = Math.pow(10, Math.floor(Math.log10(v)));
    const f = v / p;
    const nice = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10;
    return nice * p;
  }

  // ---------- tooltip và tương tác ----------
  const tip = $("tip");

  function showTip(x, y, head, rows) {
    tip.replaceChildren();
    if (head) tip.appendChild(el("div", "tk", head));
    for (const r of rows) {
      const line = el("div", "row");
      if (r.color) {
        const k = el("span", "key");
        k.style.background = r.color;
        line.appendChild(k);
      }
      line.appendChild(el("span", "tk", r.label));
      const v = el("strong", "tv", r.value);
      v.style.marginLeft = "auto";
      line.appendChild(v);
      tip.appendChild(line);
    }
    tip.hidden = false;
    const rect = tip.getBoundingClientRect();
    let left = x + 14;
    if (left + rect.width > window.innerWidth - 8) left = x - rect.width - 14;
    let top = y + 14;
    if (top + rect.height > window.innerHeight - 8) top = y - rect.height - 14;
    tip.style.left = Math.max(8, left) + "px";
    tip.style.top = Math.max(8, top) + "px";
  }

  function hideTip() {
    tip.hidden = true;
  }

  // build() trả về {head, rows}. markNode được làm sáng khi trỏ/focus.
  function attachTip(node, build, markNode) {
    const show = (x, y) => {
      const t = build();
      showTip(x, y, t.head, t.rows);
    };
    const light = (on) => {
      if (markNode) markNode.style.opacity = on ? "0.8" : "";
    };
    node.addEventListener("pointermove", (e) => show(e.clientX, e.clientY));
    node.addEventListener("pointerenter", () => light(true));
    node.addEventListener("pointerleave", () => {
      hideTip();
      light(false);
    });
    node.addEventListener("focus", () => {
      const r = node.getBoundingClientRect();
      show(r.left + r.width / 2, r.top);
      light(true);
    });
    node.addEventListener("blur", () => {
      hideTip();
      light(false);
    });
  }

  // ---------- hình học của mark ----------
  // Cột: đỉnh bo 4px, đáy phẳng nằm trên trục.
  function vbarPath(x, y0, w, h) {
    const r = Math.min(4, w / 2, h);
    const yb = y0 + h;
    return `M${x},${yb} V${y0 + r} Q${x},${y0} ${x + r},${y0} H${x + w - r} Q${x + w},${y0} ${x + w},${y0 + r} V${yb} Z`;
  }

  // Thanh ngang: đầu phải bo, đáy trái phẳng nằm trên trục.
  function hbarPath(x0, y, w, h) {
    const r = Math.min(4, h / 2, w);
    return `M${x0},${y} H${x0 + w - r} Q${x0 + w},${y} ${x0 + w},${y + r} V${y + h - r} Q${x0 + w},${y + h} ${x0 + w - r},${y + h} H${x0} Z`;
  }

  // ---------- lọc ----------
  function matches(col, f, i) {
    const v = col.values[i];
    switch (f.type) {
      case "level":
        return v !== null && v !== undefined && String(v) === f.value;
      case "range":
        return v !== null && v !== undefined && (f.lo === null || v >= f.lo) && (f.hi === null || v <= f.hi);
      case "date": {
        if (v === null || v === undefined) return false;
        const d = v.slice(0, 10);
        return (!f.from || d >= f.from) && (!f.to || d <= f.to);
      }
      default:
        return true;
    }
  }

  function computeIdx() {
    const active = [...state.filters.entries()].map(([name, f]) => [BY.get(name), f]);
    const out = [];
    for (let i = 0; i < NROWS; i++) {
      let ok = true;
      for (const [col, f] of active) {
        if (!matches(col, f, i)) {
          ok = false;
          break;
        }
      }
      if (ok) out.push(i);
    }
    state.idx = out;
  }

  function filteredValues(col) {
    return state.idx.map((i) => col.values[i]);
  }

  function updateFilterMeta() {
    let text = `Đang dùng ${state.idx.length} / ${NROWS} dòng của mẫu`;
    if (META.sampled) text += ` (mẫu từ ${META.total_rows} dòng)`;
    $("filter-count").textContent = text;
  }

  function applyFilters() {
    computeIdx();
    updateFilterMeta();
    renderTab();
  }

  function buildFilters() {
    const row = $("filter-row");
    row.replaceChildren();
    for (const c of COLS) {
      const label = el("label");
      label.appendChild(el("span", "", c.name));
      if ((c.kind === "categorical" || c.kind === "boolean" || c.kind === "id") && c.levels) {
        const sel = document.createElement("select");
        sel.setAttribute("aria-label", "Lọc theo " + c.name);
        sel.appendChild(new Option("Tất cả", "__all__"));
        for (const lv of c.levels) {
          sel.appendChild(new Option(`${displayLevel(lv.value)} (${lv.count})`, String(lv.value)));
        }
        sel.addEventListener("change", () => {
          if (sel.value === "__all__") state.filters.delete(c.name);
          else state.filters.set(c.name, { type: "level", value: sel.value });
          applyFilters();
        });
        label.appendChild(sel);
        row.appendChild(label);
      } else if ((c.kind === "numeric" || c.kind === "mixed") && c.min !== null && c.max !== null && c.min < c.max) {
        const wrap = el("span", "range");
        const lo = document.createElement("input");
        const hi = document.createElement("input");
        for (const inp of [lo, hi]) {
          inp.type = "number";
          inp.step = "any";
        }
        lo.placeholder = "Từ " + fmt(c.min);
        hi.placeholder = "Đến " + fmt(c.max);
        lo.setAttribute("aria-label", "Tối thiểu của " + c.name);
        hi.setAttribute("aria-label", "Tối đa của " + c.name);
        const onChange = () => {
          const a = lo.value === "" ? null : Number(lo.value);
          const b = hi.value === "" ? null : Number(hi.value);
          if (a === null && b === null) state.filters.delete(c.name);
          else state.filters.set(c.name, { type: "range", lo: a, hi: b });
          applyFilters();
        };
        lo.addEventListener("input", onChange);
        hi.addEventListener("input", onChange);
        wrap.appendChild(lo);
        wrap.appendChild(hi);
        label.appendChild(wrap);
        row.appendChild(label);
      } else if (c.kind === "datetime" && c.min && c.max) {
        const wrap = el("span", "range");
        const from = document.createElement("input");
        const to = document.createElement("input");
        from.type = "date";
        to.type = "date";
        from.setAttribute("aria-label", "Từ ngày của " + c.name);
        to.setAttribute("aria-label", "Đến ngày của " + c.name);
        const onChange = () => {
          const a = from.value || null;
          const b = to.value || null;
          if (!a && !b) state.filters.delete(c.name);
          else state.filters.set(c.name, { type: "date", from: a, to: b });
          applyFilters();
        };
        from.addEventListener("input", onChange);
        to.addEventListener("input", onChange);
        wrap.appendChild(from);
        wrap.appendChild(to);
        label.appendChild(wrap);
        row.appendChild(label);
      }
    }
    if (!row.childElementCount) row.appendChild(el("p", "muted small", "Không có cột nào đủ điều kiện để lọc."));
  }

  // ---------- thống kê ----------
  function describe(arr) {
    const a = arr.slice().sort((x, y) => x - y);
    const n = a.length;
    if (!n) return { n: 0, mean: null, median: null, sd: null, p05: null, p95: null, min: null, max: null };
    const q = (p) => {
      const pos = (n - 1) * p;
      const lo = Math.floor(pos);
      const hi = Math.ceil(pos);
      return a[lo] + (a[hi] - a[lo]) * (pos - lo);
    };
    const mean = a.reduce((s, v) => s + v, 0) / n;
    const sd = n > 1 ? Math.sqrt(a.reduce((s, v) => s + (v - mean) ** 2, 0) / (n - 1)) : null;
    return { n, mean, median: q(0.5), sd, p05: q(0.05), p95: q(0.95), min: a[0], max: a[n - 1] };
  }

  function histogram(nums, bins) {
    if (!nums.length) return null;
    const lo = nums.reduce((m, v) => Math.min(m, v), Infinity);
    const hi = nums.reduce((m, v) => Math.max(m, v), -Infinity);
    if (lo === hi) return { labels: [fmt(lo)], lows: [fmt(lo)], counts: [nums.length] };
    const w = (hi - lo) / bins;
    const counts = new Array(bins).fill(0);
    for (const v of nums) {
      let b = Math.floor((v - lo) / w);
      if (b >= bins) b = bins - 1;
      if (b < 0) b = 0;
      counts[b] += 1;
    }
    const labels = counts.map((_, b) => `${fmt(lo + b * w)} – ${fmt(lo + (b + 1) * w)}`);
    const lows = counts.map((_, b) => fmt(lo + b * w));
    return { labels, lows, counts };
  }

  // Chuỗi thời gian: chọn độ phân giải theo độ dài dữ liệu, rồi tạo đủ mọi kỳ (kỳ trống là null).
  function granularityFor(minKey, maxKey) {
    const days = (Date.parse(maxKey + "T00:00:00Z") - Date.parse(minKey + "T00:00:00Z")) / 86400000;
    if (days <= 120) return "day";
    if (days <= 1095) return "month";
    return "year";
  }

  function periodKey(iso, gran) {
    const s = String(iso);
    if (gran === "day") return s.slice(0, 10);
    if (gran === "month") return s.slice(0, 7);
    return s.slice(0, 4);
  }

  function keysBetween(gran, a, b) {
    const keys = [];
    if (gran === "day") {
      let t = Date.parse(a + "T00:00:00Z");
      const end = Date.parse(b + "T00:00:00Z");
      while (t <= end) {
        keys.push(new Date(t).toISOString().slice(0, 10));
        t += 86400000;
      }
    } else if (gran === "month") {
      let y = Number(a.slice(0, 4));
      let m = Number(a.slice(5, 7));
      const ye = Number(b.slice(0, 4));
      const me = Number(b.slice(5, 7));
      while (y < ye || (y === ye && m <= me)) {
        keys.push(`${y}-${String(m).padStart(2, "0")}`);
        m += 1;
        if (m > 12) {
          m = 1;
          y += 1;
        }
      }
    } else {
      for (let y = Number(a); y <= Number(b); y++) keys.push(String(y));
    }
    return keys;
  }

  // ---------- biểu đồ ----------
  function clearNode(node) {
    node.replaceChildren();
  }

  function emptyNote(node, text) {
    clearNode(node);
    node.appendChild(el("p", "empty", text));
  }

  // Thanh ngang: dùng cho danh mục.
  function hbarChart(node, items, opts) {
    opts = opts || {};
    clearNode(node);
    if (!items.length) return emptyNote(node, opts.empty || "Không có dữ liệu để vẽ.");
    const W = widthOf(node);
    const maxLen = items.reduce((m, d) => Math.max(m, String(d.label).length), 0);
    const labelW = Math.min(Math.max(96, maxLen * 6.4), Math.max(120, W * 0.42));
    const x0 = labelW + 8;
    const valueW = 90;
    const plotW = Math.max(60, W - x0 - valueW);
    const band = 24;
    const top = 4;
    const H = top + items.length * band + 4;
    const maxV = items.reduce((m, d) => Math.max(m, d.value || 0), 0) || 1;
    const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.aria || "Biểu đồ thanh ngang" }, node);
    for (let k = 0; k <= 4; k++) {
      const gx = x0 + (plotW * k) / 4;
      svg("line", { x1: gx, x2: gx, y1: top, y2: H - 4, class: k === 0 ? "baseline" : "grid-line" }, s);
    }
    items.forEach((d, i) => {
      const y = top + i * band;
      const bh = 16;
      const by = y + (band - bh) / 2;
      const w = (Math.max(0, d.value || 0) / maxV) * plotW;
      const lab = svg("text", { x: 0, y: by + bh - 3, class: "label-ink" }, s);
      lab.textContent = trunc(String(d.label), Math.floor(labelW / 6.4));
      let mark = null;
      if (w > 0) mark = svg("path", { d: hbarPath(x0, by, w, bh), class: "mark", style: `fill:${opts.color || "var(--series-1)"}` }, s);
      const vt = svg("text", { x: x0 + w + 6, y: by + bh - 3, class: "label-ink" }, s);
      vt.textContent = d.text !== undefined ? d.text : fmt(d.value);
      const hit = svg("rect", { x: 0, y, width: W, height: band, class: "hit", tabindex: 0 }, s);
      attachTip(hit, () => ({ head: String(d.label), rows: [{ label: opts.unit || "giá trị", value: vt.textContent }] }), mark);
    });
  }

  // Cột đứng: dùng cho histogram và chuỗi kỳ theo thời gian.
  function columnChart(node, labels, values, opts) {
    opts = opts || {};
    clearNode(node);
    const n = values.length;
    if (!n || values.every((v) => !v)) return emptyNote(node, opts.empty || "Không có dữ liệu để vẽ.");
    const W = widthOf(node);
    const H = opts.height || 220;
    const left = 48;
    const right = 8;
    const top = 10;
    const bottom = 34;
    const plotW = W - left - right;
    const plotH = H - top - bottom;
    const maxV = niceCeil(Math.max(...values));
    const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.aria || "Biểu đồ cột" }, node);
    for (let k = 0; k <= 4; k++) {
      const v = (maxV * k) / 4;
      const y = top + plotH - (v / maxV) * plotH;
      svg("line", { x1: left, x2: W - right, y1: y, y2: y, class: k === 0 ? "baseline" : "grid-line" }, s);
      const t = svg("text", { x: left - 6, y: y + 4, "text-anchor": "end", class: "axis-text" }, s);
      t.textContent = fmtAxis(v);
    }
    const bw = plotW / n;
    const barW = Math.max(1, bw - 2);
    const step = Math.max(1, Math.ceil(n / Math.max(1, Math.floor(plotW / 70))));
    const ticks = opts.ticks || labels;
    for (let i = 0; i < n; i++) {
      const v = values[i] || 0;
      const x = left + i * bw + (bw - barW) / 2;
      const h = (v / maxV) * plotH;
      const y0 = top + plotH - h;
      let mark = null;
      if (h > 0) mark = svg("path", { d: vbarPath(x, y0, barW, h), class: "mark", style: `fill:${opts.color || "var(--series-1)"}` }, s);
      const hit = svg("rect", { x: left + i * bw, y: top, width: bw, height: plotH, class: "hit", tabindex: 0 }, s);
      attachTip(hit, () => ({ head: String(labels[i]), rows: [{ label: opts.unit || "số dòng", value: fmt(values[i]) }] }), mark);
      if (i % step === 0) {
        const t = svg("text", { x: left + i * bw + bw / 2, y: H - 12, "text-anchor": "middle", class: "axis-text" }, s);
        t.textContent = trunc(String(ticks[i]), 12);
      }
    }
  }

  // Đường: chỉ số x đều nhau theo kỳ, null làm đứt đường. Có đường dọc theo chuột và hỗ trợ phím mũi tên.
  function lineChart(node, xs, series, opts) {
    opts = opts || {};
    clearNode(node);
    const n = xs.length;
    const all = [];
    for (const ser of series) for (const v of ser.values) if (v !== null && v !== undefined) all.push(v);
    if (!n || !all.length) return emptyNote(node, opts.empty || "Không có dữ liệu để vẽ.");
    const W = widthOf(node);
    const H = opts.height || 260;
    const endLabels = series.length <= 4 && W >= 560;
    const left = 56;
    const right = endLabels ? 130 : 12;
    const top = 12;
    const bottom = 34;
    const plotW = W - left - right;
    const plotH = H - top - bottom;
    let lo = Math.min(...all);
    let hi = Math.max(...all);
    if (lo === hi) {
      const pad = Math.abs(lo) * 0.1 || 1;
      lo -= pad;
      hi += pad;
    }
    const span = hi - lo;
    lo -= span * 0.04;
    hi += span * 0.04;
    const X = (i) => (n === 1 ? left + plotW / 2 : left + (i * plotW) / (n - 1));
    const Y = (v) => top + plotH - ((v - lo) / (hi - lo)) * plotH;

    const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.aria || "Biểu đồ đường" }, node);
    for (let k = 0; k <= 4; k++) {
      const v = lo + ((hi - lo) * k) / 4;
      const y = top + plotH - (k / 4) * plotH;
      svg("line", { x1: left, x2: left + plotW, y1: y, y2: y, class: k === 0 ? "baseline" : "grid-line" }, s);
      const t = svg("text", { x: left - 6, y: y + 4, "text-anchor": "end", class: "axis-text" }, s);
      t.textContent = fmtAxis(v);
    }
    const step = Math.max(1, Math.ceil(n / Math.max(1, Math.floor(plotW / 70))));
    for (let i = 0; i < n; i += step) {
      const t = svg("text", { x: X(i), y: H - 12, "text-anchor": "middle", class: "axis-text" }, s);
      t.textContent = trunc(String(xs[i]), 12);
    }

    for (const ser of series) {
      let d = "";
      let pen = false;
      ser.values.forEach((v, i) => {
        if (v === null || v === undefined) {
          pen = false;
          return;
        }
        d += (pen ? "L" : "M") + X(i).toFixed(1) + "," + Y(v).toFixed(1) + " ";
        pen = true;
      });
      if (d) {
        svg("path", { d: d.trim(), style: `fill:none;stroke:${ser.color};stroke-width:2;stroke-linejoin:round;stroke-linecap:round` }, s);
      }
      if (n <= 60) {
        ser.values.forEach((v, i) => {
          if (v === null || v === undefined) return;
          svg("circle", { cx: X(i), cy: Y(v), r: 2.5, style: `fill:${ser.color};stroke:var(--surface-1);stroke-width:1.5` }, s);
        });
      }
    }

    if (endLabels) {
      for (const ser of series) {
        let j = -1;
        for (let i = ser.values.length - 1; i >= 0; i--) {
          if (ser.values[i] !== null && ser.values[i] !== undefined) {
            j = i;
            break;
          }
        }
        if (j < 0) continue;
        const t = svg("text", { x: X(j) + 8, y: Y(ser.values[j]) + 4, class: "label-ink" }, s);
        t.textContent = trunc(ser.name, 18);
      }
    }

    // Đường dọc theo chuột và điểm trên từng đường. Tooltip liệt kê mọi chuỗi tại cùng một x.
    const hair = svg("line", { y1: top, y2: top + plotH, class: "hair", visibility: "hidden" }, s);
    const dots = series.map((ser) => svg("circle", { r: 4, visibility: "hidden", style: `fill:${ser.color};stroke:var(--surface-1);stroke-width:2` }, s));
    const tipFor = (i) => ({
      head: String(xs[i]),
      rows: series
        .filter((ser) => ser.values[i] !== null && ser.values[i] !== undefined)
        .map((ser) => ({ color: ser.color, label: ser.name, value: fmt(ser.values[i]) })),
    });
    let cur = -1;
    const place = (i) => {
      cur = i;
      const x = X(i);
      hair.setAttribute("x1", x);
      hair.setAttribute("x2", x);
      hair.setAttribute("visibility", "visible");
      series.forEach((ser, k) => {
        const v = ser.values[i];
        if (v === null || v === undefined) {
          dots[k].setAttribute("visibility", "hidden");
          return;
        }
        dots[k].setAttribute("cx", x);
        dots[k].setAttribute("cy", Y(v));
        dots[k].setAttribute("visibility", "visible");
      });
    };
    const hide = () => {
      hair.setAttribute("visibility", "hidden");
      dots.forEach((d) => d.setAttribute("visibility", "hidden"));
      cur = -1;
    };
    const overlay = svg("rect", { x: left, y: top, width: plotW, height: plotH, class: "hit", tabindex: 0 }, s);
    const pick = (clientX) => {
      const r = s.getBoundingClientRect();
      const px = (clientX - r.left) * (W / r.width);
      const i = n === 1 ? 0 : Math.round(((px - left) / plotW) * (n - 1));
      return Math.max(0, Math.min(n - 1, i));
    };
    overlay.addEventListener("pointermove", (e) => {
      const i = pick(e.clientX);
      place(i);
      const t = tipFor(i);
      showTip(e.clientX, e.clientY, t.head, t.rows);
    });
    overlay.addEventListener("pointerleave", () => {
      hide();
      hideTip();
    });
    overlay.addEventListener("focus", () => {
      if (cur < 0) place(n - 1);
      const r = overlay.getBoundingClientRect();
      const t = tipFor(cur);
      showTip(r.left + r.width / 2, r.top, t.head, t.rows);
    });
    overlay.addEventListener("blur", () => {
      hide();
      hideTip();
    });
    overlay.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      e.preventDefault();
      const base = cur < 0 ? n - 1 : cur;
      place(Math.max(0, Math.min(n - 1, base + (e.key === "ArrowLeft" ? -1 : 1))));
      const r = overlay.getBoundingClientRect();
      const t = tipFor(cur);
      showTip(r.left + r.width / 2, r.top, t.head, t.rows);
    });

    if (series.length >= 2) {
      const legend = el("div", "legend");
      for (const ser of series) {
        const item = el("span");
        const key = el("i");
        key.style.background = ser.color;
        item.appendChild(key);
        item.appendChild(document.createTextNode(ser.name));
        legend.appendChild(item);
      }
      node.appendChild(legend);
    }
  }

  // Ma trận tương quan: nền là màu giữa (xám), phủ màu cực theo |ρ| bằng fill-opacity. Đúng với nội suy tuyến tính.
  function corrHeatmap(node, names, M) {
    clearNode(node);
    const n = names.length;
    if (n < 2) return emptyNote(node, "Cần ít nhất 2 cột số có đủ dữ liệu để tính tương quan.");
    const W = widthOf(node);
    const labelW = Math.min(150, Math.max(70, names.reduce((m, s) => Math.max(m, s.length), 0) * 6.2));
    const topH = 96;
    const cell = Math.max(24, Math.min(56, (W - labelW) / n));
    const H = topH + n * cell + 4;
    const s = svg("svg", { viewBox: `0 0 ${labelW + n * cell + 4} ${H}`, role: "img", "aria-label": "Ma trận tương quan Spearman" }, node);
    const pos = "var(--div-pos)";
    const neg = "var(--div-neg)";
    for (let i = 0; i < n; i++) {
      const rl = svg("text", { x: labelW - 6, y: topH + i * cell + cell / 2 + 4, "text-anchor": "end", class: "axis-text" }, s);
      rl.textContent = trunc(names[i], Math.floor(labelW / 6.2));
      const cl = svg("text", { x: labelW + i * cell + cell / 2, y: topH - 8, "text-anchor": "start", class: "axis-text", transform: `rotate(-40 ${labelW + i * cell + cell / 2} ${topH - 8})` }, s);
      cl.textContent = trunc(names[i], 16);
    }
    for (let i = 0; i < n; i++) {
      for (let j = 0; j < n; j++) {
        const v = M[i][j];
        const x = labelW + j * cell + 1;
        const y = topH + i * cell + 1;
        const w = cell - 2;
        const h = cell - 2;
        const base = svg("rect", { x, y, width: w, height: h, rx: 3, style: "fill:var(--div-mid)" }, s);
        let mark = null;
        if (v !== null && v !== undefined && Math.abs(v) > 0) {
          mark = svg("rect", { x, y, width: w, height: h, rx: 3, class: "mark", style: `fill:${v >= 0 ? pos : neg};fill-opacity:${Math.min(1, Math.abs(v)).toFixed(3)}` }, s);
        }
        if (n <= 6 && v !== null && v !== undefined) {
          const t = svg("text", { x: x + w / 2, y: y + h / 2 + 4, "text-anchor": "middle", class: "label-ink" }, s);
          t.textContent = fmt(v, 2);
        }
        const hit = svg("rect", { x, y, width: w, height: h, class: "hit", tabindex: 0 }, s);
        attachTip(hit, () => ({
          head: `${names[i]} × ${names[j]}`,
          rows: [{ label: "Spearman ρ", value: v === null || v === undefined ? "—" : fmt(v, 2) }],
        }), mark || base);
      }
    }
    const legend = el("div", "legend");
    legend.appendChild(el("span", "", "Âm"));
    legend.appendChild(el("span", "", "Gần 0"));
    legend.appendChild(el("span", "", "Dương"));
    node.appendChild(legend);
  }

  // Thu nhỏ: chỉ là hình dạng, không có trục. Số liệu nằm trong thẻ và bảng.
  function miniBars(parent, counts) {
    const W = 200;
    const H = 48;
    const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, "aria-hidden": "true", preserveAspectRatio: "none" }, parent);
    const n = counts.length;
    if (!n) return;
    const maxC = Math.max(...counts, 1);
    const bw = W / n;
    counts.forEach((c, i) => {
      const h = (c / maxC) * (H - 4);
      if (h <= 0) return;
      svg("rect", { x: i * bw + 1, y: H - h, width: Math.max(1, bw - 2), height: h, rx: 1.5, style: "fill:var(--series-1)" }, s);
    });
  }

  // ---------- bảng dữ liệu đi kèm ----------
  function tableFrom(node, headers, rows, opts) {
    clearNode(node);
    opts = opts || {};
    const t = document.createElement("table");
    const thead = document.createElement("thead");
    const hr = document.createElement("tr");
    headers.forEach((h) => hr.appendChild(el("th", opts.numericCols && opts.numericCols.includes(h) ? "num" : "", h)));
    thead.appendChild(hr);
    t.appendChild(thead);
    const tbody = document.createElement("tbody");
    for (const r of rows) {
      const tr = document.createElement("tr");
      r.forEach((v, j) => {
        const numeric = typeof v === "number" || (opts.numericCols && opts.numericCols.includes(headers[j]));
        tr.appendChild(el("td", numeric ? "num" : "", v === null || v === undefined ? "—" : v));
      });
      tbody.appendChild(tr);
    }
    t.appendChild(tbody);
    node.appendChild(t);
    if (opts.note) node.appendChild(el("p", "disclaimer", opts.note));
  }

  function statBlock(dl, label, value) {
    const wrap = el("div");
    wrap.appendChild(el("dt", "", label));
    wrap.appendChild(el("dd", "", value));
    dl.appendChild(wrap);
  }

  // ---------- tổng quan ----------
  function renderKpis() {
    const k = DATA.kpis;
    const box = $("kpis");
    clearNode(box);
    const card = (value, label, cls) => {
      const d = el("div", "kpi");
      const b = el("b", cls || "", value);
      d.appendChild(b);
      d.appendChild(el("span", "", label));
      box.appendChild(d);
    };
    card(fmt(k.rows, 0), "Số dòng");
    card(fmt(k.columns, 0), "Số cột");
    card(k.missing_share_mean === null ? "—" : pct(k.missing_share_mean), "Thiếu trung bình");
    card(k.duplicate_rows === null ? "—" : fmt(k.duplicate_rows, 0), "Dòng trùng");
    card(fmt(k.n_critical, 0), "Nghiêm trọng", "sev CRITICAL");
    card(fmt(k.n_warn, 0), "Cảnh báo", "sev WARN");
    card(fmt(k.n_info, 0), "Thông tin", "sev INFO");
  }

  function renderOverview() {
    // Số liệu toàn bảng, không đổi theo bộ lọc.
    const withMissing = COLS.filter((c) => c.missing_share !== null).sort((a, b) => b.missing_share - a.missing_share).slice(0, 25);
    const missItems = withMissing.map((c) => ({ label: c.name, value: c.missing_share, text: pct(c.missing_share) }));
    hbarChart($("chart-missing"), missItems, { unit: "tỷ lệ thiếu", aria: "Tỷ lệ thiếu theo cột", empty: "Không có cột nào." });
    tableFrom($("table-missing"), ["Cột", "Tỷ lệ thiếu"], withMissing.map((c) => [c.name, pct(c.missing_share)]), { numericCols: ["Tỷ lệ thiếu"] });

    const kindCounts = new Map();
    for (const c of COLS) kindCounts.set(c.kind_label, (kindCounts.get(c.kind_label) || 0) + 1);
    const kindItems = [...kindCounts.entries()].sort((a, b) => b[1] - a[1]).map(([label, value]) => ({ label, value }));
    hbarChart($("chart-kinds"), kindItems, { unit: "số cột", aria: "Số cột theo loại" });
    tableFrom($("table-kinds"), ["Loại", "Số cột"], kindItems.map((d) => [d.label, d.value]), { numericCols: ["Số cột"] });

    // Lưới thu nhỏ theo bộ lọc hiện tại.
    const grid = $("mini-grid");
    clearNode(grid);
    for (const c of COLS.slice(0, 36)) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "mini";
      btn.setAttribute("aria-label", `Mở chi tiết cột ${c.name}`);
      btn.appendChild(el("b", "", c.name));
      btn.appendChild(el("span", "", c.kind_label));
      const vals = filteredValues(c).filter((v) => v !== null && v !== undefined);
      if (c.kind === "numeric" || c.kind === "mixed") {
        const h = histogram(vals, 20);
        if (h) miniBars(btn, h.counts);
        else btn.appendChild(el("span", "", "Không có số liệu"));
      } else if (c.kind === "categorical" || c.kind === "boolean" || c.kind === "id") {
        const counts = new Map();
        for (const v of vals) counts.set(String(v), (counts.get(String(v)) || 0) + 1);
        const top = [...counts.values()].sort((a, b) => b - a).slice(0, 8);
        if (top.length) miniBars(btn, top);
        else btn.appendChild(el("span", "", "Không có dữ liệu"));
        btn.appendChild(el("span", "", `${counts.size} giá trị khác nhau`));
      } else if (c.kind === "datetime") {
        const sorted = vals.slice().sort();
        btn.appendChild(el("span", "", sorted.length ? `${sorted[0].slice(0, 10)} → ${sorted[sorted.length - 1].slice(0, 10)}` : "Không có ngày"));
      } else {
        btn.appendChild(el("span", "", `${new Set(vals.map(String)).size} giá trị khác nhau`));
      }
      btn.addEventListener("click", () => {
        state.col = c.name;
        $("col-select").value = c.name;
        showTab("columns");
      });
      grid.appendChild(btn);
    }
  }

  // ---------- chi tiết cột ----------
  function renderColumn() {
    const c = BY.get(state.col);
    if (!c) return;
    $("col-title").textContent = c.name;
    $("col-note").textContent =
      `${c.kind_label} · vai trò kỹ thuật ${c.role} · độ tin cậy ${(c.confidence * 100).toFixed(0)}% · thiếu ${pct(c.missing_share)} trên toàn bảng`;
    const vals = filteredValues(c);
    const present = vals.filter((v) => v !== null && v !== undefined);
    const missing = vals.length - present.length;
    const dl = $("col-stats");
    clearNode(dl);
    statBlock(dl, "Số dòng", fmt(vals.length, 0));
    statBlock(dl, "Thiếu", vals.length ? pct(missing / vals.length) : "—");

    const chartNode = $("chart-column");
    const tableNode = $("table-column");

    if (c.kind === "numeric" || c.kind === "mixed") {
      const nums = present.map(Number);
      const d = describe(nums);
      statBlock(dl, "Trung bình", fmt(d.mean));
      statBlock(dl, "Trung vị", fmt(d.median));
      statBlock(dl, "Độ lệch chuẩn", fmt(d.sd));
      statBlock(dl, "P05", fmt(d.p05));
      statBlock(dl, "P95", fmt(d.p95));
      statBlock(dl, "Nhỏ nhất", fmt(d.min));
      statBlock(dl, "Lớn nhất", fmt(d.max));
      const h = histogram(nums, META.histogram_bins);
      if (h) {
        columnChart(chartNode, h.labels, h.counts, { unit: "số dòng", ticks: h.lows, aria: `Phân bố của ${c.name}` });
        tableFrom(tableNode, ["Khoảng", "Số dòng"], h.labels.map((l, i) => [l, h.counts[i]]), { numericCols: ["Số dòng"] });
      } else {
        emptyNote(chartNode, "Không có số liệu trong phạm vi lọc.");
        tableNode.replaceChildren();
      }
      $("col-note").textContent += c.kind === "mixed" && c.text_part_count
        ? ` · ${fmt(c.text_part_count, 0)} giá trị không phải số đã bị bỏ qua ở biểu đồ`
        : "";
    } else if (c.kind === "datetime") {
      const sorted = present.slice().sort();
      statBlock(dl, "Từ", sorted.length ? sorted[0].slice(0, 10) : "—");
      statBlock(dl, "Đến", sorted.length ? sorted[sorted.length - 1].slice(0, 10) : "—");
      if (sorted.length) {
        const a = sorted[0].slice(0, 10);
        const b = sorted[sorted.length - 1].slice(0, 10);
        const gran = granularityFor(a, b);
        const keys = keysBetween(gran, periodKey(a, gran), periodKey(b, gran));
        const pos = new Map(keys.map((k, i) => [k, i]));
        const counts = new Array(keys.length).fill(0);
        for (const v of present) {
          const p = pos.get(periodKey(v, gran));
          if (p !== undefined) counts[p] += 1;
        }
        columnChart(chartNode, keys, counts, { unit: "số dòng", aria: `Số dòng theo ${gran} của ${c.name}` });
        tableFrom(tableNode, ["Kỳ", "Số dòng"], keys.map((k, i) => [k, counts[i]]), { numericCols: ["Số dòng"] });
      } else {
        emptyNote(chartNode, "Không có ngày trong phạm vi lọc.");
        tableNode.replaceChildren();
      }
    } else {
      const counts = new Map();
      for (const v of present) counts.set(String(v), (counts.get(String(v)) || 0) + 1);
      const entries = [...counts.entries()].sort((a, b) => b[1] - a[1]);
      statBlock(dl, "Giá trị khác nhau", fmt(counts.size, 0));
      if (entries.length) statBlock(dl, "Phổ biến nhất", trunc(entries[0][0], 30));
      const top = entries.slice(0, 20);
      const other = entries.slice(20).reduce((s, e) => s + e[1], 0);
      const share = (v) => (vals.length ? pct(v / vals.length) : "—");
      const items = top.map(([k, v]) => ({
        label: c.kind === "boolean" ? (k === "true" ? "Đúng" : "Sai") : k,
        value: v,
        text: `${fmt(v, 0)} (${share(v)})`,
      }));
      if (missing > 0) items.push({ label: "(thiếu)", value: missing, text: `${fmt(missing, 0)} (${share(missing)})` });
      hbarChart(chartNode, items, { unit: "số dòng", aria: `Phân bố của ${c.name}`, empty: "Không có giá trị trong phạm vi lọc." });
      const tableRows = items.map((d) => [d.label, d.value, vals.length ? pct(d.value / vals.length) : "—"]);
      tableFrom(tableNode, ["Giá trị", "Số dòng", "Tỷ lệ"], tableRows, { numericCols: ["Số dòng", "Tỷ lệ"] });
      if (entries.length > 20) {
        tableNode.appendChild(el("p", "disclaimer", `Còn ${fmt(entries.length - 20, 0)} giá trị khác (${fmt(other, 0)} dòng), không hiện trong biểu đồ.`));
      }
    }
  }

  // ---------- quan hệ ----------
  function rankAvg(a) {
    const idx = a.map((_, i) => i).sort((i, j) => a[i] - a[j]);
    const r = new Array(a.length);
    let i = 0;
    while (i < idx.length) {
      let j = i;
      while (j + 1 < idx.length && a[idx[j + 1]] === a[idx[i]]) j++;
      const avg = (i + j) / 2 + 1;
      for (let k = i; k <= j; k++) r[idx[k]] = avg;
      i = j + 1;
    }
    return r;
  }

  function pearson(x, y) {
    const n = x.length;
    if (n < 3) return null;
    const mx = x.reduce((s, v) => s + v, 0) / n;
    const my = y.reduce((s, v) => s + v, 0) / n;
    let sxy = 0;
    let sxx = 0;
    let syy = 0;
    for (let i = 0; i < n; i++) {
      const dx = x[i] - mx;
      const dy = y[i] - my;
      sxy += dx * dy;
      sxx += dx * dx;
      syy += dy * dy;
    }
    if (sxx === 0 || syy === 0) return null;
    return sxy / Math.sqrt(sxx * syy);
  }

  function spearman(a, b) {
    const xs = [];
    const ys = [];
    for (let i = 0; i < a.length; i++) {
      if (a[i] !== null && a[i] !== undefined && b[i] !== null && b[i] !== undefined) {
        xs.push(a[i]);
        ys.push(b[i]);
      }
    }
    if (xs.length < 3) return null;
    return pearson(rankAvg(xs), rankAvg(ys));
  }

  function renderRelations() {
    const numericCols = COLS.filter((c) => c.kind === "numeric").slice(0, META.heatmap_max_columns);
    const names = numericCols.map((c) => c.name);
    const arrays = numericCols.map((c) => filteredValues(c));
    const M = names.map((_, i) => names.map((_, j) => (i === j ? 1 : spearman(arrays[i], arrays[j]))));
    corrHeatmap($("chart-heatmap"), names, M);
    const rows = [];
    for (let i = 0; i < names.length; i++) {
      for (let j = i + 1; j < names.length; j++) {
        rows.push([names[i], names[j], M[i][j] === null ? "—" : fmt(M[i][j], 2)]);
      }
    }
    tableFrom($("table-heatmap"), ["Cột A", "Cột B", "Spearman ρ"], rows, {
      numericCols: ["Spearman ρ"],
      note: rows.length ? "" : "Cần ít nhất hai cột số để có ma trận.",
    });

    const rel = DATA.relations.slice(0, 300);
    const relRows = rel.map((r) => [
      r.col_a,
      r.col_b,
      r.test || "—",
      r.effect === null ? "—" : `${r.effect_name || "hiệu ứng"} = ${fmt(r.effect, 3)}`,
      r.p_value === null ? "—" : fmt(r.p_value, 4),
      r.q_value === null ? "—" : fmt(r.q_value, 4),
      r.significant ? "Có" : "Không",
    ]);
    tableFrom($("table-relations"), ["Cột A", "Cột B", "Kiểm định", "Hiệu ứng", "p", "q (BH)", "Có ý nghĩa"], relRows, {
      numericCols: ["p", "q (BH)"],
      note: DATA.relations.length > rel.length ? `Hiển thị ${rel.length} / ${DATA.relations.length} cặp.` : "",
    });
  }

  // ---------- thời gian ----------
  function buildTimeToolbar() {
    const bar = $("time-toolbar");
    clearNode(bar);
    const mSel = document.createElement("select");
    mSel.setAttribute("aria-label", "Cột số để vẽ");
    for (const c of COLS.filter((c) => c.kind === "numeric" || c.kind === "mixed")) mSel.appendChild(new Option(c.name, c.name));
    mSel.addEventListener("change", () => {
      state.tsMeasure = mSel.value;
      renderTab();
    });
    const aSel = document.createElement("select");
    aSel.setAttribute("aria-label", "Cách tổng hợp");
    aSel.appendChild(new Option("Trung bình", "mean"));
    aSel.appendChild(new Option("Tổng", "sum"));
    aSel.appendChild(new Option("Số dòng", "count"));
    aSel.addEventListener("change", () => {
      state.tsAgg = aSel.value;
      renderTab();
    });
    const modeSel = document.createElement("select");
    modeSel.setAttribute("aria-label", "Cách tách chuỗi");
    modeSel.appendChild(new Option("Tổng hợp", "total"));
    modeSel.appendChild(new Option("Theo thực thể (tối đa " + META.series_max + ")", "entity"));
    modeSel.disabled = !(META.entity_column && BY.has(META.entity_column));
    modeSel.addEventListener("change", () => {
      state.tsMode = modeSel.value;
      renderTab();
    });
    const wrap = (text, sel) => {
      const l = el("label");
      l.appendChild(el("span", "", text));
      l.appendChild(sel);
      return l;
    };
    bar.appendChild(wrap("Cột số", mSel));
    bar.appendChild(wrap("Tổng hợp", aSel));
    bar.appendChild(wrap("Chuỗi", modeSel));
    mSel.value = state.tsMeasure;
    aSel.value = state.tsAgg;
    modeSel.value = state.tsMode;
  }

  // Thực thể được xếp theo số dòng trên toàn mẫu, để màu của một thực thể không đổi khi lọc.
  let ENTITY_ORDER = null;
  function entityOrder() {
    if (ENTITY_ORDER) return ENTITY_ORDER;
    const ecol = META.entity_column && BY.get(META.entity_column);
    if (!ecol) return (ENTITY_ORDER = []);
    const counts = new Map();
    for (const v of ecol.values) {
      if (v === null || v === undefined) continue;
      const name = entName(v);
      counts.set(name, (counts.get(name) || 0) + 1);
    }
    ENTITY_ORDER = [...counts.entries()].sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1)).map((e) => e[0]);
    return ENTITY_ORDER;
  }

  function aggregateRows(rows, mcol, tcol, gran, keys, pos, agg) {
    const sum = new Array(keys.length).fill(0);
    const cnt = new Array(keys.length).fill(0);
    const rowCnt = new Array(keys.length).fill(0);
    for (const i of rows) {
      const p = pos.get(periodKey(tcol.values[i], gran));
      if (p === undefined) continue;
      rowCnt[p] += 1;
      const v = mcol.values[i];
      if (v === null || v === undefined) continue;
      sum[p] += Number(v);
      cnt[p] += 1;
    }
    return keys.map((_, p) => {
      if (agg === "count") return rowCnt[p];
      if (cnt[p] === 0) return null;
      return agg === "sum" ? sum[p] : sum[p] / cnt[p];
    });
  }

  function renderTime() {
    const node = $("chart-time");
    const note = $("time-note");
    const tcol = META.time_column && BY.get(META.time_column);
    if (!tcol) {
      emptyNote(node, "Không có cột thời gian được nhận diện trong bảng.");
      note.textContent = "";
      $("time-facts-card").hidden = true;
      $("table-time").replaceChildren();
      return;
    }
    const mcol = BY.get(state.tsMeasure);
    const rows = state.idx.filter((i) => tcol.values[i] !== null && tcol.values[i] !== undefined);
    const stamps = rows.map((i) => String(tcol.values[i]).slice(0, 10)).sort();
    if (!stamps.length || !mcol) {
      emptyNote(node, "Không có dòng có thời gian trong phạm vi lọc.");
      $("table-time").replaceChildren();
      return;
    }
    const minKey = stamps[0];
    const maxKey = stamps[stamps.length - 1];
    const gran = granularityFor(minKey, maxKey);
    const keys = keysBetween(gran, periodKey(minKey, gran), periodKey(maxKey, gran));
    const pos = new Map(keys.map((k, i) => [k, i]));
    const aggLabel = { mean: "trung bình", sum: "tổng", count: "số dòng" }[state.tsAgg];
    const granLabel = { day: "ngày", month: "tháng", year: "năm" }[gran];
    $("time-title").textContent = `${mcol.name} theo ${granLabel}`;
    note.textContent = `Tổng hợp: ${aggLabel}. Cột thời gian: ${tcol.name}. Mỗi điểm là một ${granLabel}; kỳ không có dòng nào hiện là khoảng trống.`;
    if (META.sampled) note.textContent += " Dữ liệu là mẫu.";

    let series;
    if (state.tsMode === "entity" && META.entity_column && BY.get(META.entity_column)) {
      const ecol = BY.get(META.entity_column);
      const order = entityOrder();
      const top = order.slice(0, META.series_max);
      const topSet = new Set(top);
      series = [];
      top.forEach((name, k) => {
        const sub = rows.filter((i) => entName(ecol.values[i]) === name);
        series.push({ name: trunc(name, 24), color: `var(--series-${k + 1})`, values: aggregateRows(sub, mcol, tcol, gran, keys, pos, state.tsAgg) });
      });
      const others = rows.filter((i) => ecol.values[i] !== null && ecol.values[i] !== undefined && !topSet.has(entName(ecol.values[i])));
      if (others.length) {
        series.push({ name: "Khác", color: "var(--text-muted)", values: aggregateRows(others, mcol, tcol, gran, keys, pos, state.tsAgg) });
      }
      series = series.filter((s) => s.values.some((v) => v !== null));
    } else {
      series = [{ name: `${mcol.name} (${aggLabel})`, color: "var(--series-1)", values: aggregateRows(rows, mcol, tcol, gran, keys, pos, state.tsAgg) }];
    }

    lineChart(node, keys, series, { aria: `${mcol.name} theo thời gian` });
    const head = ["Kỳ", ...series.map((s) => s.name)];
    const body = keys.map((k, i) => [k, ...series.map((s) => (s.values[i] === null ? "—" : fmt(s.values[i])))]);
    tableFrom($("table-time"), head, body, { numericCols: head.slice(1) });

    const facts = DATA.findings.filter((f) => /^(temporal|panel|hierarchy|constraint)/.test(f.id) || /^(temporal|panel|hierarchy|constraint)\./.test(f.id));
    const card = $("time-facts-card");
    card.hidden = facts.length === 0;
    tableFrom($("time-facts"), ["Mức", "Phạm vi", "Thông điệp", "Gợi ý"], facts.map((f) => [`${SEV_ICON[f.severity] || ""} ${SEV_LABEL[f.severity] || f.severity}`, f.scope, f.message, f.suggestion]));
  }

  // ---------- phát hiện ----------
  function buildSevToolbar() {
    const bar = $("sev-toolbar");
    clearNode(bar);
    const levels = ["ALL", "CRITICAL", "WARN", "INFO"];
    for (const lv of levels) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "sev-chip";
      b.dataset.level = lv;
      b.addEventListener("click", () => {
        state.sev = lv;
        renderFindings();
      });
      bar.appendChild(b);
    }
  }

  function renderFindings() {
    const counts = { ALL: DATA.findings.length, CRITICAL: 0, WARN: 0, INFO: 0 };
    for (const f of DATA.findings) counts[f.severity] = (counts[f.severity] || 0) + 1;
    for (const b of $("sev-toolbar").querySelectorAll("button")) {
      const lv = b.dataset.level;
      const text = lv === "ALL" ? "Tất cả" : SEV_LABEL[lv];
      b.textContent = `${text} (${counts[lv] || 0})`;
      b.setAttribute("aria-pressed", String(state.sev === lv));
    }
    const shown = DATA.findings.filter((f) => state.sev === "ALL" || f.severity === state.sev);
    tableFrom($("table-findings"), ["Mức", "Phạm vi", "Thông điệp", "Gợi ý", "Mã"],
      shown.slice(0, 300).map((f) => [`${SEV_ICON[f.severity] || ""} ${SEV_LABEL[f.severity] || f.severity}`, f.scope, f.message, f.suggestion, f.id]),
      { note: shown.length > 300 ? `Hiển thị 300 / ${shown.length} phát hiện.` : shown.length ? "" : "Không có phát hiện ở mức này." });
  }

  // ---------- bảng dữ liệu ----------
  function csvEscape(v) {
    if (v === null || v === undefined) return "";
    const s = typeof v === "boolean" ? (v ? "TRUE" : "FALSE") : String(v);
    return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }

  function renderData() {
    const preview = META.table_preview_rows;
    const shown = state.idx.slice(0, preview);
    const numericNames = COLS.filter((c) => c.kind === "numeric" || c.kind === "mixed").map((c) => c.name);
    const rows = shown.map((i) => COLS.map((c) => c.values[i]));
    tableFrom($("table-data"), COLS.map((c) => c.name), rows.map((r) => r.map((v) => (typeof v === "boolean" ? (v ? "Đúng" : "Sai") : v))), {
      numericCols: numericNames,
      note: state.idx.length > preview ? `Hiển thị ${preview} / ${state.idx.length} dòng đã lọc.` : "",
    });
    $("data-note").textContent = `Dữ liệu trong dashboard là mẫu ${NROWS} dòng${META.sampled ? ` trên tổng ${META.total_rows} dòng` : ""}.`;
  }

  function downloadCsv() {
    const lines = [COLS.map((c) => csvEscape(c.name)).join(",")];
    for (const i of state.idx) lines.push(COLS.map((c) => csvEscape(c.values[i])).join(","));
    const blob = new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = String(META.name || "du_lieu").replace(/[^A-Za-z0-9_-]+/g, "_") + "_loc_mau.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  // ---------- điều phối ----------
  function renderTab() {
    updateFilterMeta();
    switch (state.tab) {
      case "overview":
        return renderOverview();
      case "columns":
        return renderColumn();
      case "relations":
        return renderRelations();
      case "time":
        return renderTime();
      case "findings":
        return renderFindings();
      case "data":
        return renderData();
      default:
        return undefined;
    }
  }

  const TAB_NAMES = ["overview", "columns", "relations", "time", "findings", "data"];

  function showTab(name) {
    state.tab = name;
    for (const t of TAB_NAMES) {
      const btn = $("tab-" + t);
      const panel = $("panel-" + t);
      const on = t === name;
      btn.setAttribute("aria-selected", String(on));
      btn.tabIndex = on ? 0 : -1;
      panel.hidden = !on;
    }
    renderTab();
  }

  function currentTheme() {
    const t = document.documentElement.getAttribute("data-theme");
    if (t === "light" || t === "dark") return t;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function setupTheme() {
    try {
      const saved = window.localStorage.getItem("tseda-theme");
      if (saved === "light" || saved === "dark") document.documentElement.setAttribute("data-theme", saved);
    } catch (e) {
      /* trình duyệt chặn localStorage: dùng theme của hệ điều hành */
    }
    const btn = $("theme-toggle");
    const label = () => {
      btn.textContent = currentTheme() === "dark" ? "Chế độ sáng" : "Chế độ tối";
    };
    label();
    btn.addEventListener("click", () => {
      const next = currentTheme() === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      try {
        window.localStorage.setItem("tseda-theme", next);
      } catch (e) {
        /* bỏ qua: chỉ là tiện ích, không ảnh hưởng dữ liệu */
      }
      label();
      renderTab();
    });
  }

  function init() {
    setupTheme();
    $("title").textContent = "tseda · " + META.name;
    const sub = `${fmt(DATA.kpis.rows, 0)} dòng × ${fmt(DATA.kpis.columns, 0)} cột · tạo lúc ${META.generated_at} · nguồn: ${META.source}`;
    $("subtitle").textContent = sub + (META.sampled ? ` · dashboard dùng mẫu ${NROWS} dòng` : "");
    if (META.columns_truncated) $("subtitle").textContent += ` · chỉ hiện ${COLS.length} / ${META.columns_total} cột`;
    if (META.stage_errors && META.stage_errors.length) {
      $("subtitle").textContent += ` · có ${META.stage_errors.length} lỗi giai đoạn, xem báo cáo HTML`;
    }

    renderKpis();
    const firstNumeric = COLS.find((c) => c.kind === "numeric" || c.kind === "mixed");
    state.tsMeasure = firstNumeric ? firstNumeric.name : null;
    buildFilters();
    buildTimeToolbar();
    buildSevToolbar();

    const colSel = $("col-select");
    clearNode(colSel);
    for (const c of COLS) colSel.appendChild(new Option(c.name, c.name));
    state.col = (COLS.find((c) => c.kind === "numeric") || COLS[0] || {}).name || null;
    colSel.value = state.col || "";
    colSel.addEventListener("change", () => {
      state.col = colSel.value;
      renderTab();
    });

    $("filter-reset").addEventListener("click", () => {
      state.filters.clear();
      buildFilters();
      applyFilters();
    });
    $("csv-download").addEventListener("click", downloadCsv);

    for (const t of TAB_NAMES) {
      $("tab-" + t).addEventListener("click", () => showTab(t));
    }
    document.querySelector(".tabs").addEventListener("keydown", (e) => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      const cur = TAB_NAMES.indexOf(state.tab);
      const next = (cur + (e.key === "ArrowRight" ? 1 : TAB_NAMES.length - 1)) % TAB_NAMES.length;
      e.preventDefault();
      showTab(TAB_NAMES[next]);
      $("tab-" + TAB_NAMES[next]).focus();
    });

    let resizeTimer = null;
    window.addEventListener("resize", () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(renderTab, 150);
    });

    computeIdx();
    showTab("overview");
  }

  init();
})();
