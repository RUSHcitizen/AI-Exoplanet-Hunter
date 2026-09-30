# Exoplanet Hunter — frontend

Next.js (App Router) dashboard for the AI Exoplanet Hunter pipeline. See
the repository [README](../README.md) and
[`docs/architecture.md`](../docs/architecture.md) for the full project.

```bash
npm install
npm run dev         # http://localhost:3000 (expects the API at NEXT_PUBLIC_API_URL)
npm run lint
npm run typecheck
npm test
npm run build
```

`NEXT_PUBLIC_API_URL` is baked into the browser bundle at build time and
defaults to `http://localhost:8000`.

## Layout

- `src/app/` — routes: overview (`/`), the Pi Mensae observation
  (`/demo/pi-mensae`), 404 and error boundaries.
- `src/components/` — page sections and the chart layer
  (`LightCurveChart`, `PhaseFoldChart`, `chart/Axes`); `ui.tsx` holds the
  shared design-system primitives.
- `src/lib/api.ts` — typed API client mirroring the backend response models.
- `src/lib/lightcurve.ts` — pure display-side helpers (binning, robust
  scatter, ephemeris predictions, folding, ticks), unit tested in
  `tests/lightcurve.test.ts`.
- `src/lib/reference.ts` — published literature values. Anything from
  this file must be shown with the *Literature* tag, never as a pipeline
  result.
