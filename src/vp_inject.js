// Injected into every page: pointer circle, snapping to interactive elements,
// pinch/dwell selection, and a sticky highlight on the selected element.
(() => {
  if (window.__vp) return;
  const SELECTOR = 'a[href], button, input, select, textarea, summary, [role=button], [role=link], [onclick], [tabindex]:not([tabindex="-1"])';
  // dwellMs 0 = dwell selection off (pinch is the main trigger)
  const state = { radius: 50, snap: true, dwellMs: 0, hysteresis: 20, cur: null, since: 0, fired: false, boxes: [], boxesAt: -Infinity, selected: null };

  const mk = (css) => { const d = document.createElement('div'); d.style.cssText = 'position:fixed;pointer-events:none;z-index:2147483647;display:none;box-sizing:border-box;' + css; document.documentElement.appendChild(d); return d; };
  let circle, hover, sel, label, ready = false;
  function init() {
    if (ready || !document.documentElement) return;
    ready = true;
    circle = mk('width:40px;height:40px;margin:-20px 0 0 -20px;border-radius:50%;background:rgba(0,0,255,.85);');
    hover = mk('border:3px solid #00f;border-radius:4px;');
    sel = mk('border:4px solid #0a0;border-radius:4px;background:rgba(0,170,0,.15);');
    label = mk('background:#0a0;color:#fff;font:12px sans-serif;padding:2px 6px;border-radius:3px;');
    label.textContent = 'selected';
    requestAnimationFrame(drawSelected);
  }

  function place(box, r, pad) {
    box.style.display = 'block';
    box.style.left = r.left - pad + 'px'; box.style.top = r.top - pad + 'px';
    box.style.width = r.width + 2 * pad + 'px'; box.style.height = r.height + 2 * pad + 'px';
  }

  // Follows the selected element every frame so the highlight survives scrolling/layout changes.
  function drawSelected() {
    if (state.selected && !state.selected.isConnected) state.selected = null;
    if (state.selected) {
      const r = state.selected.getBoundingClientRect();
      place(sel, r, 4);
      label.style.display = 'block';
      label.style.left = r.left - 4 + 'px';
      label.style.top = Math.max(r.top - 24, 0) + 'px';
    } else {
      sel.style.display = label.style.display = 'none';
    }
    requestAnimationFrame(drawSelected);
  }

  function cssPath(el) {
    if (el.id) return '#' + CSS.escape(el.id);
    const parts = [];
    while (el && el.nodeType === 1 && el !== document.body) {
      const sib = [...el.parentNode.children].filter((c) => c.tagName === el.tagName);
      parts.unshift(el.tagName.toLowerCase() + (sib.length > 1 ? `:nth-of-type(${sib.indexOf(el) + 1})` : ''));
      el = el.parentNode;
    }
    return 'body > ' + parts.join(' > ');
  }

  function info(el) {
    const r = el.getBoundingClientRect();
    const attrs = {};
    for (const a of el.attributes) attrs[a.name] = a.value.slice(0, 200);
    return {
      selector: cssPath(el), tag: el.tagName.toLowerCase(), id: el.id || null,
      text: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 200),
      attrs, html: el.outerHTML.slice(0, 500),
      bbox: { x: r.x, y: r.y, w: r.width, h: r.height },
      page: { url: location.href, title: document.title, viewport: { w: innerWidth, h: innerHeight }, scroll: { x: scrollX, y: scrollY } },
    };
  }

  function refresh() {
    const now = performance.now();
    if (now - state.boxesAt < 200) return;
    state.boxesAt = now;
    state.boxes = [];
    for (const el of document.querySelectorAll(SELECTOR)) {
      if (el.disabled || el.type === 'hidden') continue;
      const r = el.getBoundingClientRect();
      if (r.width < 1 || r.height < 1 || r.bottom < 0 || r.right < 0 || r.top > innerHeight || r.left > innerWidth) continue;
      const cs = getComputedStyle(el);
      if (cs.visibility === 'hidden' || cs.display === 'none') continue;
      state.boxes.push({ el, r });
    }
  }

  const dist = (r, x, y) => Math.hypot(Math.max(r.left - x, 0, x - r.right), Math.max(r.top - y, 0, y - r.bottom));

  // Closest interactive element to (x,y) honouring snap/radius; also reports the current element's distance.
  function pick(x, y) {
    let best = null, bestD = Infinity, curD = Infinity;
    for (const b of state.boxes) {
      const d = dist(b.r, x, y);
      if (b.el === state.cur) curD = d;
      if (d < bestD) { bestD = d; best = b; }
    }
    if (!state.snap) { if (bestD > 0) best = null; }      // snapping off: only exact hits count
    else if (bestD > state.radius) best = null;
    return { best, bestD, curD };
  }

  function choose(el) {
    state.selected = el;
    const data = info(el);
    console.log('VP_SELECT ' + JSON.stringify(data));
    document.dispatchEvent(new CustomEvent('vpselect', { detail: data }));
  }

  window.__vp = {
    configure(o) { Object.assign(state, o); },
    // x,y in viewport pixels, or null when no hand is visible.
    update(x, y, pinching) {
      init();
      if (x === null) { circle.style.display = hover.style.display = 'none'; state.cur = null; return; }
      refresh();
      circle.style.display = 'block';
      circle.style.left = x + 'px'; circle.style.top = y + 'px';
      circle.style.background = pinching ? 'rgba(0,170,0,.9)' : 'rgba(0,0,255,.85)';

      let { best, bestD, curD } = pick(x, y);
      // hysteresis: keep the current element unless another is clearly closer
      if (best && state.cur && best.el !== state.cur && curD <= state.radius && curD - bestD < state.hysteresis) {
        best = state.boxes.find((b) => b.el === state.cur);
      }
      const el = best ? best.el : null;
      if (el !== state.cur) { state.cur = el; state.since = performance.now(); state.fired = false; }
      if (!el) { hover.style.display = 'none'; return; }

      place(hover, best.r, 3);
      if (state.dwellMs > 0 && !state.fired && performance.now() - state.since >= state.dwellMs) { state.fired = true; choose(el); }
    },
    // Pinch: select the element nearest (x,y); pinching empty space clears the selection.
    selectAt(x, y) {
      init(); refresh();
      const { best } = pick(x, y);
      if (best) choose(best.el);
      else this.clear();
    },
    clear() {
      if (state.selected) { state.selected = null; console.log('VP_CLEAR'); }
    },
  };
  addEventListener('keydown', (e) => { if (e.key === 'Escape') console.log('VP_QUIT'); });
})();
