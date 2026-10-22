# Admin console development previews

Three development-only pages, served by the Vite dev server (`npm run dev`,
port 5173). None is part of the production build: `vite build` builds
`index.html` only, and each preview renders only inside `import.meta.env.DEV`.
All data is fictional. No preview reads or writes the stored session, and no
request reaches a server.

| Page | What it shows |
|---|---|
| `/docs/console-preview.html` | The whole console, signed in as a fictional Admin. An in-memory `fetch` stub answers every API call; acknowledge, overlap decisions, affiliate and ID-review decisions and map-layer deletes change only this page. |
| `/docs/console-ready.html` | The UI READY components (features the server does not support yet) and the empty and failed states of Requests and Reports. Every callback is simulated in the page. |
| `/docs/foundations.html` | The shared UI components in both themes. |

The fixtures live in `docs/console-preview.jsx` and `docs/console-ready.jsx`.
They use example names only (`Example Area 1.2`, `example.test` addresses).

Screen-to-frame references: [figma-frames.md](figma-frames.md). What the
server supports per screen: [backend-capabilities.md](backend-capabilities.md).
What is integrated, prepared or blocked:
[FRONTEND_INTEGRATION_HANDOFF.md](FRONTEND_INTEGRATION_HANDOFF.md).
