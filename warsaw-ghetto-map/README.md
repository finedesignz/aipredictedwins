# Warsaw Ghetto Wall — Interactive Map

A single-page, mobile-first map of the **Warsaw Ghetto wall line (1940–1943)** overlaid on
modern Warsaw. It shows your **live location** relative to the wall and pins the
**surviving wall fragments, memorials, and "Mur getta" boundary markers**.

No build step, no dependencies to install — just static `index.html` (Leaflet + CARTO/OSM tiles
loaded from CDN).

## Features

- 🔴 Approximate **maximum ghetto perimeter** drawn over today's streets (orientation, not survey accuracy).
- 📍 **Live geolocation** — a "you are here" dot, accuracy circle, whether you're **inside/outside**
  the former ghetto, **distance to the wall line**, and the **nearest pin**. Auto-locates on load and
  re-centres with the ◎ button.
- 🧱 **Surviving wall fragments** (Sienna 55 / Złota 62, Waliców 11, Żelazna).
- ✡ **Memorials & sites** (Ghetto Heroes Monument, Umschlagplatz, Mila 18, POLIN, Pawiak,
  Nożyk Synagogue, Footbridge of Memory, Grzybowski Square).
- ▮ **Boundary-line markers** (the 2008/2010 cast-iron "MUR GETTA" pavement line, selected points).
- 🚶 Every pin has a **walking-directions** link.

## Run locally

```bash
cd warsaw-ghetto-map
python3 -m http.server 8080
# open http://localhost:8080
```

> Geolocation requires a secure context. `localhost` and any `https://` host (incl. Cloudflare Pages)
> work; a plain `http://` LAN IP will not grant location.

## Deploy on Cloudflare Pages

**Option A — Dashboard (Git):**
1. Cloudflare Dashboard → **Workers & Pages** → **Create** → **Pages** → **Connect to Git**.
2. Pick this repo, set **Root directory / build output** to `warsaw-ghetto-map`.
3. **Build command:** *(leave empty)* · **Output directory:** `warsaw-ghetto-map` (or `/` if root is set).
4. Deploy. Cloudflare serves `index.html` directly.

**Option B — Wrangler (direct upload), no Git wiring:**
```bash
cd warsaw-ghetto-map
npx wrangler pages deploy . --project-name warsaw-ghetto-wall
```

**Option C — Drag & drop:** zip the folder contents and drop them into
Pages → *Upload assets*.

## Data & accuracy

The wall outline is an **approximate reconstruction** of the ghetto's maximum extent traced over
modern streets — treat it as orientation, not a surveyed line. Pin coordinates are placed at the
documented street addresses of each fragment, memorial, and marker.

Sources: Wikipedia (*Warsaw Ghetto boundary markers*; *Fragments of the ghetto walls in Warsaw*),
POLIN Museum of the History of Polish Jews, and the Polish Center for Holocaust Research
(getto.pl). Corrections to coordinates or additional fragments are welcome — edit the `PLACES`
and `GHETTO_OUTLINE` arrays in `index.html`.
