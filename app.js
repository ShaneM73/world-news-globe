/* World News Globe - front end
 * Reads data/latest.json (written daily by scripts/fetch_news.py)
 * and plots each story on a Globe.gl 3D earth.
 */
(() => {
  "use strict";

  const TEXTURES = "https://cdn.jsdelivr.net/npm/three-globe@2.45.3/example/img/";

  // Five impact tiers: 5 = biggest story of the day
  const TIERS = {
    5: { name: "Major", color: "#ff3b5c", alt: 0.16, radius: 0.75, ring: 6.5, speed: 2.4, period: 700 },
    4: { name: "High", color: "#fb923c", alt: 0.11, radius: 0.6, ring: 5, speed: 2, period: 1000 },
    3: { name: "Notable", color: "#facc15", alt: 0.07, radius: 0.45, ring: 3.6, speed: 1.6, period: 1500 },
    2: { name: "Moderate", color: "#4ade80", alt: 0.04, radius: 0.35, ring: 2.4, speed: 1.2, period: 2200 },
    1: { name: "Minor", color: "#4cc9f0", alt: 0.02, radius: 0.25, ring: 0, speed: 0, period: 0 },
  };

  const $ = (id) => document.getElementById(id);
  const state = { stories: [], hiddenTiers: new Set(), query: "", selected: null };

  // ---------- helpers ----------
  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "#");
  const hexToRgba = (hex, a) => {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`;
  };
  const fmt = (n) => Number(n || 0).toLocaleString();

  // Spread out stories pinned to exactly the same spot so each stays clickable
  function spread(stories) {
    const seen = {};
    for (const s of stories) {
      const key = `${s.lat.toFixed(2)},${s.lng.toFixed(2)}`;
      const n = (seen[key] = (seen[key] || 0) + 1) - 1;
      s._lat = s.lat;
      s._lng = s.lng;
      if (n > 0) {
        const angle = n * 2.4;
        const r = 0.9 * Math.sqrt(n);
        s._lat += r * Math.sin(angle);
        s._lng += r * Math.cos(angle);
      }
    }
    return stories;
  }

  // ---------- globe ----------
  const globe = new Globe($("globe"), { animateIn: true })
    .globeImageUrl(TEXTURES + "earth-night.jpg")
    .bumpImageUrl(TEXTURES + "earth-topology.png")
    .backgroundImageUrl(TEXTURES + "night-sky.png")
    .atmosphereColor("#5aa9ff")
    .atmosphereAltitude(0.22)
    // bars
    .pointLat("_lat")
    .pointLng("_lng")
    .pointAltitude((d) => TIERS[d.tier].alt)
    .pointRadius((d) => TIERS[d.tier].radius)
    .pointColor((d) => (state.selected === d ? "#ffffff" : TIERS[d.tier].color))
    .pointResolution(8)
    .pointsMerge(false)
    .pointsTransitionDuration(800)
    .pointLabel(
      (d) =>
        `<div class="tip"><b>${esc(d.title)}</b><span>${esc(d.location || d.country)} · ${esc(
          TIERS[d.tier].name
        )} impact · ${fmt(d.articles)} articles</span></div>`
    )
    .onPointClick((d) => select(d))
    // pulsing shock-wave rings
    .ringLat("_lat")
    .ringLng("_lng")
    .ringColor((d) => (t) => hexToRgba(TIERS[d.tier].color, Math.max(0, 1 - t)))
    .ringMaxRadius((d) => TIERS[d.tier].ring)
    .ringPropagationSpeed((d) => TIERS[d.tier].speed)
    .ringRepeatPeriod((d) => TIERS[d.tier].period)
    // flashing beacons for the biggest stories
    .htmlLat("_lat")
    .htmlLng("_lng")
    .htmlAltitude((d) => TIERS[d.tier].alt)
    .htmlElement((d) => {
      const el = document.createElement("div");
      const t = TIERS[d.tier];
      el.className = "beacon";
      el.style.setProperty("--c", t.color);
      el.style.setProperty("--size", d.tier === 5 ? "12px" : "8px");
      el.style.setProperty("--speed", d.tier === 5 ? "1.1s" : "1.7s");
      el.title = d.title;
      el.addEventListener("click", (e) => {
        e.stopPropagation();
        select(d);
      });
      return el;
    })
    .onGlobeClick(() => closeDetail());

  // Keep it smooth: cap pixel density (4K / Retina screens draw 4-9x more pixels)
  globe.renderer().setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));

  const controls = globe.controls();
  controls.autoRotate = true;
  controls.autoRotateSpeed = 0.45;
  controls.enableDamping = true;
  controls.dampingFactor = 0.15; // stops quickly after you let go, no floaty drift
  controls.zoomSpeed = 1.2;

  function setRotation(on) {
    controls.autoRotate = on;
    $("rotate").setAttribute("aria-pressed", String(on));
    $("rotate-ico").textContent = on ? "❚❚" : "▶";
    $("rotate-lbl").textContent = on ? "Pause" : "Spin";
  }
  // Grabbing the globe with the mouse / finger stops the spin so you stay in control
  controls.addEventListener("start", () => setRotation(false));
  globe.pointOfView({ lat: 25, lng: 10, altitude: window.innerWidth < 760 ? 3.6 : 2.4 });

  const resize = () => globe.width(window.innerWidth).height(window.innerHeight);
  window.addEventListener("resize", resize);
  resize();

  // ---------- rendering ----------
  function visible() {
    const q = state.query;
    return state.stories.filter(
      (s) =>
        !state.hiddenTiers.has(s.tier) &&
        (!q || `${s.title} ${s.location} ${s.description} ${s.domain} ${s.category}`.toLowerCase().includes(q))
    );
  }

  function render() {
    const list = visible();
    globe.pointsData(list);
    globe.ringsData(list.filter((s) => s.tier >= 3));
    globe.htmlElementsData(list.filter((s) => s.tier >= 4));
    renderList(list);
    renderLegend();
  }

  function renderList(list) {
    const ol = $("story-list");
    if (!list.length) {
      ol.innerHTML = '<li class="empty">No stories match.</li>';
      return;
    }
    ol.innerHTML = list
      .map(
        (s) => `<li data-id="${s.id}" class="${state.selected === s ? "active" : ""}">
          <span class="dot" style="background:${TIERS[s.tier].color};box-shadow:0 0 8px ${TIERS[s.tier].color}"></span>
          <div><div class="t">${esc(s.title)}</div>
          <div class="s">${esc(s.location || s.country)} · ${fmt(s.articles)} articles · ${esc(s.domain)}</div></div>
        </li>`
      )
      .join("");
  }

  function renderLegend() {
    const counts = {};
    state.stories.forEach((s) => (counts[s.tier] = (counts[s.tier] || 0) + 1));
    $("legend-items").innerHTML = [5, 4, 3, 2, 1]
      .map((t) => {
        const size = 6 + t * 2;
        const c = TIERS[t].color;
        return `<button class="legend-item ${state.hiddenTiers.has(t) ? "off" : ""}" data-tier="${t}">
          <span class="dot" style="width:${size}px;height:${size}px;background:${c};box-shadow:0 0 ${t * 2}px ${c}"></span>
          ${TIERS[t].name}<span class="count">${counts[t] || 0}</span></button>`;
      })
      .join("");
  }

  // ---------- detail card ----------
  function select(story) {
    state.selected = story;
    const t = TIERS[story.tier];
    $("d-title").textContent = story.title;
    $("d-tier").textContent = `${t.name.toUpperCase()} IMPACT`;
    $("d-tier").style.background = hexToRgba(t.color, 0.18);
    $("d-tier").style.color = t.color;
    $("d-category").textContent = story.category || "General";
    $("d-location").textContent = "📍 " + (story.location || story.country || "Unknown location");
    $("d-desc").textContent = story.description || "";
    $("d-articles").textContent = fmt(story.articles);
    $("d-sources").textContent = fmt(story.sources);
    $("d-rank").textContent = "#" + story.rank;
    $("d-link").href = safeUrl(story.url);
    $("d-domain").textContent = story.domain || "";
    const img = $("d-image");
    img.hidden = !story.image;
    img.onerror = () => (img.hidden = true);
    if (story.image) img.src = safeUrl(story.image);
    $("detail").hidden = false;

    setRotation(false);
    globe.pointOfView({ lat: story._lat, lng: story._lng, altitude: 1.5 }, 1200);
    globe.pointColor(globe.pointColor()); // refresh highlight
    renderList(visible());
    const li = document.querySelector(`#story-list li[data-id="${story.id}"]`);
    if (li) li.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  function closeDetail() {
    if (!state.selected) return;
    state.selected = null;
    $("detail").hidden = true;
    globe.pointColor(globe.pointColor());
    renderList(visible());
  }

  // ---------- data ----------
  async function getJSON(path) {
    const res = await fetch(path, { cache: "no-cache" });
    if (!res.ok) throw new Error(`${path}: ${res.status}`);
    return res.json();
  }

  async function loadDay(day) {
    let data;
    try {
      data = await getJSON(day ? `data/archive/${day}.json` : "data/latest.json");
    } catch (err) {
      $("updated").textContent = "Could not load news data.";
      console.error(err);
      return;
    }
    state.selected = null;
    $("detail").hidden = true;
    state.stories = spread((data.stories || []).filter((s) => TIERS[s.tier] && isFinite(s.lat) && isFinite(s.lng)));
    $("demo-banner").hidden = !data.demo;
    const when = new Date(data.generated_at);
    $("updated").textContent = `${state.stories.length} stories · updated ${when.toLocaleString([], {
      dateStyle: "medium",
      timeStyle: "short",
    })}`;
    render();
  }

  async function init() {
    try {
      const index = await getJSON("data/index.json");
      const sel = $("day");
      sel.innerHTML = (index.days || [])
        .map((d, i) => `<option value="${esc(d)}">${i === 0 ? "Today · " : ""}${esc(d)}</option>`)
        .join("");
      sel.hidden = !(index.days || []).length;
    } catch {
      $("day").hidden = true;
    }
    await loadDay(null);
  }

  // ---------- UI events ----------
  $("day").addEventListener("change", (e) => loadDay(e.target.selectedIndex === 0 ? null : e.target.value));
  $("search").addEventListener("input", (e) => {
    state.query = e.target.value.trim().toLowerCase();
    render();
  });
  $("story-list").addEventListener("click", (e) => {
    const li = e.target.closest("li[data-id]");
    if (li) select(state.stories.find((s) => String(s.id) === li.dataset.id));
  });
  $("legend-items").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-tier]");
    if (!btn) return;
    const t = Number(btn.dataset.tier);
    state.hiddenTiers.has(t) ? state.hiddenTiers.delete(t) : state.hiddenTiers.add(t);
    render();
  });
  $("close-detail").addEventListener("click", closeDetail);
  $("rotate").addEventListener("click", () => setRotation(!controls.autoRotate));
  document.addEventListener("keydown", (e) => {
    if (e.code === "Space" && !/INPUT|SELECT|TEXTAREA|BUTTON/.test(e.target.tagName)) {
      e.preventDefault();
      setRotation(!controls.autoRotate);
    }
  });
  $("toggle-list").addEventListener("click", () => $("list-panel").classList.toggle("hidden"));
  document.addEventListener("keydown", (e) => e.key === "Escape" && closeDetail());
  if (window.innerWidth < 760) $("list-panel").classList.add("hidden");

  init();
})();
