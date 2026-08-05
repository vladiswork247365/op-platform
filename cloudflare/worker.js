// Cloudflare Worker + Containers (бета): по крону дёргает контейнер-рендер.
// Требует пакет @cloudflare/containers и wrangler с поддержкой контейнеров.
// Форма API актуальна на 2025; при новой версии wrangler сверься с доками.
import { Container, getContainer } from "@cloudflare/containers";

export class RenderContainer extends Container {
  defaultPort = 8080;      // service.py слушает 8080
  sleepAfter = "3m";       // засыпает после простоя — платим только за работу
}

export default {
  // крон (wrangler.jsonc → triggers.crons): один цикл рендера
  async scheduled(event, env, ctx) {
    const c = getContainer(env.RENDER);
    ctx.waitUntil(c.fetch(new Request("http://container/run")));
  },
  // ручной триггер: https://<worker>/run — тот же цикл; иначе health
  async fetch(request, env) {
    const c = getContainer(env.RENDER);
    const url = new URL(request.url);
    if (url.pathname === "/run") return c.fetch(new Request("http://container/run"));
    return new Response(JSON.stringify({ ok: true, service: "reels-factory" }), {
      headers: { "content-type": "application/json" },
    });
  },
};
