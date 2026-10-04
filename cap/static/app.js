"use strict";

// The server puts the token in the page only for the window cap.py opened (single-use launch link).
// Keep it in this tab's sessionStorage so reloads work, and drop the launch code from the address bar.
const TOKEN = (() => {
  const fromPage = document.querySelector('meta[name="cap-token"]').content;
  try {
    if (fromPage) sessionStorage.setItem("cap-token", fromPage);
    return fromPage || sessionStorage.getItem("cap-token") || "";
  } catch { return fromPage; }
})();
history.replaceState(null, "", "/" + location.hash);
const LOCKED = !TOKEN;  // not the window cap.py opened: show it, and run nothing
const NAME = document.querySelector('meta[name="cap-name"]').content;
const DEMO = document.querySelector('meta[name="cap-mode"]').content === "demo";
const $ = (sel, root = document) => root.querySelector(sel);
const LABELS = { balance: "FIN", subscriptions: "SUB", email: "MAIL", research: "RSCH", weather: "WX" };

/* ---------- tiny helpers ---------- */

// Build DOM nodes. Strings become text nodes, so result data can never inject HTML.
function el(tag, attrs = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else node.setAttribute(k, v === true ? "" : v);
  }
  node.append(...nodes(kids));
  return node;
}
// Flatten nested arrays and drop null/false, so renderers can write `cond ? [a, b] : null`.
const nodes = (kids) => kids.flat(Infinity).filter((k) => k != null && k !== false).map((k) => (k instanceof Node ? k : String(k)));
const fill = (target, ...kids) => target.replaceChildren(...nodes(kids));
const money = (n) => (n < 0 ? "-$" : "$") + Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const clockTime = (d = new Date()) => d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
const shortDate = (iso) => new Date(iso + "T12:00:00").toLocaleDateString([], { month: "short", day: "numeric" });
const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : null);
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode: fine */ } },
};

function bar(fraction, tone) {
  const fill = el("i");
  requestAnimationFrame(() => requestAnimationFrame(() => { fill.style.width = `${Math.max(0, Math.min(1, fraction)) * 100}%`; }));
  return el("div", { class: `bar ${tone || ""}` }, fill);
}

async function api(path, options = {}) {
  const res = await fetch(path, { ...options, headers: { "X-CAP-Token": TOKEN, "Content-Type": "application/json" } });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`);
  return body;
}

/* ---------- voice ---------- */

const voice = {
  on: store.get("cap-voice") !== "off",
  pick() {
    // On-device voices only: online voices (e.g. Chrome's "Google ..." ones) send the text to a server.
    const voices = speechSynthesis.getVoices().filter((v) => v.localService);
    const prefer = ["Daniel", "Arthur", "Oliver"];
    return prefer.map((n) => voices.find((v) => v.name.startsWith(n))).find(Boolean)
      || voices.find((v) => v.lang === "en-GB") || voices.find((v) => v.lang.startsWith("en"));
  },
  say(text, { queue = false } = {}) {  // queue: wait for anything already being said
    if (!this.on || !("speechSynthesis" in window)) return;
    const u = new SpeechSynthesisUtterance(text);
    const v = this.pick();
    if (v) u.voice = v;
    u.rate = 1.02; u.pitch = 0.95;
    if (!queue) speechSynthesis.cancel();
    speechSynthesis.speak(u);
  },
};
if ("speechSynthesis" in window) speechSynthesis.getVoices(); // starts the async voice list load

function setVoiceButton() {
  const b = $("#voice");
  b.setAttribute("aria-pressed", String(voice.on));
  b.title = voice.on ? "Voice on" : "Voice off";
}
$("#voice").addEventListener("click", () => {
  voice.on = !voice.on;
  store.set("cap-voice", voice.on ? "on" : "off");
  setVoiceButton();
  if (voice.on) voice.say("Voice online.");
  else speechSynthesis.cancel();
});
setVoiceButton();

/* ---------- greeting, boot ---------- */

function partOfDay(h = new Date().getHours()) {
  return h < 5 ? "Working late" : h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}
function greeting() {
  const p = partOfDay();
  return p === "Working late" ? `Working late, ${NAME}?` : `${p}, ${NAME}.`;
}

$("#greeting").textContent = greeting();
$("#subgreeting").textContent = "All systems online. Four modules standing by.";
if (DEMO) $("#demo-badge").hidden = false;

const BOOT_LINES = [
  "Initializing core systems",
  "Secure channel: local only (127.0.0.1)",
  "Linking modules: finance · subscriptions · mail · weather · research",
  "Voice interface " + (voice.on ? "ready" : "muted"),
];

function finishBoot() {
  const boot = $("#boot");
  if (boot.classList.contains("done")) return;
  boot.classList.add("done");
  document.body.classList.add("ready");
  if (LOCKED) { logLine("SYS", "Locked: this window isn't authorized. Start CAP with uv run cap.py.", "err"); return; }
  logLine("SYS", greeting() + " All systems online.", "ok");
  if (DEMO && location.hash === "#autorun") setTimeout(autorun, 300);
  else loadSavedWeather();
}

async function boot() {
  const list = $("#boot-lines");
  const fast = matchMedia("(prefers-reduced-motion: reduce)").matches || location.hash === "#autorun";
  $("#boot").addEventListener("click", finishBoot);
  document.addEventListener("keydown", finishBoot, { once: true });
  const wait = (ms) => new Promise((r) => setTimeout(r, fast ? 0 : ms));
  for (const text of BOOT_LINES) {
    const li = el("li", {}, text);
    list.append(li);
    await wait(380);
    li.classList.add("ok");
  }
  await wait(250);
  $("#boot-greeting").textContent = greeting();
  voice.say(`${greeting()} All systems are online. How can I help?`);
  await wait(2100);
  finishBoot();
}

/* ---------- activity log ---------- */

function logLine(tag, msg, kind = "") {
  const log = $("#log");
  const tagName = Object.keys(LABELS).find((k) => LABELS[k] === tag) || "";
  log.append(el("li", { class: kind }, el("time", {}, clockTime()), el("span", { class: `tag ${tagName}` }, tag), el("span", { class: "msg" }, msg)));
  while (log.children.length > 400) log.firstChild.remove();
  log.scrollTop = log.scrollHeight;
}

/* ---------- running modules ---------- */

const running = new Set();
function updateSystemStatus() {
  if (LOCKED) return;
  const busy = running.size > 0;
  document.body.classList.toggle("busy", busy);
  $("#sys-dot").classList.toggle("busy", busy);
  $("#sys-text").textContent = busy ? `Processing (${running.size})` : "Online";
}

function setState(panel, text, tone) {
  const s = $("[data-state]", panel);
  s.textContent = text;
  s.className = `state ${tone || ""}`;
}

// Start a script on the server and stream its progress lines until it finishes.
async function runJob(task, input, onLine) {
  const { id } = await api("/api/run", { method: "POST", body: JSON.stringify({ task, input }) });
  for (let since = 0; ;) {
    await new Promise((r) => setTimeout(r, 450));
    const job = await api(`/api/jobs/${id}?since=${since}`);
    since = job.next;
    job.log.forEach((line) => onLine(line.trim()));
    if (job.status === "running") continue;
    if (job.status === "error") throw new Error(job.error || "Something went wrong.");
    return job;
  }
}

async function runModule(task, input = {}) {
  const panel = $(`.panel[data-task="${task}"]`);
  if (LOCKED || running.has(task)) return;
  const buttons = panel.querySelectorAll("[data-run]");
  const ticker = $("[data-ticker]", panel);
  running.add(task); updateSystemStatus();
  buttons.forEach((b) => (b.disabled = true));
  panel.classList.add("running");
  setState(panel, "Processing", "run");
  ticker.textContent = "Starting…";
  logLine(LABELS[task], `${STARTED[task](input)}`);

  try {
    const job = await runJob(task, input, (line) => { logLine(LABELS[task], line); ticker.textContent = line; });
    ticker.textContent = "";
    $("[data-meta]", panel).textContent = `Updated ${clockTime()} · ${job.elapsed}s`;
    const { tone, summary, speech } = RENDER[task]($("[data-body]", panel), job.result, input);
    setState(panel, { bad: "Attention", warn: "Warning" }[tone] || "Complete", tone);
    logLine(LABELS[task], summary, { bad: "err", warn: "warn" }[tone] || "ok");
    voice.say(speech);
  } catch (err) {
    const body = $("[data-body]", panel);
    fill(body, el("p", { class: "error" }, err.message));
    setState(panel, "Fault", "bad");
    ticker.textContent = "";
    logLine(LABELS[task], err.message.split("\n").pop(), "err");
    voice.say(`I ran into a problem with ${SPOKEN[task]}.`);
  } finally {
    running.delete(task); updateSystemStatus();
    buttons.forEach((b) => (b.disabled = false));
    panel.classList.remove("running");
  }
}

const SPOKEN = { balance: "the balance check", subscriptions: "the subscription scan", email: "email triage", research: "the research request" };
const STARTED = {
  balance: () => "Running balance check across linked banks",
  subscriptions: () => "Scanning transaction history for recurring charges",
  email: (i) => (i.dry_run ? "Classifying inbox (preview only, no labels)" : "Classifying inbox and applying labels"),
  research: (i) => `Researching: ${i.prompt}`,
};

/* ---------- renderers: each returns {tone, summary, speech} ---------- */

const RENDER = {
  balance(body, r) {
    const banks = Object.entries(r.per_bank);
    const named = (status) => banks.filter(([, t]) => t.status === status).map(([n]) => n);
    const TONE = { pass: "good", warn: "warn", fail: "bad" };
    const HEADLINE = { pass: "All clear", warn: "Running low", fail: "Attention" };
    fill(body,
      el("div", { class: "headline" },
        el("span", { class: `big ${TONE[r.status]}` }, HEADLINE[r.status]),
        el("span", { class: "sub" }, `${banks.length} bank${banks.length === 1 ? "" : "s"} · warn under ${money(r.warn_below)} left`)),
      el("ul", { class: "rows" }, banks.map(([name, t]) => el("li", { class: "row" },
        el("span", { class: "row-name" }, name, " ", el("span", { class: `chip ${TONE[t.status]}` }, t.status)),
        el("span", { class: "row-val" }, t.left < 0 ? `${money(-t.left)} short` : `${money(t.left)} left`),
        bar(t.checking > 0 ? t.left / t.checking : 0, TONE[t.status]),  // share of checking left after cards
        el("span", { class: "row-sub" }, `Checking ${money(t.checking)} − cards owed ${money(t.credit)}`)))),
    );
    const plural = (names, one, many) => (names.length === 1 ? one : `${names.length} ${many}`);
    if (r.status === "fail") {
      const names = named("fail");
      return { tone: "bad", summary: `Balance check: cards owed exceed checking at ${names.join(", ")}.`,
               speech: `Balance check complete. ${plural(names, "One bank needs", "banks need")} your attention.` };
    }
    if (r.status === "warn") {
      const names = named("warn");
      return { tone: "warn", summary: `Balance check: under ${money(r.warn_below)} left at ${names.join(", ")}.`,
               speech: `Balance check complete. ${plural(names, "One bank is", "banks are")} running low.` };
    }
    return { tone: "good", summary: "Balance check: all banks pass.", speech: "Balance check complete. All accounts are in good shape." };
  },

  subscriptions(body, r) {
    const active = r.subscriptions.filter((s) => s.active);
    const stopped = r.subscriptions.filter((s) => !s.active);
    const monthly = active.reduce((sum, s) => sum + s.per_month, 0);
    const row = (s) => el("li", { class: "row" },
      el("span", { class: "row-name" }, s.merchant),
      el("span", { class: "row-val" }, money(s.amount)),
      el("span", { class: "row-sub" }, `${s.frequency} · ${s.where} · ${s.active ? `next ~${shortDate(s.next)}` : `expected ~${shortDate(s.next)}`}`));
    fill(body, 
      ...r.warnings.map((w) => el("p", { class: "notice" }, w)),
      el("div", { class: "headline" },
        el("span", { class: "big cyan" }, money(monthly)),
        el("span", { class: "sub" }, `per month · ${active.length} active · ${r.history_days} days of history`)),
      active.length ? el("ul", { class: "rows" }, active.map(row)) : el("p", { class: "hint" }, "No subscriptions found."),
      stopped.length ? [el("div", { class: "section-label" }, "Missed last charge (maybe cancelled)"), el("ul", { class: "rows dimmed" }, stopped.map(row))] : null,
    );
    return { tone: "good", summary: `Subscriptions: ${active.length} active, about ${money(monthly)}/month.`,
             speech: `I found ${active.length} active subscription${active.length === 1 ? "" : "s"}.` };
  },

  email(body, r) {
    const counts = Object.entries(r.labelled);
    const total = counts.reduce((s, [, n]) => s + n, 0);
    const max = Math.max(1, ...counts.map(([, n]) => n));
    if (!r.new) {
      fill(body, 
        el("div", { class: "headline" }, el("span", { class: "big good" }, "Inbox sorted")),
        el("p", { class: "hint" }, `No unlabelled Primary emails in the last ${r.days} days (${r.found} checked).`));
      return { tone: "good", summary: "Mail: nothing new to label.", speech: "Your inbox is already sorted." };
    }
    fill(body, 
      el("div", { class: "headline" },
        el("span", { class: "big cyan" }, String(total)),
        el("span", { class: "sub" }, `${r.dry_run ? "would be labelled" : "labelled"} of ${r.new} new · last ${r.days} days`)),
      r.dry_run ? el("p", { class: "notice" }, "Preview only: no labels were changed in Gmail.") : null,
      el("ul", { class: "rows" }, counts.map(([label, n]) => el("li", { class: "row" },
        el("span", { class: "row-name" }, `Classifier/${label[0].toUpperCase()}${label.slice(1)}`),
        el("span", { class: "row-val" }, String(n)),
        bar(n / max)))),
      r.unsure ? el("p", { class: "hint section-label" }, `${r.unsure} left alone (model under ${Math.round(r.threshold * 100)}% sure)`) : null,
    );
    return { tone: "good", summary: `Mail: ${r.dry_run ? "would label" : "labelled"} ${total} of ${r.new} new emails.`,
             speech: `Email triage complete. ${total} message${total === 1 ? "" : "s"} ${r.dry_run ? "would be" : ""} labelled.` };
  },

  research(body, r) {
    if (!r.papers.length) {
      fill(body, el("p", { class: "hint" }, "No papers found. Try describing the problem differently."));
      return { tone: "good", summary: "Research: no papers found.", speech: "I couldn't find any matching papers." };
    }
    const queries = Object.values(r.queries).flat();
    fill(body, 
      el("div", { class: "queries" },
        el("span", { class: "chip muted" }, r.used_claude ? "Queries by Claude" : "Keyword search"),
        queries.map((q) => el("span", { class: "chip cyan" }, q))),
      el("p", { class: "sub" }, `Top ${r.papers.length} of ${r.candidates} candidates · full ranking saved to research/${r.saved_to}`),
      el("ol", { class: "papers" }, r.papers.map((p, i) => {
        const url = safeUrl(p.url);
        return el("li", { class: "paper" },
          el("span", { class: "paper-rank" }, String(i + 1).padStart(2, "0")),
          url ? el("a", { class: "paper-title", href: url, target: "_blank", rel: "noopener noreferrer" }, p.title)
              : el("span", { class: "paper-title" }, p.title),
          el("div", { class: "paper-meta" },
            [p.year, p.venue, p.first_author, `${p.citations.toLocaleString()} citations`].filter(Boolean).map((m) => el("span", {}, m)),
            el("span", { class: "chip muted" }, p.kind.replace("_", " ")),
            el("span", { class: "paper-match" }, "match", bar((p.similarity - 0.6) / 0.35), p.similarity.toFixed(3))),
          p.abstract ? el("details", {}, el("summary", {}, "Abstract"), el("p", {}, p.abstract)) : null);
      })),
    );
    return { tone: "good", summary: `Research: ${r.papers.length} papers ranked from ${r.candidates}.`,
             speech: `Research complete. Here are the ${r.papers.length} most relevant papers I found.` };
  },
};

/* ---------- weather icons (24x24 line drawings) ---------- */

const SVG_NS = "http://www.w3.org/2000/svg";
const CLOUD = "M7 19h10a4 4 0 0 0 .6-7.96A6 6 0 0 0 6.2 11.2 3.9 3.9 0 0 0 7 19z";
const CLOUD_HIGH = "M7 15h10a3.6 3.6 0 0 0 .5-7.17A5.4 5.4 0 0 0 6.6 8.3 3.4 3.4 0 0 0 7 15z";
const WX_PARTS = {
  sun: "M12 8a4 4 0 1 0 0 8a4 4 0 1 0 0-8zM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4",
  moon: "M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z",
  smallSun: "M7 4.5a2.5 2.5 0 1 0 0 5a2.5 2.5 0 1 0 0-5zM7 1v1.2M1 7h1.2M2.8 2.8l.85.85M11.2 2.8l-.85.85M2.8 11.2l.85-.85",
  smallMoon: "M9.5 8.5A3.5 3.5 0 1 1 5.5 3a2.8 2.8 0 0 0 4 5.5z",
  cloudLow: "M10 20h8a3.5 3.5 0 0 0 .4-6.97A5 5 0 0 0 9.3 13.3 3.3 3.3 0 0 0 10 20z",
  drops: "M8 18l-1 3M12 18l-1 3M16 18l-1 3",
  flakes: "M8 18v3M6.5 19.5h3M15 18v3M13.5 19.5h3",
  bolt: "M12.5 15.5L10.5 19h3l-2 3.5",
  fog: "M4 8h16M2.5 12h19M4 16h16M7 20h10",
};

function wxIcon(kind, isDay = true) {
  const parts = {
    clear: [isDay ? WX_PARTS.sun : WX_PARTS.moon],
    partly: [isDay ? WX_PARTS.smallSun : WX_PARTS.smallMoon, WX_PARTS.cloudLow],
    cloudy: [CLOUD],
    fog: [WX_PARTS.fog],
    rain: [CLOUD_HIGH, WX_PARTS.drops],
    snow: [CLOUD_HIGH, WX_PARTS.flakes],
    storm: [CLOUD_HIGH, WX_PARTS.bolt],
  }[kind] || [CLOUD];
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", "wx-icon");
  svg.setAttribute("aria-hidden", "true");
  for (const d of parts) {
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
}

/* ---------- wiring ---------- */

$('.panel[data-task="balance"] [data-run]').addEventListener("click", () => runModule("balance"));
$('.panel[data-task="subscriptions"] [data-run]').addEventListener("click", () => runModule("subscriptions"));
$('.panel[data-task="email"] [data-run]').addEventListener("click", () => runModule("email", { dry_run: $("#email-preview").checked }));
$("#research-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const prompt = $("#research-input").value.trim();
  if (prompt.length < 3) { $("#research-input").focus(); return; }
  runModule("research", { prompt });
});

function autorun() { // demo only: fill every panel so the whole console can be previewed at once
  runModule("balance"); runModule("subscriptions"); runModule("email", { dry_run: true });
  $("#research-input").value = "predict which tenants will pay rent late";
  runModule("research", { prompt: $("#research-input").value });
  updateWeather("Example City");
}

/* ---------- weather ---------- */

// Fetch the weather for the header readout (no panel). Logged in Activity like everything else.
async function updateWeather(place, { speak = true, queue = false } = {}) {
  if (LOCKED || running.has("weather")) return;
  running.add("weather"); updateSystemStatus();
  logLine("WX", `Checking the weather for ${place}`);
  try {
    const { result: r } = await runJob("weather", { place }, (line) => logLine("WX", line));
    const { current: c, today: t, units: u } = r;
    const where = [r.place.name, r.place.region].filter(Boolean).join(", ");
    const clock = (iso) => new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    store.set("cap-weather-place", place);  // remembered for next start-up (this browser profile only)
    fill($("#wx-icon"), wxIcon(c.icon, c.is_day));
    $("#wx-temp").textContent = `${c.temp}${u.temp}`;
    $("#wx-summary").textContent = c.summary;
    $("#wx-detail").textContent = t ? `${r.place.name} · H ${t.high}° L ${t.low}°` : r.place.name;
    $("#wx-button").title = [
      `${where}: ${c.summary}, feels like ${c.feels_like}°`,
      t && `Rain today ${t.rain ?? 0}% · Humidity ${c.humidity}% · Wind ${c.wind} ${u.wind}`,
      t && `Sunrise ${clock(t.sunrise)} · Sunset ${clock(t.sunset)}`,
      "Click to change city",
    ].filter(Boolean).join("\n");
    logLine("WX", `${c.temp}${u.temp} and ${c.summary.toLowerCase()} in ${where}.`, "ok");
    if (speak) voice.say(`It's ${c.temp} degrees and ${c.summary.toLowerCase()} in ${r.place.name}.`, { queue });
  } catch (err) {
    $("#wx-detail").textContent = "Weather unavailable";
    logLine("WX", err.message.split("\n").pop(), "err");
    if (speak) voice.say("I couldn't get the weather.", { queue });
  } finally {
    running.delete("weather"); updateSystemStatus();
  }
}

function loadSavedWeather() {  // at start-up: the city from last time, spoken after the greeting
  const place = store.get("cap-weather-place");
  if (place) updateWeather(place, { queue: true });
}

// Click the header readout to set or change the city.
const wxForm = $("#weather-form");
function setWxOpen(open) {
  wxForm.hidden = !open;
  $("#wx-button").setAttribute("aria-expanded", String(open));
  if (open) {
    $("#weather-input").value = store.get("cap-weather-place") || "";
    $("#weather-input").focus();
  }
}
$("#wx-button").addEventListener("click", () => setWxOpen(wxForm.hidden));
wxForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const place = $("#weather-input").value.trim();
  if (place.length < 2) { $("#weather-input").focus(); return; }
  setWxOpen(false);
  updateWeather(place);
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !wxForm.hidden) setWxOpen(false); });
document.addEventListener("click", (e) => { if (!wxForm.hidden && !e.target.closest(".wx-wrap")) setWxOpen(false); });

// Quietly refresh every 30 minutes once a city is saved.
setInterval(() => {
  const place = store.get("cap-weather-place");
  if (place) updateWeather(place, { speak: false });
}, 30 * 60_000);

// Let CAP know the window is still open; it shuts down a few minutes after these stop.
if (!LOCKED) {
  const ping = () => api("/api/ping").catch(() => { $("#sys-text").textContent = "Offline"; $("#sys-dot").classList.add("busy"); });
  ping();
  setInterval(ping, 20_000);
} else {
  // Not the window cap.py opened (or CAP restarted): nothing here can run.
  document.querySelectorAll("[data-run]").forEach((b) => (b.disabled = true));
  $("#sys-text").textContent = "Locked";
  $("#sys-dot").classList.add("busy");
  $("#subgreeting").textContent = "This window isn't authorized. Start CAP with: uv run cap.py";
}

boot();
