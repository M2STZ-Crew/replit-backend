# RepLiT Observer Console

The web surface for **observer team captains** — Police, Medical and Barangay
sub-admins (Master Context v10, Sections 2.6 and 3.1). React 18 + Vite +
react-leaflet, deployed separately from the Admin Console in `../admin-web`.

Observers watch and acknowledge; they do not run the response. So this console
has exactly three surfaces:

| Surface | What it shows |
|---|---|
| **Dashboard** | Live incidents where a reporter asked for your agency, and which are awaiting your Accept |
| **Map** (Monitoring) | Those incidents on the map, with evacuation sites and risk areas. When Admin routes an incident to your agency or your team, an **Accept** control appears |
| **Audit log** (History) | The append-only action record, limited by the server to incidents your agency can see |

**Accept** acknowledges receipt — yes, we see it; yes, we are on it. It is written
to `audit_logs` and never changes the incident's status. There is no Reject,
verify, dispatch or resolve here: Fire Volunteer and BFP coordinators do those
from the mobile app.

When Admin routes an incident to you, your agency's notification sound plays
(Section 2.8). Sounds can be turned off, or muted and adjusted per category,
from the control at the bottom of the sidebar. The cues are synthesized
placeholders until the final recordings are chosen — see `src/sound/cues.js`.

## Run

```bash
cp .env.example .env
npm install
npm run dev
```

The dev server runs on **http://localhost:5174**. The backend must allow that
origin: it is in the default `CORS_ORIGINS`, but if your `.env` sets
`CORS_ORIGINS` explicitly, add `http://localhost:5174` to it.

Sign in with a `sub_admin` account whose agency is `police`, `medical` or
`barangay`. Anyone else is turned away with a pointer to their own surface.

## Shared code

`src/sound/cues.js`, `src/lib/status.js`, `src/map/tiles.js` and
`src/components/SoundSettings.jsx` mirror the Admin Console's copies. The two
consoles are separate SPAs on purpose (Section 3.1), so the files are copied
rather than shared — change both when you change one.

## Deploy

As for `admin-web` (see `../DEPLOY.md`): root directory `observer-web`, build
`npm run build`, output `dist`. `public/_redirects` and `vercel.json` already
route every path to `index.html`. Set `VITE_API_BASE` and `VITE_MAPBOX_TOKEN` in
the host's environment, and set `VITE_OBSERVER_URL` on the Admin Console so it
can point observers here.
