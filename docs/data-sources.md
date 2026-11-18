# Data sources: evacuation sites and fire hydrants

Where RepLiT's map layers came from, how to cite them, and what their licence
asks of us. Retrieved 18 November 2026.

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

**17 found, not loaded yet:** see [`hydrants/pasay-hydrants-osm.csv`](hydrants/pasay-hydrants-osm.csv).
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

## What the licence asks of RepLiT

- **Attribution where the data is shown.** For example: "Evacuation sites and
  hydrants © OpenStreetMap contributors (ODbL)".
- **Share-alike.** If the layers are ever published as a database, for
  example as a download, they must be offered under the ODbL too. Showing them
  on RepLiT's map does not trigger this.
