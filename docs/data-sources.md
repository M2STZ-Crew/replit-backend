# Data sources: evacuation sites, fire hydrants, cisterns and bodies of water

Where RepLiT's map layers came from, how to cite them, and what their licence
asks of us. Retrieved 18 November 2026. Pasay City came first (the two
sections below); [Metro Manila](#metro-manila) followed the same day.

## Evacuation sites: Pasay City's covered courts

**Loaded 18 November 2026:** 22 sites, the rows marked `yes` in
[`evacuation-sites/pasay-covered-courts-review.csv`](evacuation-sites/pasay-covered-courts-review.csv).
These are roofed sports halls (most are barangay covered courts), a covered
basketball court, and barangay multi-purpose halls. Each row keeps its
OpenStreetMap link.

**Citation (APA 7)**

> OpenStreetMap contributors. (2026). *Pasay City, Philippines: sports halls,
> covered courts and multi-purpose halls* [Data set]. OpenStreetMap Foundation.
> Retrieved November 18, 2026, from https://www.openstreetmap.org, via the
> Overpass API (https://overpass-api.de).

**Addresses.** Each site's barangay and street come from Nominatim reverse
geocoding: OpenStreetMap Foundation, *Nominatim*,
https://nominatim.openstreetmap.org, retrieved November 18, 2026.

**Licence.** © OpenStreetMap contributors. Available under the Open Database
License (ODbL) 1.0, https://www.openstreetmap.org/copyright.

**Query used** (Overpass QL, Pasay City's boundary, admin_level 6)

```
area["boundary"="administrative"]["admin_level"="6"]["name"~"Pasay"]->.pasay;
(
  nwr(area.pasay)["leisure"="sports_hall"];
  nwr(area.pasay)["leisure"="pitch"]["sport"="basketball"]["covered"="yes"];
  nwr(area.pasay)["amenity"="community_centre"]["name"~"multi-?purpose|barangay",i];
);
out center tags;
```

## Fire hydrants

**Loaded 18 November 2026** ("Yes, load them"): all 17 in
[`hydrants/pasay-hydrants-osm.csv`](hydrants/pasay-hydrants-osm.csv).
Each keeps its OpenStreetMap reference in `source`, for example
`openstreetmap:node/1745104230`. Its `code` stays empty for BFP's own hydrant
code, and its status is `unknown` until BFP checks it.
All are pillar hydrants on sidewalks, 16 of them in Barangay 76. Each row gives
its OpenStreetMap link. Where a mapper recorded it, a row also says the hydrant
was surveyed on site or links a street-level photo.

**Citation (APA 7)**

> OpenStreetMap contributors. (2026). *Pasay City, Philippines: fire hydrants
> (emergency=fire_hydrant)* [Data set]. OpenStreetMap Foundation. Retrieved
> November 18, 2026, from https://www.openstreetmap.org, via the Overpass API
> (https://overpass-api.de).

**Street-level photos.** Mapillary, https://www.mapillary.com, CC BY-SA 4.0.

**Licence.** © OpenStreetMap contributors, ODbL 1.0, as above.

**Why not Mapbox or Google Maps.** Neither publishes hydrant locations, so
neither has hydrants to find. Their terms also do not allow copying places or
positions from their maps into another database.

**The authoritative source** is the hydrant inventory kept by BFP Pasay and by
Maynilad, the water concessionaire for Pasay City. RepLiT keeps each hydrant's
reported status apart from what BFP finds on the ground (`ground_truth_status`),
so BFP can mark each one as checked.

## Metro Manila

**Loaded 18 November 2026** ("now, let's get all of the data within
metropolitan manila only"): every fire hydrant, covered court, fire water tank
and covered reservoir, and river, creek, pond and lake that OpenStreetMap has
in Metro Manila (the National Capital Region, ISO 3166-2 `PH-00`: its 16
cities and Pateros). The lists are in [`metro-manila/`](metro-manila/), one row
per place, each with its city and its OpenStreetMap link.

| Layer | In the list | Loaded | Already there |
|---|---:|---:|---:|
| Fire hydrants | 1,281 | 1,254 | 27 |
| Evacuation sites (covered courts) | 1,357 | 1,305 | 52 |
| Cisterns (fire water tanks, covered reservoirs) | 11 | 11 | 0 |
| Bodies of water | 466 | 448 | 18 |

"Already there" means the same place loaded before (Pasay's 17 hydrants and
22 courts are in these lists), or a place within a few metres of one already
loaded: 10 m for a hydrant or a cistern, 30 m for a court, 50 m for a body of
water. Loading the lists again adds nothing.

**What each layer holds**

- **Fire hydrants**: every `emergency=fire_hydrant`, mostly pillar hydrants
  (899) and underground ones (235). As with Pasay's, each keeps its
  OpenStreetMap reference in `source`, its `code` stays empty for BFP's own,
  and its status is `unknown` until BFP checks it.
- **Evacuation sites**: roofed sports halls (1,116), barangay multi-purpose
  halls (100), covered basketball courts (85) and other places named a covered
  court (56). Gyms, malls and game parks are left out. Each site's city says
  whether it is outside Pasay. These are places a city could open as a
  shelter, not its list of designated evacuation centres; each city's disaster
  office keeps that list.
- **Cisterns**: firefighting water tanks (3) and covered reservoirs (8), as
  asked ("Only fire tanks + reservoirs"). Water towers and other storage tanks
  are left out. Each one's description gives its kind and OpenStreetMap
  reference.
- **Bodies of water**: rivers (185), ponds (161), streams (92), and
  reservoirs, canals, lakes and lagoons, as asked ("Rivers, creeks, ponds,
  lakes"). Drains, wastewater, swimming pools and fountains are left out, and
  so is an unnamed one unless it is a lake, pond, reservoir or lagoon. A named
  river or creek mapped in many pieces is kept once in each city it runs
  through (twice where it is also mapped as an area). Each one's description
  gives its city and OpenStreetMap reference.

**City and street.** A place's city is the OpenStreetMap city or municipal
boundary (`admin_level` 6) it falls inside. Its street is its own OpenStreetMap
address, where a mapper added one.

**On the map.** About 3,100 places are too many to draw at once on an older
phone, so the app and the console draw a layer's points from street level in
(zoom 14), only those on or near the screen, and below that say "Zoom in to
see the places you turned on" ("Only nearby, when zoomed in"). The app still
downloads them all for use offline.

**Citations (APA 7)**

> OpenStreetMap contributors. (2026). *Metro Manila, Philippines: fire
> hydrants (emergency=fire_hydrant)* [Data set]. OpenStreetMap Foundation.
> Retrieved November 18, 2026, from https://www.openstreetmap.org, via the
> Overpass API (https://overpass-api.de).

> OpenStreetMap contributors. (2026). *Metro Manila, Philippines: sports
> halls, covered courts and multi-purpose halls* [Data set]. OpenStreetMap
> Foundation. Retrieved November 18, 2026, from https://www.openstreetmap.org,
> via the Overpass API (https://overpass-api.de).

> OpenStreetMap contributors. (2026). *Metro Manila, Philippines: firefighting
> water tanks and covered reservoirs* [Data set]. OpenStreetMap Foundation.
> Retrieved November 18, 2026, from https://www.openstreetmap.org, via the
> Overpass API (https://overpass-api.de).

> OpenStreetMap contributors. (2026). *Metro Manila, Philippines: rivers,
> streams, canals, ponds and lakes* [Data set]. OpenStreetMap Foundation.
> Retrieved November 18, 2026, from https://www.openstreetmap.org, via the
> Overpass API (https://overpass-api.de).

> OpenStreetMap contributors. (2026). *Metro Manila, Philippines: city and
> municipal boundaries (admin_level 6)* [Data set]. OpenStreetMap Foundation.
> Retrieved November 18, 2026, from https://www.openstreetmap.org, via the
> Overpass API (https://overpass-api.de).

**Licence.** © OpenStreetMap contributors, ODbL 1.0, as above.

**Queries used** (Overpass QL). Each layer was its own query: the area line,
the layer's statements in `( … );`, then `out center tags;` (`out geom;` for
the boundaries).

```
area["ISO3166-2"="PH-00"]->.ncr;

// Fire hydrants
nwr(area.ncr)["emergency"="fire_hydrant"];

// Covered courts
nwr(area.ncr)["leisure"="sports_hall"];
nwr(area.ncr)["leisure"="pitch"]["covered"="yes"];
nwr(area.ncr)["amenity"="community_centre"]["name"~"multi-?purpose|barangay|covered",i];
nwr(area.ncr)["name"~"covered court",i];

// Cisterns (of these, fire water tanks, suction points and covered reservoirs are kept)
nwr(area.ncr)["emergency"~"^(water_tank|suction_point|fire_water_pond)$"];
nwr(area.ncr)["man_made"="reservoir_covered"];
nwr(area.ncr)["man_made"="storage_tank"]["content"="water"];
nwr(area.ncr)["man_made"="water_tower"];

// Bodies of water
nwr(area.ncr)["natural"="water"];
nwr(area.ncr)["waterway"~"^(river|canal|stream|drain)$"]["name"];

// City and municipal boundaries
rel(area.ncr)["boundary"="administrative"]["admin_level"="6"];
```

## Streets: what a fire is called

**Fetched 19 November 2026** for v1.12.42 ("Corner, else Near"): Metro
Manila's named streets, from which each new fire is named
(`app/services/place_names.py`): "Taft Avenue corner Gil Puyat Avenue" where
two named streets meet within 30 m of it, else "Near F. Victor Street". They
are loaded into `public.streets` by `scripts/load_streets.py`.

- **Kept:** ways tagged `highway` = trunk, primary, secondary, tertiary (and
  their links), unclassified, residential, living_street, pedestrian or road,
  with a `name`, and with a point inside one of the 17 city boundaries above:
  57,499 ways, 56,128 of them loaded, under 13,779 names.
- **Left out:** expressways and service roads, paths, and bridges, flyovers
  and tunnels (a fire beneath a flyover is on the street below, and a flyover
  would make a corner where there is none).
- **OpenStreetMap data as of** 19 November 2026, 06:35 UTC.

**Citation (APA 7)**

> OpenStreetMap contributors. (2026). *Metro Manila, Philippines: named
> streets (highway=* with name)* [Data set]. OpenStreetMap Foundation.
> Retrieved November 19, 2026, from https://www.openstreetmap.org, via the
> Overpass API (https://overpass-api.de).

**Licence.** © OpenStreetMap contributors, ODbL 1.0, as above. A fire's name
is drawn from this database, so a fire named this way is attributed with the
map layers ("© OpenStreetMap contributors").

**Query used** (Overpass QL). One query for the whole region timed out on
every public server, so the region's bounding box was cut into boxes 0.06°
square and each asked in turn; a way in several boxes was kept once, and only
those inside the city boundaries were loaded.

```
way["highway"~"^(trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|unclassified|residential|living_street|pedestrian|road)$"]["name"](south,west,north,east);
out geom qt;
```

## Barangays: where a fire is, and the barangay layer

Since v1.12.45 a fire is named in its barangay ("Near F. Victor St., Brgy 76,
Pasay"; in full "Near F. Victor Street, Barangay 76 Zone 10, Pasay"), and
every map can draw Metro Manila's barangays with Pasay's High fire-risk zones.
The files are in `docs/barangays/`; `scripts/load_barangays.py` loads them.

**Outlines.** The 1,712 barangays of Metro Manila (`ncr-barangays-psa.geojson.gz`,
layer `phl_admin4`, adm1 `PH13`), chosen over OpenStreetMap, which has 900 of
them (Manila 152 of 899):

> Philippine Statistics Authority and National Mapping and Resource
> Information Authority. (2025). *Philippines: Subnational administrative
> boundaries (COD-AB)*, version 3, valid 13 February 2025 [Data set]. UN OCHA,
> Humanitarian Data Exchange. https://data.humdata.org/dataset/cod-ab-phl.
> Retrieved November 19, 2026 (`phl_admin_boundaries.gdb.zip`, 360,586,879
> bytes).

Licence: CC BY-IGO 3.0. Shown on the maps as "Barangay boundaries: PSA/NAMRIA
via UN OCHA (CC BY-IGO)".

**Zones and Manila's districts** (`metro-manila-barangays.csv`), from
Wikipedia's lists, read through the MediaWiki API on November 20, 2026 (CC
BY-SA 4.0). PSA's own PSGC pages could not be read: psa.gov.ph answers
scripts and the browser alike with a "Verify you are human" loop.

> Wikipedia contributors. (2026). *Pasay* (revision 1386022808), *Caloocan*
> (revision 1386021331), and Manila's district articles: *Tondo, Manila*
> (1384934795), *Binondo* (1378931041), *Quiapo, Manila* (1376581025), *San
> Nicolas, Manila* (1378198975), *Santa Cruz, Manila* (1383250899), *Sampaloc,
> Manila* (1376763701), *San Miguel, Manila* (1376766913), *Ermita*
> (1384974235), *Intramuros* (1386421980), *Malate, Manila* (1379561741),
> *Paco, Manila* (1386051986), *Pandacan* (1378961766), *Port Area, Manila*
> (1378966424), *Santa Ana, Manila* (1386341155), *San Andres, Manila*
> (1377113667), *Santa Mesa* (1380955117). In *Wikipedia, The Free
> Encyclopedia*. Retrieved November 20, 2026, from https://en.wikipedia.org.

What the file carries beyond PSA's names:

- `name`: PSA's name without a trailing note ("San Jose (Pob.)" is "San Jose").
- The ten EMBO barangays (Cembo, Comembo, East Rembo, Pembo, Pitogo, Post
  Proper Northside and Southside, Rizal, South Cembo, West Rembo) are named
  Taguig, as the Supreme Court ruled, though PSA's file still has them under
  Makati.
- Port Area (649–653) is Zone 68, which its article says in words.
- Caloocan's Barangay 176 is one barangay: PSA draws no outlines for 176-A to
  176-F, so none are invented.

**High fire-risk zones** (`pasay-high-fire-risk-barangays.csv`): the 86
barangays of Pasay's Zones 8, 11, 13, 14, 15, 16, 19 and 20, from RepLiT's
research-based fire incident assessment (2022-01-01 to 2026-11-19). They are
shown as "High fire-risk zone (research-based)", never as a BFP designation,
and keep their outlines as drawn. Zones come from the revision of *Barangays
of Pasay* the assessment cites:

> Wikipedia contributors. (2023, September 12). *Barangays of Pasay*
> (revision 1175023360). In *Wikipedia, The Free Encyclopedia*.

## What the licence asks of RepLiT

- **Attribution where the data is shown.** For example: "Map layers ©
  OpenStreetMap contributors (ODbL)".
- **Share-alike.** If the layers are ever published as a database, for
  example as a download, they must be offered under the ODbL too. Showing them
  on RepLiT's map does not trigger this.
- **The lists in `docs/`** (`evacuation-sites/`, `hydrants/`, `metro-manila/`)
  are extracts of OpenStreetMap, so they are © OpenStreetMap contributors and
  available under the ODbL 1.0 too.
