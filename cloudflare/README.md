# Passwort-Gate fürs Dashboard (Cloudflare Worker, gratis)

GitHub Pages (public Repo) hat keine eingebaute Auth. Dieser Worker legt ein serverseitiges
Passwort-Gate vor die statische Page: ohne gueltiges Cookie wird nichts vom Origin ausgeliefert,
sondern eine Login-Seite. Das Passwort liegt nur als SHA-256-Hash im Worker-Secret.

## Setup (einmalig, ~5 Min)

```bash
# 1. wrangler installieren + anmelden
npm i -g wrangler   # oder: npx wrangler ...
wrangler login

# 2. Worker deployen (aus diesem Ordner)
cd cloudflare
wrangler deploy worker-gate.js --name research-hub-gate
# -> URL: https://research-hub-gate.<dein-account>.workers.dev

# 3. Passwort als Hash setzen (nie Klartext committen!)
echo -n 'DEIN-PASSWORT' | sha256sum        # Hash kopieren
wrangler secret put GATE_HASH               # Hash einfuegen
```

## Eigene Domain (optional)

Domain muss in Cloudflare verwaltet sein: Dashboard -> Workers & Pages -> research-hub-gate ->
Triggers -> Add route: `dashboard.deinedomain.at/*` -> Worker. Dann ist das Gate unter
`https://dashboard.deinedomain.at/` erreichbar. (Alternative: Cloudflare Access, gratis bis 50 Nutzer.)

## Anpassung

- `ORIGIN` in `worker-gate.js` auf die Pages-URL aendern, falls sich Repo-Name aendert:
  `https://wpy4t4hwh4-prog.github.io/GrammatikstattStil`
- Cookie-Lebensdauer: `COOKIE_MAXAGE` (Sekunden).

## Wichtiger Hinweis

Das Repo ist public - die Dateien liegen also ohnehin auf github.com. Das Gate schuetzt die
bequeme URL vor neugierigen Zugriffen; gegen jemanden, der gezielt das Repo findet, hilft nur
ein privates Repo (kostet) oder Daten hinter die Key-geschuetzte API (serve.py auf eigener VM).
