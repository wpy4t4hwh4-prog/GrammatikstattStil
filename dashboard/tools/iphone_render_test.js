#!/usr/bin/env node
/* iPhone/Safari-Render-Test fuer dashboard/index.html (jsdom).
   Aufruf:  node tools/iphone_render_test.js
   Voraussetzung: jsdom installiert (z. B. `npm i jsdom` in einem Dev-Ordner);
   ohne jsdom wird SKIP ausgegeben und Exit-Code 0 geliefert (kein Harter Fehler).

   Emuliert iPhone 14 (390x844, iPhone-Safari-UA, maxTouchPoints=5, kein serviceWorker)
   und prueft: Rendern der 10 Nav-Buttons (inkl. Agent), Deep-Link ?tab=, Tab-Wechsel per Tap,
   Daten-Laden aus data/project.json, iOS-kritische Metas (viewport-fit=cover,
   kein Zoom-Block, apple-*-Metas, apple-touch-icon, manifest), dialog-Fallback,
   keine JS-Fehler. */
'use strict';
const fs = require('fs');
const path = require('path');

let JSDOM, VirtualConsole;
try {
  ({ JSDOM, VirtualConsole } = require('jsdom'));
} catch (e) {
  console.log('SKIP: jsdom nicht installiert (npm i jsdom) — statische iOS-Checks siehe forschungsagent/tests/run_tests.py (PwaAppTests)');
  process.exit(0);
}

const DASH = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(DASH, 'index.html'), 'utf8');
const projectJson = fs.readFileSync(path.join(DASH, 'data', 'project.json'), 'utf8');
const sampleJs = fs.readFileSync(path.join(DASH, 'data', 'sample-data.js'), 'utf8');
const templatesJson = fs.readFileSync(path.join(DASH, 'data', 'templates.json'), 'utf8');

const IPHONE_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1';
const errors = [];
const vc = new VirtualConsole();
vc.on('jsdomError', e => errors.push('jsdomError: ' + (e.detail && e.detail.message || e.message)));
vc.on('error', (...a) => errors.push('console.error: ' + a.join(' ')));

function makeDom(url) {
  return new JSDOM(html, {
    url,
    runScripts: 'dangerously',
    pretendToBeVisual: true,
    virtualConsole: vc,
    beforeParse(window) {
      Object.defineProperty(window.navigator, 'userAgent', { value: IPHONE_UA, configurable: true });
      Object.defineProperty(window.navigator, 'maxTouchPoints', { value: 5, configurable: true });
      window.innerWidth = 390; window.innerHeight = 844; // iPhone 14
      window.eval(sampleJs); // window.DASHBOARD_DATA (Fallback-Pfad)
      window.fetch = async (input) => {
        const u = new URL(String(input), window.location.href);
        const respond = (body) => ({ ok: true, status: 200, json: async () => JSON.parse(body), text: async () => body });
        if (u.pathname.endsWith('data/project.json')) return respond(projectJson);
        if (u.pathname.endsWith('data/templates.json')) return respond(templatesJson);
        return { ok: false, status: 404, json: async () => ({}), text: async () => '' };
      };
      delete window.navigator.serviceWorker; // SW-Registrierung muss ge guarded sein
    }
  });
}

(async () => {
  let failed = 0;
  const assert = (cond, msg) => {
    if (!cond) { failed++; console.error('FAIL:', msg); } else console.log('ok:', msg);
  };

  const dom = makeDom('https://hub.test/?tab=verzeichnis');
  const w = dom.window, d = w.document;
  await new Promise(r => setTimeout(r, 400));

  assert(d.querySelectorAll('nav button').length === 10, 'iPhone: 10 Nav-Buttons rendern (inkl. Agent)');
  const active = d.querySelector('nav button.active');
  assert(active && active.dataset.page === 'verzeichnis', 'iPhone: Deep-Link ?tab=verzeichnis aktiv');
  assert(d.querySelector('section.page.active') && d.querySelector('section.page.active').id === 'page-verzeichnis', 'iPhone: page-verzeichnis aktiv');
  assert(w.eval('!!DATA && !!DATA.kstand && DATA.kstand.positionen > 0'), 'iPhone: DATA aus data/project.json geladen');
  assert((d.querySelector('#statCards') || { innerHTML: '' }).innerHTML.length > 10, 'iPhone: Stat-Cards gerendert');

  const b = d.querySelector('nav button[data-page="komm"]');
  b.click();
  assert(d.querySelector('nav button.active').dataset.page === 'komm', 'iPhone: Tap wechselt auf Komm-Tab');
  assert(d.querySelector('section.page.active').id === 'page-komm', 'iPhone: page-komm sichtbar');

  const vp = (d.querySelector('meta[name="viewport"]') || {}).content || '';
  assert(vp.includes('viewport-fit=cover'), 'viewport-fit=cover vorhanden');
  assert(vp.includes('interactiveWidget=resizes-content'), 'interactiveWidget=resizes-content (Tastatur schrumpft Viewport)');
  assert(!/maximum-scale=1|user-scalable=no/.test(vp), 'kein Zoom-Block im Viewport (Accessibility)');
  assert(!!d.querySelector('meta[name="apple-mobile-web-app-capable"]'), 'apple-mobile-web-app-capable');
  assert(!!d.querySelector('meta[name="apple-mobile-web-app-status-bar-style"]'), 'apple-mobile-web-app-status-bar-style');
  assert(!!d.querySelector('link[rel="apple-touch-icon"]'), 'apple-touch-icon verlinkt');
  assert(!!d.querySelector('link[rel="manifest"]'), 'manifest verlinkt');
  assert(html.includes("typeof d.showModal === 'function'"), 'dialog showModal-Fallback (Safari < 15.4)');
  assert(html.includes("'serviceWorker' in navigator"), 'SW-Registrierung ge guarded');
  assert(html.includes('overscroll-behavior-y: none'), 'kein Pull-to-Refresh-Reload (overscroll-behavior-y)');
  assert(/@media \(pointer: coarse\)[\s\S]*font-size:\s*16px/.test(html), 'Coarse: Inputs 16px (kein iOS-Auto-Zoom)');
  assert(/@media \(pointer: coarse\)[\s\S]*min-height:\s*44px/.test(html), 'Coarse: Touch-Targets >= 44px');
  assert(html.includes('touch-action: manipulation'), 'touch-action: manipulation (kein Doppel-Tipp-Zoom)');
  assert(html.includes('100dvh'), 'Chat-Card mit dvh-Viewport (Composer bleibt sichtbar)');
  assert((html.match(/env\(safe-area-inset/g) || []).length >= 4, 'safe-area-Insets an >= 4 Stellen');
  assert(html.includes('-webkit-backdrop-filter'), '-webkit-backdrop-filter fuer aeltere Safari');

  // Session-Auth + Projekte + Agent-Tab (Hub-Modus)
  assert(!!d.querySelector('#loginOverlay[hidden]'), 'Login-Overlay vorhanden und initial hidden');
  assert(!!d.querySelector('#loginForm #loginPw'), 'Login-Passwortfeld vorhanden');
  assert(/#loginPw \{[^}]*font-size: 16px/.test(html), 'Login-Input 16px (kein iOS-Auto-Zoom)');
  assert(/#loginPw \{[^}]*min-height: 44px/.test(html), 'Login-Input 44px Touch-Target');
  assert(!!d.querySelector('#projWrap #projSel') && !!d.querySelector('#projWrap #projNew'), 'Projekt-Picker im Header');
  assert(!!d.querySelector('nav button[data-page="agent"]'), 'Agent-Nav-Button vorhanden');
  assert(!!d.querySelector('#liveBadge #liveDetail'), 'Badge: kompaktes #liveLabel + #liveDetail (Stats nur Desktop)');
  assert(html.includes('.hright nav { position: fixed; left: 12px; right: 12px; bottom: calc(8px + env(safe-area-inset-bottom)); z-index: 20;'), 'iPhone: Tab-Bar als schwebende Glas-Kapsel (iOS 26 Liquid Glass)');
  assert(html.includes('max-width: none; border-radius: 999px; border: 1px solid var(--glass-border);'), 'iPhone: Tab-Bar-Kapsel mit Glas-Rand (999px)');
  assert(html.includes('header { -webkit-backdrop-filter: none; backdrop-filter: none; }'), 'iPhone: backdrop-filter mobil AUS (sonst klebt die fixed Tab-Bar am Header statt am Viewport)');
  assert(!!d.querySelector('#page-agent'), 'Agent-Seite vorhanden');
  assert(!!d.querySelector('#page-agent #wfRun') && !!d.querySelector('#page-agent #noteSend') && !!d.querySelector('#page-agent #btnQvLive'), 'Agent-Tab: Run/Notiz/QV-live Buttons');
  assert(/@media \(max-width: 760px\) \{ #agentGrid \{ grid-template-columns: 1fr !important; \}/.test(html), 'Agent-Grid mobil 1 Spalte');
  assert(html.includes("'X-Hub-CSRF'"), 'CSRF-Header im api()-Wrapper');
  assert(html.includes('async function boot()'), 'Boot prueft /api/auth/me vor App-Start');
  assert(/id="wfInput"[\s\S]{0,400}font-size:\s*16px/.test(html), 'Agent-Input 16px (kein iOS-Zoom)');

  const realErrors = errors.filter(e => !/Could not load|not implemented|css/i.test(e));
  assert(realErrors.length === 0, 'keine JS-Fehler' + (realErrors.length ? ': ' + realErrors.slice(0, 3).join(' | ') : ''));

  console.log(failed ? ('\n' + failed + ' FEHLGESCHLAGEN') : '\nAlle iPhone-Checks bestanden.');
  process.exit(failed ? 1 : 0);
})();
