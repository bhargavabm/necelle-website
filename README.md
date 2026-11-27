# Automated Nacelle Alignment System

Plain HTML, CSS, and JavaScript with no framework and no build step.

## Status

Complete:

- Favicon added
- Privacy policy page added
- Terms and conditions page added
- AI tag removed after project-wide search
- Contact form (mailto) added
- Key results replaced with measured simulation values
- Simulation layout rebuilt and bounding-box checks passed at 1440px and 375px

Still manual:

- Visual review of `screenshots\rebuild-1440.png` and `screenshots\rebuild-375.png`
- Custom domain connected in Vercel
- Deployed to Vercel and checked on a phone and a laptop
- Favicon confirmed in the browser tab on the live site
- Guided tour voice narration verified with Voice on
- Placeholders confirmed (team details, contact, last updated date)

## Run locally

Serve this folder with any static file server. The checked command is:

```text
python -m http.server 8000
```

Open http://localhost:8000.

## Files

- `index.html` - Home page
- `simulation.html` - Simulation page
- `about.html` - About page
- `privacy.html` - Privacy policy
- `terms.html` - Terms and conditions
- `assets/css/styles.css` - design tokens, shared components, and layout
- `assets/js/main.js` - navigation, Privacy/Terms links, and contact form
- `assets/js/simulation.js` - physics, controller, 3D scene, section view, charts, and guided tour
- `assets/data/results.json` - measured simulation results
- `assets/img/` - favicon

## Deploy

1. Import the repository in Vercel.
2. Use no build command.
3. Set the output directory to the project root.

## Development checks

- `scripts/` - programmatic UI, overlap, and layout checks
- `screenshots/` - screenshots from layout checks
- Backup folders: `backup-before-fix/`, `backup-before-fix2/`, `backup-before-rebuild/`
