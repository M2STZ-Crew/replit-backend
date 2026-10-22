# Prompt — redesign the RepLiT Admin web console

Redesign the RepLiT **Admin web console** so it matches the pass 6 Figma design, page **10 — Admin Web Experience**. Use **PRD v13**, which I have already given you, for wording, roles and behaviour. Read this whole brief before changing anything.

## 1. The website today

- **Code:** `H:\replit_backend\admin-web`. React 18, Vite 5, react-router-dom 6, plain JS (`.jsx`), Leaflet maps. There is no UI library. All styling is in `src/index.css` as CSS variables. Dark is the default ground; a light toggle lives in `src/theme.js`.
- **Shell:** `src/components/ConsoleShell.jsx` draws the sidebar. On small screens it shows a bottom bar with a **More** menu.
- **Pages, in `src/pages/`:**
  - `SituationBoard.jsx` (dashboard), `IncidentDesk.jsx` (incidents), `MapManagement.jsx` (map layers)
  - `Affiliates.jsx`, `Accounts.jsx`, `IdReview.jsx`, `ActionRecord.jsx` (audit log), `OrgDirectory.jsx`
  - `Login.jsx`, `Register.jsx` (public affiliate form)
- **Shared pieces:**
  - `components/LiveMap.jsx`, `OrgDialog.jsx`, `SoundSettings.jsx`
  - `live/LiveFeed.jsx` (live updates), `sound/` (new-fire sounds)
  - `lib/status.js` (status labels), `api/client.js` (API calls)
- **Run:** start the `admin-web` entry in `.claude/launch.json` (Vite on :5173). I will give you an admin test account. Never write credentials into files or commits.
- **Deploy:** Vercel builds `admin-web` from `main`. Bump the version in `admin-web/package.json` (now 1.12.6) when you finish.

## 2. The design source

- **Figma:** https://www.figma.com/design/yTInpc7mWlTug0PQzKiW0L/REPLIT---MAIN-- (file key `yTInpc7mWlTug0PQzKiW0L`).
- **Screen map:** node `909:11191`. It lists every destination, who sees it, its screens and the PRD v13 section.
- **Screens:** **A01–A85** (64 screens), drawn at 1440 × 900 and checked at 1280 × 800 and 1024 × 768. Page **08** holds the 17 admin flows.
- **Foundations:** page **03**. Desktop layout, type, surfaces and glass. Pass 6 added no new tokens: map every colour, radius and spacing onto the variables already in `index.css`.
- **Components:** page **04**, the "Desktop Admin web" set. Build one React component per Figma component.
- **Handoff:** page **09**, pass 6 board. Permissions, behaviour and states, responsive rules, console accessibility.
- **Figma MCP:** it only sees pages loaded in the Figma desktop app, so open pages 10, 03, 04 and 09 there first. Per screen, use `get_design_context` for structure, `get_screenshot` to compare, and `get_variable_defs` for tokens.

### Design rules from the file

- Never design a control the backend cannot honour (PRD §1.4).
- One dominant action per screen. Consequential acts get a confirm dialog that repeats the verb ("Acknowledge Area 1.2?" → **Acknowledge**).
- Status is a word first. Colour and position only reinforce it.
- UPPERCASE names things. Questions and instructions are sentence case.
- Depth comes from tone and hairlines. No shadows or glow.
- The mobile app (pass 5) is the visual reference: same orange accent, chips, status colours, map markers and icon style.

## 3. Screens to redesign

| Destination (sidebar group) | Figma screens | Redesigns today's |
|---|---|---|
| **Dashboard** (Operations) | A20 central hub, A21 new-incident sound, A72 AFK organisation, A83 at 1280 | `SituationBoard.jsx` |
| **Incidents** (Operations, red badge) | A22 list/search/filters, A23 detail, A24–A24b acknowledge, A25 view only, A26 on scene, A27–A27b merge, A28 declined, A80 empty, A81 loading, A82 couldn't load, A84 at 1280 | `IncidentDesk.jsx` |
| **Live map** (Operations) | A30 shared incidents, A31 incident selected | `LiveMap.jsx` |
| **Requests** (Operations, red badge) | A40 inbox, A41 detail, A42 sent, A43 water, A44 backup, A45 alarm escalation, A46–A46b BFP decides | new |
| **Water resources** (Resources) | A32 list, A33 map/detail/history, A34–A34b delete, A35 add/update (blocked in Figma) | `MapManagement.jsx` |
| **Reports & CIAR** (Records) | A60 list, A61 post-incident report, A62 CIAR, A63–A63b generating/failed, A66 correction | new |
| **Audit log** (Records) | A64 append-only, A65 add a correction | `ActionRecord.jsx` |
| **Organization** (Organization) | A47 profile and people | `OrgDirectory.jsx`, `OrgDialog.jsx` |
| **Accounts** (Organization) | A48 Coordinators, A49–A49b create | `Accounts.jsx` |
| **Verification** (central hub, red badge) | A50 queue, A51 details masked | `IdReview.jsx` |
| **Affiliates** (central hub, red badge) | A05 requests, A06–A06c accept/decline | `Affiliates.jsx` |
| **Settings** (sidebar footer) | A70 availability and sounds, A71 AFK on | `SoundSettings.jsx` |
| **Outside the console** | A01–A02b sign in, A03–A04 affiliate form, A07–A11 Admin registration, A12 first sign-in | `Login.jsx`, `Register.jsx` |

Sidebar order:

- **Operations:** Dashboard, Incidents, Live map, Requests
- **Resources:** Water resources
- **Records:** Reports & CIAR, Audit log
- **Organization:** Organization, Accounts, Verification, Affiliates
- **Footer:** Settings

Verification and Affiliates are for the Barangay 76 central hub only.

### Layout, states and access

- **Responsive:**
  - At 1280 px and wider, the full sidebar shows.
  - From 1024 to 1279 px, it collapses to the **Sidebar rail** (A85).
  - Below 1024 px is not designed. Keep today's small-screen layout working.
- **States:** every list and detail gets its empty, loading and couldn't-load state, as drawn in A80–A82.
- **Accessibility:**
  - Every action reachable by keyboard, with a visible focus ring. Esc closes dialogs.
  - Text contrast at least 4.5:1.
  - Reduced motion respected.
- **Light theme:** out of Figma scope. Design to dark, and keep the existing light toggle readable.

## 4. Boundaries

- This is a redesign of `admin-web`. Keep every current data call, action, live update and sound working. Change how they look and read, not what they call.
- Do not change the backend (`app/`), the mobile app, or `observer-web/`.
- The backend is not fully on PRD v13 yet. Check `app/api/routes/` before wiring any screen.
  - Some v13 features have no endpoint yet: AFK, Admin-to-Admin water and backup requests, correction entries, a declined status, the CIAR as its own record, and the Admin registration link.
  - Lay those screens out from the Figma, but do not ship dead buttons. Leave a control out until its endpoint exists, and list it in your report.
- If the Figma and the working console disagree, follow the Figma and tell me. For example, Admins cannot reject in v13, and A35 add/update is blocked.

## 5. How to work and what to hand back

1. Pull `main`, then work on a branch.
2. Take **before** screenshots of every current page at 1440 × 900, 1280 × 800 and 1024 × 768.
3. Build the shared components first: shell, sidebar and rail, page header, table, chips, count badge, confirm dialog, state panels. Then redesign one destination at a time. After each, compare it with the Figma screenshot and check the browser console for errors.
4. `npm run build --prefix admin-web` must pass.
5. Take **after** screenshots at the same sizes and put them side by side with the before ones.
6. Don't commit or push until I say so.

Hand back:

- A coverage table, A01–A85: **Done**, **Partial** or **Waiting on backend**, each with a one-line reason.
- The before and after images.
- Every place you followed the Figma over today's behaviour.
- What you could not verify. For example, Safari isn't available on this machine.
