# Automated Nacelle Alignment System

## Live site

https://necelle-website.vercel.app/

Replace this URL with the custom domain once it is connected.

Custom domain: pending

## About

A wind turbine nacelle turns on its yaw bearing to face the wind. This project models the control loop, the PD controller with deadband and rate limit, and shows the result in a live browser simulation with 3D, Section, and Output views.

## What the site contains

- Home: `index.html`
- Simulation: `simulation.html`
- Architecture on the About page: `about.html#architecture`
- About: `about.html`
- Privacy policy: `privacy.html`
- Terms and conditions dialog: in the footer on Home, About, and Privacy policy

## Measured results

The Stable preset was run 10 times and these are the median results. Settling time is 27.59 s, with a range of 19.74 s to 38.52 s. Mean absolute error after settling is 2.21 degrees, with a range of 1.41 to 3.09 degrees. Steady power is 99.83 percent, with a range of 99.70 to 99.92 percent. The wind model is random, so results vary between runs.

## Run locally

```text
python -m http.server 8000 --bind 127.0.0.1
```

Open http://127.0.0.1:8000. The 3D view needs an internet connection because Three.js and Chart.js load from cdnjs.cloudflare.com.

## Deploy

The site is static. Import the repository into Vercel with no build command and the project root as the output directory. `vercel.json` sets the security headers.

## Repository layout

- `index.html`
- `simulation.html`
- `about.html`
- `privacy.html`
- `assets/css/`
- `assets/js/`
- `assets/img/`
- `assets/fonts/`
- `assets/data/`
- `vercel.json`
- `.gitignore`
- `.vercelignore`

## Licence and contact

The content is a student project by Bhargava B M and Ashish K S, UVCE Bengaluru. Contact: bhargavabm2007@gmail.com.

## Development checks

`scripts/` contains local UI, overlap, and layout checks. `screenshots/` contains images from those checks. These are development checks and are not deployed.
