// @ts-check
import { defineConfig } from 'astro/config';
import solid from '@astrojs/solid-js';
import tailwindcss from '@tailwindcss/vite';

// Entwicklungs-Proxy: FYOS_DEV_HUB und FYOS_DEV_RUNNER zeigen auf laufende Dienste, z. B.
//   FYOS_DEV_HUB=http://localhost:8080 FYOS_DEV_RUNNER=http://localhost:18438 FYOS_DEV_RUNNER_TOKEN=… npm run dev
// Ohne sie zeigt die Shell nur ihre eigenen Flächen (der Hub gilt als nicht erreichbar).
// Wie in der Auslieferung (nginx/default.conf.template): `/hub-api/*` wird zu `/hub/*`.
const hub = process.env.FYOS_DEV_HUB;
/** @type {Record<string, import('vite').ProxyOptions>} */
const proxy = {};
if (hub) {
  proxy['/hub-api'] = {
    target: hub,
    changeOrigin: true,
    rewrite: (/** @type {string} */ p) => p.replace(/^\/hub-api/, '/hub'),
  };
}
// Agenten-Runner (FYOS_DEV_RUNNER, z. B. http://localhost:18438): dieselbe Tür wie nginx — Pflicht-Kopf
// X-FYOS-Agent: 1 (sonst 404), Präfix /api/agent ab, Cookie weg, Authorization: Bearer aus FYOS_DEV_RUNNER_TOKEN.
// Das Token steht nie im Browser.
const runner = process.env.FYOS_DEV_RUNNER?.trim();
if (runner) {
  const token = process.env.FYOS_DEV_RUNNER_TOKEN ?? '';
  proxy['/api/agent'] = {
    target: new URL(runner).origin,
    changeOrigin: true,
    ws: false,
    rewrite: (/** @type {string} */ p) => p.replace(/^\/api\/agent/, '') || '/',
    /** @param {import('node:http').IncomingMessage} req @param {import('node:http').ServerResponse} res */
    bypass(req, res) {
      if (req.headers['x-fyos-agent'] !== '1' && res) {
        res.statusCode = 404;
        res.end('nicht freigegeben');
        return false;
      }
      return undefined;
    },
    /** @param {import('http-proxy').Server} p */
    configure(p) {
      p.on('proxyReq', (proxyReq) => {
        proxyReq.removeHeader('cookie');
        proxyReq.setHeader('Authorization', `Bearer ${token}`);
      });
    },
  };
}

// https://astro.build/config
export default defineConfig({
  output: 'static',
  devToolbar: { enabled: false },
  // Der Build legt Seiten als Verzeichnisse ab (build.format); nginx leitet `/x` per 301 auf `/x/`.
  // 'ignore' statt 'never', damit der Dev-Server beide Formen annimmt.
  trailingSlash: 'ignore',
  build: {
    format: 'directory',
    assets: '_astro',
    inlineStylesheets: 'auto',
  },
  integrations: [solid()],
  vite: {
    plugins: [tailwindcss()],
    server: { proxy },
    build: {
      sourcemap: process.env.ASTRO_SOURCEMAP === '1',
    },
  },
  prefetch: false,
});
