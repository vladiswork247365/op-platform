"use strict";
const Autopilot = (() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const api = async (path, opts) => {
    const r = await fetch(path, opts);
    if (!r.ok && r.status !== 503) throw new Error(path + " -> " + r.status);
    return r.json();
  };
  const post = (path, body) =>
    api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
  const fmt = (iso) => (iso ? new Date(iso).toLocaleString("ru-RU") : "—");
  const esc = (s) =>
    (s == null ? "" : String(s)).replace(/[&<>"]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])
    );

  async function refreshModeBadge() {
    try {
      const s = await api("/api/summary");
      const badge = $("#mode-badge");
      if (badge) {
        badge.textContent = s.run_mode === "production" ? "PRODUCTION" : "DRY RUN";
        badge.className = "mode " + (s.run_mode === "production" ? "prod" : "dry");
      }
      return s;
    } catch (e) {
      return null;
    }
  }

  const decClass = (d) =>
    d === "MATCH" ? "b-ok" : d === "REVIEW" ? "b-warn" : d === "REJECT" ? "b-dim" : "";

  function vacRow(v) {
    return `<tr onclick="location.href='/vacancy/${v.id}'">
      <td>${fmt(v.discovered_at)}</td>
      <td>${esc(v.company)}</td>
      <td>${esc(v.title)}</td>
      <td>${v.score ?? "—"}</td>
      <td><span class="badge ${decClass(v.decision)}">${esc(v.decision || "—")}</span></td>
      <td>${v.applied ? "✓" : ""}</td>
      <td>${v.whatsapp ? "✓" : ""}</td>
      <td>${esc(v.status)}</td>
    </tr>`;
  }

  return {
    async initDashboard() {
      const paint = async () => {
        const s = await refreshModeBadge();
        if (!s) return;
        const st = $("#sys-status");
        st.innerHTML = "Система: <b>" + s.system_status + "</b>";
        st.className = "status-pill s-" + s.system_status;
        $("#last-check").textContent = fmt(s.last_check);
        $("#next-check").textContent = fmt(s.next_check);
        $("#queue").textContent = s.queue_depth;
        $("#errors24").textContent = s.errors_24h;
        document.querySelectorAll("#today-cards .num").forEach((el) => {
          el.textContent = s.today[el.dataset.k] ?? 0;
        });
      };
      await paint();
      $("#run-now").onclick = async () => {
        await post("/api/control/run-now");
        $("#run-now").textContent = "Запущено…";
        setTimeout(() => {
          $("#run-now").textContent = "Запустить цикл сейчас";
          paint();
        }, 2500);
      };
      $("#toggle-mode").onclick = async () => {
        const s = await api("/api/summary");
        const next = s.run_mode === "production" ? "dry_run" : "production";
        if (next === "production" && !confirm("Включить PRODUCTION? Система начнёт реально отправлять отклики.")) return;
        await post("/api/control/mode", { mode: next });
        paint();
      };
      setInterval(paint, 15000);
    },

    async initVacancies() {
      refreshModeBadge();
      let filter = "week";
      const load = async () => {
        const d = await api("/api/vacancies?filter=" + filter + "&limit=200");
        $("#vac-body").innerHTML =
          d.items.map(vacRow).join("") ||
          '<tr><td colspan="8">Нет вакансий</td></tr>';
      };
      document.querySelectorAll("#filters button").forEach((b) => {
        b.onclick = () => {
          document.querySelectorAll("#filters button").forEach((x) => x.classList.remove("on"));
          b.classList.add("on");
          filter = b.dataset.f;
          load();
        };
      });
      load();
    },

    async initDetail(id) {
      refreshModeBadge();
      const d = await api("/api/vacancies/" + id);
      const v = d.vacancy;
      const a = d.analysis;
      const bars = a
        ? [
            ["Должность", a.title_match],
            ["Навыки", a.skills_match],
            ["Опыт", a.experience_match],
            ["Зарплата", a.salary_match],
            ["Формат", a.format_match],
          ]
            .map(
              ([k, val]) =>
                `<div class="bar"><span>${k}</span><div class="track"><i style="width:${val}%"></i></div><b>${val}</b></div>`
            )
            .join("")
        : "<p>Анализ отсутствует.</p>";
      const list = (arr) => (arr && arr.length ? "<ul>" + arr.map((x) => "<li>" + esc(x) + "</li>").join("") + "</ul>" : "<p class='muted'>—</p>");
      const salary =
        v.salary_from || v.salary_to
          ? `${v.salary_from || ""}–${v.salary_to || ""} ${esc(v.salary_currency)}`
          : "не указана";
      $("#detail").innerHTML = `
        <h2>${esc(v.title)} <span class="badge ${decClass(v.decision)}">${esc(v.decision || "")}</span></h2>
        <p class="muted">${esc(v.company)} · ${esc(v.area)} · ${esc(v.schedule)} · ${esc(v.employment)}</p>
        ${v.attention_reason ? `<div class="attn">${esc(v.attention_reason)}</div>` : ""}
        <div class="cols">
          <div>
            <h3>AI-анализ (score ${a ? a.score : "—"}, ${a ? esc(a.provider) : ""})</h3>
            ${bars}
            <h3>Причины соответствия</h3>${list(a && a.reasons)}
            <h3>Риски</h3>${list(a && a.risks)}
          </div>
          <div>
            <h3>Условия</h3>
            <p>Зарплата: ${salary}<br>Опыт: ${esc(v.experience)}<br>
            <a href="${esc(v.url)}" target="_blank" rel="noopener">Источник (${esc(v.external_id)})</a></p>
            <h3>Отклик</h3>
            ${
              d.application
                ? `<p>Статус: <b>${esc(d.application.status)}</b>${d.application.error ? " — " + esc(d.application.error) : ""}</p>
                   <details><summary>Сопроводительное письмо</summary><pre>${esc(d.application.cover_letter)}</pre></details>`
                : "<p class='muted'>Отклик не отправлялся.</p>"
            }
            <h3>Контакты</h3>
            ${
              d.contact
                ? `<p>${esc(d.contact.name)}<br>${esc(d.contact.phone)}<br>${esc(d.contact.email)}</p>`
                : "<p class='muted'>Контакты не опубликованы.</p>"
            }
            <h3>WhatsApp</h3>
            ${
              d.whatsapp
                ? `<p>Статус: ${esc(d.whatsapp.status)}</p>${d.whatsapp.body ? `<pre>${esc(d.whatsapp.body)}</pre>` : ""}`
                : "<p class='muted'>—</p>"
            }
          </div>
        </div>
        <h3>Описание</h3>
        <div class="desc">${esc(v.description)}</div>
        <h3>Технический лог</h3>
        <table class="grid small"><tbody>${d.logs
          .map((l) => `<tr><td>${fmt(l.at)}</td><td>${esc(l.action)}</td><td>${esc(l.detail)}</td></tr>`)
          .join("")}</tbody></table>`;
    },

    async initAttention() {
      refreshModeBadge();
      const d = await api("/api/attention");
      $("#att-body").innerHTML =
        d.items
          .map(
            (v) => `<tr onclick="location.href='/vacancy/${v.id}'">
        <td>${fmt(v.discovered_at)}</td><td>${esc(v.company)}</td>
        <td>${esc(v.title)}</td><td>${v.score ?? "—"}</td><td>${esc(v.reason)}</td></tr>`
          )
          .join("") || '<tr><td colspan="5">Пусто — всё обработано автоматически 🎉</td></tr>';
    },

    async initRuns() {
      refreshModeBadge();
      const d = await api("/api/runs");
      $("#runs-body").innerHTML = d.items
        .map(
          (r) => `<tr><td>${fmt(r.started_at)}</td><td>${r.found}</td><td>${r.new}</td>
        <td>${r.duplicates}</td><td>${r.matched}</td><td>${r.review}</td><td>${r.rejected}</td>
        <td>${r.applied}</td><td>${r.errors}</td><td>${r.ok ? "✓" : "✗"}</td></tr>`
        )
        .join("") || '<tr><td colspan="10">Циклов ещё не было</td></tr>';
    },

    async initSettings() {
      refreshModeBadge();
      const form = $("#settings-form");
      const s = await api("/api/settings");
      for (const el of form.elements) {
        if (!el.name || !(el.name in s)) continue;
        const val = s[el.name];
        if (el.type === "checkbox") el.checked = !!val;
        else if (el.dataset.list !== undefined) el.value = Array.isArray(val) ? val.join(", ") : "";
        else el.value = val == null ? "" : val;
      }
      form.onsubmit = async (e) => {
        e.preventDefault();
        const payload = {};
        for (const el of form.elements) {
          if (!el.name) continue;
          if (el.type === "checkbox") payload[el.name] = el.checked;
          else if (el.dataset.list !== undefined)
            payload[el.name] = el.value.split(",").map((x) => x.trim()).filter(Boolean);
          else if (el.type === "number") payload[el.name] = el.value === "" ? null : Number(el.value);
          else payload[el.name] = el.value;
        }
        await post("/api/settings", payload);
        $("#save-status").textContent = "Сохранено ✓";
        refreshModeBadge();
        setTimeout(() => ($("#save-status").textContent = ""), 2000);
      };
    },
  };
})();

document.addEventListener("DOMContentLoaded", () => {
  if (!document.body.dataset.noauto) Autopilot;
  const badge = document.querySelector("#mode-badge");
  if (badge) {
    fetch("/api/summary")
      .then((r) => r.json())
      .then((s) => {
        badge.textContent = s.run_mode === "production" ? "PRODUCTION" : "DRY RUN";
        badge.className = "mode " + (s.run_mode === "production" ? "prod" : "dry");
      })
      .catch(() => {});
  }
});
