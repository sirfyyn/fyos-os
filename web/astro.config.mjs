// @ts-check
import { defineConfig } from 'astro/config';
import solid from '@astrojs/solid-js';
import tailwindcss from '@tailwindcss/vite';

// Entwicklungs-Proxy: FYOS_DEV_HUB und FYOS_DEV_AGENT zeigen auf laufende Dienste, z. B.
//   FYOS_DEV_HUB=http://localhost:8080 FYOS_DEV_AGENT=http://localhost:18789 npm run dev
// Ohne sie zeigt die Shell nur ihre eigenen Flächen (der Hub gilt als nicht erreichbar).
// Wie in der Auslieferung (nginx/default.conf.template): `/hub-api/*` wird zu `/hub/*`, `/agent` geht mit seinem
// Präfix durch, denn das Gateway liefert seine Oberfläche unter gateway.controlUi.basePath=/agent aus.
const hub = process.env.FYOS_DEV_HUB;
const agent = process.env.FYOS_DEV_AGENT;
/** @type {Record<string, import('vite').ProxyOptions>} */
const proxy = {};
if (hub) {
  proxy['/hub-api'] = {
    target: hub,
    changeOrigin: true,
    rewrite: (/** @type {string} */ p) => p.replace(/^\/hub-api/, '/hub'),
  };
}
if (agent) {
  proxy['/agent'] = {
    target: agent,
    changeOrigin: true,
    ws: true,
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
