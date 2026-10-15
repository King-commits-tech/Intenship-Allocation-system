/* Shared front-end behaviour: confirmations, loading states, notifications polling, skill chips. */
(function () {
  "use strict";
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";

  // ---- API helper (sends CSRF header) ----
  window.api = async function (url, options = {}) {
    const opts = Object.assign({ headers: {} }, options);
    opts.headers = Object.assign({ "X-CSRFToken": csrf, "Accept": "application/json" }, opts.headers);
    if (opts.body && typeof opts.body !== "string") {
      opts.body = JSON.stringify(opts.body);
      opts.headers["Content-Type"] = "application/json";
    }
    const res = await fetch(url, opts);
    let data = null;
    try { data = await res.json(); } catch (e) { /* non-JSON */ }
    if (!res.ok) throw new Error((data && data.error) || `Request failed (${res.status})`);
    return data;
  };

  // ---- Sidebar toggle (mobile) ----
  document.querySelectorAll("[data-toggle-sidebar]").forEach((btn) =>
    btn.addEventListener("click", () => document.querySelector(".sidebar")?.classList.toggle("open")));
  document.addEventListener("click", (e) => {
    const sb = document.querySelector(".sidebar.open");
    if (sb && !sb.contains(e.target) && !e.target.closest("[data-toggle-sidebar]")) sb.classList.remove("open");
  });

  // ---- Confirmation dialogs (Bootstrap modal) for forms with data-confirm ----
  const modalEl = document.getElementById("confirmModal");
  let pendingForm = null;
  if (modalEl) {
    const modal = new bootstrap.Modal(modalEl);
    document.addEventListener("submit", (e) => {
      const form = e.target;
      if (form.dataset.confirm && !form.dataset.confirmed) {
        e.preventDefault();
        pendingForm = form;
        modalEl.querySelector(".modal-body").textContent = form.dataset.confirm;
        modal.show();
      }
    }, true);
    modalEl.querySelector("[data-confirm-ok]").addEventListener("click", () => {
      if (pendingForm) {
        pendingForm.dataset.confirmed = "1";
        modal.hide();
        if (pendingForm.requestSubmit) pendingForm.requestSubmit(); else pendingForm.submit();
      }
    });
  }

  // ---- Client-side validation + loading state on submit ----
  document.addEventListener("submit", (e) => {
    const form = e.target;
    if (form.dataset.confirm && !form.dataset.confirmed) return;
    if (form.classList.contains("needs-validation") && !form.checkValidity()) {
      e.preventDefault();
      e.stopPropagation();
      form.classList.add("was-validated");
      return;
    }
    const btn = form.querySelector("button[type=submit]:not([data-no-loading])");
    if (btn && !btn.disabled) {
      btn.dataset.originalHtml = btn.innerHTML;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>' +
        (btn.dataset.loadingText || "Working…");
      setTimeout(() => { btn.disabled = true; }, 0);
    }
    if (form.dataset.overlay) document.querySelector(".loading-overlay")?.classList.add("show");
  });
  window.addEventListener("pageshow", () => {
    document.querySelectorAll("button[data-original-html]").forEach((b) => {
      b.innerHTML = b.dataset.originalHtml; b.disabled = false;
    });
    document.querySelector(".loading-overlay")?.classList.remove("show");
  });

  // ---- Auto-submit filters ----
  document.querySelectorAll("[data-autosubmit]").forEach((el) =>
    el.addEventListener("change", () => el.form.requestSubmit ? el.form.requestSubmit() : el.form.submit()));

  // ---- Notification badge polling (every 60 s; not real-time push) ----
  const badge = document.getElementById("notifCount");
  if (badge) {
    const refresh = async () => {
      try {
        const data = await api("/api/notifications?unread=1");
        badge.textContent = data.unread;
        badge.classList.toggle("d-none", data.unread === 0);
      } catch (e) { /* ignore transient errors */ }
    };
    setInterval(refresh, 60000);
  }

  // ---- Skill chips editor: <div data-skill-editor data-target="#skills"> ----
  document.querySelectorAll("[data-skill-editor]").forEach((wrap) => {
    const input = document.querySelector(wrap.dataset.target);
    const box = wrap.querySelector(".chips");
    const add = wrap.querySelector("input.add-skill");
    const parse = () => input.value.split(",").map((s) => s.trim()).filter(Boolean);
    const render = () => {
      box.innerHTML = "";
      const items = parse();
      if (!items.length) box.innerHTML = '<span class="text-muted small">No skills yet.</span>';
      items.forEach((s, idx) => {
        const chip = document.createElement("span");
        chip.className = "skill-chip";
        chip.textContent = s + " ";
        const x = document.createElement("button");
        x.type = "button"; x.innerHTML = "&times;"; x.setAttribute("aria-label", "Remove " + s);
        x.addEventListener("click", () => { const arr = parse(); arr.splice(idx, 1); input.value = arr.join(", "); render(); });
        chip.appendChild(x);
        box.appendChild(chip);
      });
    };
    const addValue = () => {
      const v = add.value.replace(/,/g, " ").trim();
      if (!v) return;
      const arr = parse();
      if (!arr.some((s) => s.toLowerCase() === v.toLowerCase())) arr.push(v);
      input.value = arr.join(", "); add.value = ""; render();
    };
    add.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); addValue(); } });
    wrap.querySelector(".add-skill-btn")?.addEventListener("click", addValue);
    wrap.querySelectorAll("[data-add-skill]").forEach((b) => b.addEventListener("click", () => {
      add.value = b.dataset.addSkill; addValue(); b.remove();
    }));
    input.addEventListener("input", render);
    render();
  });

  // ---- Tooltips ----
  document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((el) => new bootstrap.Tooltip(el));
})();
