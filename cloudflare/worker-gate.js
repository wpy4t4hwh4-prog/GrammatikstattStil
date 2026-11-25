// Cloudflare Worker: Passwort-Gate (reverse proxy) vor dem statischen Dashboard auf GitHub Pages.
// Free-Plan-tauglich: workers.dev-Subdomain oder eigene Domain via Workers-Route.
// Das Passwort liegt als SHA-256-Hash im Worker-Secret (nie im Klartext im Client-Code der Page).
//
// Setup siehe cloudflare/README.md

const ORIGIN = "https://wpy4t4hwh4-prog.github.io/GrammatikstattStil"; // ohne fuehrenden Slash am Ende
const COOKIE = "gate";
const COOKIE_MAXAGE = 60 * 60 * 24 * 7; // 7 Tage

async function sha256hex(s) {
  const b = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, "0")).join("");
}

function hasGateCookie(request) {
  const c = request.headers.get("Cookie") || "";
  return /(?:^|;\s*)gate=ok(?:;|$)/.test(c);
}

function loginPage(redirect, wrong) {
  return `<!doctype html><html lang="de"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Research Hub - Login</title>
<style>body{font-family:-apple-system,system-ui,sans-serif;background:#f5f5f7;color:#1d1d1f;display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}
.card{background:#fff;padding:28px;border-radius:18px;box-shadow:0 8px 24px rgba(0,0,0,.08);width:min(92vw,340px)}
h1{font-size:18px;margin:0 0 16px}input{width:100%;padding:10px 12px;border:1px solid #d2d2d7;border-radius:10px;font-size:16px;box-sizing:border-box}
button{margin-top:12px;width:100%;padding:11px;border:0;border-radius:10px;background:#0a84ff;color:#fff;font-size:16px}
.err{color:#ff453a;font-size:13px;margin-top:10px}</style>
<div class="card"><h1>Research Hub</h1>
<form method="POST" action="/__gate?r=${encodeURIComponent(redirect)}">
<input type="password" name="pw" placeholder="Passwort" autofocus required autocomplete="current-password">
<button type="submit">Anmelden</button>
${wrong ? '<div class="err">Falsches Passwort.</div>' : ""}
</form></div></html>`;
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // Login-Endpunkt
    if (url.pathname === "/__gate" && request.method === "POST") {
      const form = await request.formData();
      const pw = String(form.get("pw") || "");
      const hash = await sha256hex(pw);
      const redirect = url.searchParams.get("r") || "/";
      if (env.GATE_HASH && hash === env.GATE_HASH) {
        return new Response(null, {
          status: 302,
          headers: {
            Location: redirect.startsWith("/") ? redirect : "/",
            "Set-Cookie": `${COOKIE}=ok; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=${COOKIE_MAXAGE}`,
          },
        });
      }
      return new Response(loginPage(redirect, true), {
        status: 401,
        headers: { "Content-Type": "text/html; charset=utf-8" },
      });
    }

    // Gate: ohne gueltiges Cookie -> Login-Seite (nichts vom Origin ausliefern)
    if (!hasGateCookie(request)) {
      return new Response(loginPage(url.pathname + url.search, false), {
        headers: { "Content-Type": "text/html; charset=utf-8" },
      });
    }

    // Proxy zum statischen Origin (GitHub Pages). Pfad relativ an ORIGIN haengen.
    const target = ORIGIN + "/" + url.pathname.replace(/^\/+/, "") + url.search;
    const resp = await fetch(target, request);
    const headers = new Headers(resp.headers);
    headers.set("X-Robots-Tag", "noindex");
    return new Response(resp.body, { status: resp.status, statusText: resp.statusText, headers });
  },
};
