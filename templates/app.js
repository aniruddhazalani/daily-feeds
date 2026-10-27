(function () {
  const tabs = [...document.querySelectorAll(".tab")];
  const panels = [...document.querySelectorAll(".panel")];
  // Browser storage can be missing or blocked (private windows); everything still works without it.
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} },
    del(k) { try { localStorage.removeItem(k); } catch (e) {} },
    json(k) { try { return JSON.parse(store.get(k) || "null"); } catch (e) { return null; } },
  };

  function show(id, push) {
    if (!panels.some(p => p.dataset.panel === id)) id = panels[0] && panels[0].dataset.panel;
    tabs.forEach(t => t.setAttribute("aria-selected", String(t.dataset.tab === id)));
    panels.forEach(p => { p.hidden = p.dataset.panel !== id; });
    store.set("feeds.tab", id);
    if (push) history.replaceState(null, "", "#" + id);
  }

  tabs.forEach(t => t.addEventListener("click", () => { show(t.dataset.tab, true); window.scrollTo({ top: 0 }); }));

  // Hash can be a tab ("#ai") or a section anchor ("#ai-llms").
  function goToHash(hash) {
    const panel = panels.find(p => p.dataset.panel === hash || (hash && p.querySelector("#" + CSS.escape(hash))));
    if (!panel) return false;
    show(panel.dataset.panel, false);
    if (hash !== panel.dataset.panel) document.getElementById(hash)?.scrollIntoView();
    return true;
  }
  if (!goToHash(decodeURIComponent(location.hash.slice(1)))) show(store.get("feeds.tab"), false);

  // In-page links (section chips, "Politics › World" labels on Top stories) may point into another tab.
  document.addEventListener("click", e => {
    const a = e.target.closest('a[href^="#"]');
    if (!a) return;
    const hash = decodeURIComponent(a.getAttribute("href").slice(1));
    if (goToHash(hash)) { e.preventDefault(); history.replaceState(null, "", "#" + hash); }
  });

  document.querySelectorAll(".show-more").forEach(b => b.addEventListener("click", () => {
    const list = b.previousElementSibling;
    const open = list.classList.toggle("expanded");
    b.textContent = open ? "Show less" : `Show ${b.dataset.more} more`;
  }));

  document.querySelectorAll("[data-filter-group]").forEach(group => {
    group.addEventListener("click", e => {
      const btn = e.target.closest("[data-filter]");
      if (!btn) return;
      group.querySelectorAll("[data-filter]").forEach(b => b.classList.toggle("on", b === btn));
      const tag = btn.dataset.filter;
      const panel = group.closest(".panel");
      // A filtered list shows every match, so the "show more" toggles only apply to "All".
      panel.querySelectorAll(".items").forEach(list => list.classList.toggle("expanded", tag !== "all"));
      panel.querySelectorAll(".show-more").forEach(b => {
        b.hidden = tag !== "all";
        b.textContent = `Show ${b.dataset.more} more`;
      });
      panel.querySelectorAll(".item").forEach(it => {
        it.toggleAttribute("hidden-by-filter", tag !== "all" && it.dataset.tag !== tag);
      });
    });
  });

  // Relative times ("3h ago") computed when the page is viewed, not when it was built.
  const now = Date.now();
  document.querySelectorAll("time[datetime]").forEach(t => {
    const mins = Math.round((now - Date.parse(t.getAttribute("datetime"))) / 60000);
    if (isNaN(mins) || mins < 0) return;
    t.title = t.textContent;
    t.textContent = mins < 60 ? `${mins}m ago` : mins < 48 * 60 ? `${Math.round(mins / 60)}h ago` : `${Math.round(mins / 1440)}d ago`;
  });

  const archive = document.getElementById("archive");
  if (archive) archive.addEventListener("change", () => { location.href = archive.value; });

  /* ---------------- Read tracking (stored only in this browser) ---------------- */
  const today = Math.floor(now / 86400000);
  const items = [...document.querySelectorAll(".item[data-url]")];
  const linksOf = it => [...it.querySelectorAll("a.title, .related a")].map(a => a.href);

  function loadMap(key, keepDays) {
    const m = store.json(key) || {};
    for (const [u, d] of Object.entries(m)) if (today - d > keepDays) delete m[u];
    return m;
  }
  const read = loadMap("feeds.read", 30);
  const known = loadMap("feeds.known", 21);

  function updateCounts() {
    tabs.forEach(t => {
      const panel = panels.find(p => p.dataset.panel === t.dataset.tab);
      const count = t.querySelector(".count");
      if (!panel || !count || t.dataset.tab === "new-sources") return;
      const all = panel.querySelectorAll(".item[data-url]");
      const unread = [...all].filter(it => !it.classList.contains("is-read")).length;
      count.textContent = unread;
      count.title = `${unread} unread of ${all.length}`;
    });
  }

  function markItem(it) {
    it.classList.toggle("is-read", linksOf(it).some(u => read[u]));
  }

  function remember(urls) {
    urls.forEach(u => { read[u] = today; });
    store.set("feeds.read", JSON.stringify(read));
    items.forEach(markItem);
    updateCounts();
  }

  // A story counts as read once you've opened any of its articles.
  document.addEventListener("click", e => {
    const a = e.target.closest("a.title, .related a");
    if (a) remember([a.href]);
  });
  document.addEventListener("auxclick", e => {  // middle-click / open in new tab
    const a = e.target.closest("a.title, .related a");
    if (a && e.button === 1) remember([a.href]);
  });

  // "New" = not on the page the last time you looked (skipped on your very first visit).
  const firstVisit = Object.keys(known).length === 0;
  items.forEach(it => {
    markItem(it);
    if (!firstVisit && !known[it.dataset.url] && !it.classList.contains("is-read")) {
      it.classList.add("is-new");
      it.querySelector(".meta")?.insertAdjacentHTML("afterbegin", '<span class="badge b-fresh">New</span>');
    }
    known[it.dataset.url] = known[it.dataset.url] || today;
  });
  store.set("feeds.known", JSON.stringify(known));
  updateCounts();

  const hideRead = document.getElementById("hide-read");
  if (hideRead) {
    hideRead.checked = store.get("feeds.hideRead") === "1";
    document.body.classList.toggle("hide-read", hideRead.checked);
    hideRead.addEventListener("change", () => {
      document.body.classList.toggle("hide-read", hideRead.checked);
      store.set("feeds.hideRead", hideRead.checked ? "1" : "0");
    });
  }
  document.getElementById("mark-read")?.addEventListener("click", () => {
    const panel = panels.find(p => !p.hidden);
    if (panel) remember([...panel.querySelectorAll(".item[data-url]")].flatMap(linksOf));
  });

  /* ---------------- Refresh (starts the GitHub workflow; at most once an hour) ---------------- */
  const btn = document.getElementById("refresh");
  const status = document.getElementById("refresh-status");
  const body = document.body;
  if (!btn || !body.dataset.repo) return;

  const repo = body.dataset.repo;
  const workflow = body.dataset.workflow;
  const minMs = Number(body.dataset.minMinutes || 60) * 60000;
  const builtAt = Date.parse(document.querySelector('meta[name="feeds-generated"]').content);
  const dialog = document.getElementById("refresh-setup");
  const fmt = t => new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const say = msg => { status.textContent = msg; };

  function nextAllowed() {
    const requested = Number(store.get("feeds.refreshRequestedAt") || 0);
    return Math.max(builtAt, requested) + minMs;
  }

  function updateButton() {
    const next = nextAllowed();
    const waiting = Date.now() < next;
    btn.disabled = waiting;
    btn.textContent = waiting ? `Refresh at ${fmt(next)}` : "Refresh";
    btn.title = waiting ? "The feed refreshes at most once an hour" : "Fetch the latest news now (takes about 3 minutes)";
  }
  updateButton();
  setInterval(updateButton, 30000);

  // Reload once the newly built page is live (GitHub Pages can take a minute after the build).
  function waitForNewBuild() {
    const started = Date.now();
    say("Refreshing… this takes about 3 minutes. The page reloads by itself when it's ready.");
    const timer = setInterval(async () => {
      try {
        const html = await (await fetch(`${location.pathname}?t=${Date.now()}`, { cache: "no-store" })).text();
        const m = html.match(/name="feeds-generated" content="([^"]+)"/);
        if (m && Date.parse(m[1]) > builtAt) { clearInterval(timer); say("Updated — reloading…"); location.reload(); return; }
      } catch (e) { /* offline for a moment; keep waiting */ }
      if (Date.now() - started > 12 * 60000) {
        clearInterval(timer);
        say("Still no new version after 12 minutes. Check the run on GitHub Actions.");
      }
    }, 20000);
  }
  if (Date.now() - Number(store.get("feeds.refreshRequestedAt") || 0) < 12 * 60000) waitForNewBuild();

  async function trigger(token) {
    btn.disabled = true;
    say("Starting refresh…");
    let res;
    try {
      res = await fetch(`https://api.github.com/repos/${repo}/actions/workflows/${workflow}/dispatches`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28" },
        body: JSON.stringify({ ref: "main" }),
      });
    } catch (e) {
      say("Couldn't reach GitHub. Check your connection and try again.");
      updateButton();
      return;
    }
    if (res.status === 204) {
      store.set("feeds.refreshRequestedAt", String(Date.now()));
      updateButton();
      waitForNewBuild();
    } else if (res.status === 401 || res.status === 403 || res.status === 404) {
      store.del("feeds.ghToken");
      updateButton();
      say("");
      openSetup(res.status === 401
        ? "GitHub rejected that token (expired or mistyped). Create a new one and paste it here."
        : "That token can't run the workflow. Give it Actions: Read and write on this repository only.");
    } else {
      say(`GitHub returned an error (${res.status}). Try again in a minute.`);
      updateButton();
    }
  }

  function openSetup(error) {
    const err = document.getElementById("token-error");
    err.hidden = !error;
    err.textContent = error || "";
    document.getElementById("token-input").value = "";
    dialog.showModal();
  }

  dialog.addEventListener("close", () => {
    const token = document.getElementById("token-input").value.trim();
    if (dialog.returnValue !== "save" || !token) return;
    store.set("feeds.ghToken", token);
    trigger(token);
  });

  btn.addEventListener("click", () => {
    if (Date.now() < nextAllowed()) { updateButton(); return; }
    const token = store.get("feeds.ghToken");
    if (token) trigger(token); else openSetup();
  });
})();
