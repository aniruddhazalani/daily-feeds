(function () {
  const tabs = [...document.querySelectorAll(".tab")];
  const panels = [...document.querySelectorAll(".panel")];
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} },
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
  const hash = decodeURIComponent(location.hash.slice(1));
  const fromHash = panels.find(p => p.dataset.panel === hash || (hash && p.querySelector("#" + CSS.escape(hash))));
  show(fromHash ? fromHash.dataset.panel : store.get("feeds.tab"), false);
  if (fromHash && hash !== fromHash.dataset.panel) document.getElementById(hash)?.scrollIntoView();

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
})();
