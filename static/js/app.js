// Global live search (name / member ID / mobile)
(function () {
  const input = document.getElementById("globalSearch");
  const box = document.getElementById("searchResults");
  if (!input) return;
  let timer, idx = -1;
  const esc = (s) => String(s || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function render(items, q) {
    if (!items.length) {
      box.innerHTML = `<div class="p-3 text-muted-2" style="font-size:13px">No members match “${esc(q)}”.</div>`;
    } else {
      box.innerHTML = items.map((m) => `
        <a href="${m.url}">
          <span class="avatar">${esc(m.name.split(/[\s.]+/).filter(Boolean).slice(0, 2).map((p) => p[0]).join(""))}</span>
          <span class="flex-grow-1">
            <span class="fw-semibold d-block">${esc(m.name)}</span>
            <span class="meta">#${esc(m.member_id)} · ${esc(m.mobile || "No mobile")} · ${esc(m.place || "-")}</span>
          </span>
          <span class="pill ${m.status === "Paid" ? "pill-paid" : "pill-unpaid"}">${esc(m.status)}</span>
        </a>`).join("") +
        `<a href="${window.MEMBERS_URL}?q=${encodeURIComponent(q)}" class="justify-content-center text-primary" style="font-size:13px">See all results <i class="bi bi-arrow-right"></i></a>`;
    }
    box.style.display = "block";
    idx = -1;
  }

  input.addEventListener("input", () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (q.length < 2) { box.style.display = "none"; return; }
    timer = setTimeout(() => {
      fetch(`${window.SEARCH_URL}?q=${encodeURIComponent(q)}`)
        .then((r) => r.json()).then((d) => render(d, q)).catch(() => {});
    }, 180);
  });
  input.addEventListener("keydown", (e) => {
    const links = [...box.querySelectorAll("a")];
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      idx = (idx + (e.key === "ArrowDown" ? 1 : -1) + links.length) % links.length;
      links.forEach((l, i) => l.classList.toggle("focus", i === idx));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (idx >= 0 && links[idx]) location.href = links[idx].href;
      else location.href = `${window.MEMBERS_URL}?q=${encodeURIComponent(input.value.trim())}`;
    } else if (e.key === "Escape") { box.style.display = "none"; input.blur(); }
  });
  document.addEventListener("click", (e) => { if (!e.target.closest(".global-search")) box.style.display = "none"; });
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) {
      e.preventDefault(); input.focus();
    }
  });
})();

// Confirm dialogs for forms marked data-confirm
document.addEventListener("submit", (e) => {
  const msg = e.target.getAttribute("data-confirm");
  if (msg && !confirm(msg)) e.preventDefault();
});
