/// The one place the console decides what a map is made of.
///
/// Both map screens — the Situation Board's live map and Map Management — use
/// these, so the basemap changes in one edit rather than two.
///
/// The console previously drew CARTO's "Dark Matter" tiles, which were free
/// and key-less when that code was written. CARTO now answers without a key by
/// serving an "API KEY REQUIRED" watermark instead of map data, so both maps
/// were rendering a grey placeholder. This draws Mapbox's `dark-v11` — the
/// style the design hand-off specifies — and falls back to plain OpenStreetMap
/// when no token is configured, so a checkout without one still gets a working
/// map rather than a blank rectangle.

/// Mapbox public access token, from the environment.
///
/// A `pk.` token is meant to be visible in a client — Vite inlines it into the
/// bundle and anyone can read it out of the page. The protection is the URL
/// restriction you set on the token in your Mapbox account, not secrecy. Set
/// it in `admin-web/.env`:
///
///   VITE_MAPBOX_TOKEN=pk.your_token_here
const TOKEN = import.meta.env.VITE_MAPBOX_TOKEN || '';

export const hasMapboxToken = TOKEN.startsWith('pk.');

/// `dark-v11` is Mapbox's dark style, which is what the design draws its maps
/// on. Raster rather than vector: the console already renders with Leaflet, and
/// swapping to Mapbox GL JS would mean a second map engine in the bundle for a
/// difference nobody looking at a dashboard would notice.
export const TILE_URL = hasMapboxToken
  ? `https://api.mapbox.com/styles/v1/mapbox/dark-v11/tiles/256/{z}/{x}/{y}@2x?access_token=${TOKEN}`
  : 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';

/// Attribution is a licence condition for both providers, not decoration. The
/// map components hide Leaflet's default control and render this instead, so
/// it can be styled to the design.
export const TILE_ATTRIBUTION = hasMapboxToken
  ? '© Mapbox © OpenStreetMap'
  : '© OpenStreetMap';

/// Mapbox's raster tiles stop at zoom 22; OSM's at 19. Past a provider's
/// maximum Leaflet upscales the last real tile rather than requesting a 404.
export const TILE_MAX_ZOOM = hasMapboxToken ? 22 : 19;
