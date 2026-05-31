![Version](https://img.shields.io/github/v/release/jrhubott/adaptive-cover-pro?style=for-the-badge)
![Tests](https://img.shields.io/github/actions/workflow/status/jrhubott/adaptive-cover-pro/tests.yml?branch=main&label=Tests&style=for-the-badge)
![Hassfest](https://img.shields.io/github/actions/workflow/status/jrhubott/adaptive-cover-pro/hassfest.yml?branch=main&label=Hassfest&style=for-the-badge)
![HACS](https://img.shields.io/github/actions/workflow/status/jrhubott/adaptive-cover-pro/hacs.yaml?branch=main&label=HACS&style=for-the-badge)
![Coverage](https://img.shields.io/codecov/c/github/jrhubott/adaptive-cover-pro?style=for-the-badge)

![Adaptive Cover Pro](https://raw.githubusercontent.com/jrhubott/adaptive-cover-pro/main/images/dark_logo.png)

# Adaptive Cover Pro

Sun-tracking cover automation with an inspectable decision pipeline, full venetian sequencing, glare zones, and a seasonal climate arbiter — for Home Assistant.

> Full documentation lives on the [Wiki](https://github.com/jrhubott/adaptive-cover-pro/wiki).

---

## What it does

- **Four cover types with full geometric modeling** — vertical blinds, horizontal awnings, tilt-only blinds, and venetian blinds; each uses real window and facade geometry, not rules of thumb.
- **Inspectable decision pipeline** — 10 handlers run in priority order (safety, weather, manual, climate, glare, solar) and each reports its reason. A `decision_trace` sensor shows exactly why the cover is at 45% — no black boxes.
- **Venetian blinds done properly** — dual-axis sequencer waits for the carriage to settle before sending tilt, handles back-rotation across a 45-second post-settle window, and pre-positions tilt on opening to eliminate flicker. Covers KNX, Shelly, and Somfy IO buses.
- **Climate mode with a full seasonal arbiter** — winter heating, winter insulation, summer cooling, and glare comfort each have independent logic; presence, lux, irradiance, and cloud cover are all suppression inputs.
- **Glare zones** — name the floor areas you want protected (TV, dining table); the cover deploys further than pure sun tracking when a protected zone would receive direct sun.
- **15 runtime services** — every parameter is scriptable from automations; no UI interaction needed to change mode, position limits, or overrides at runtime.

More detail: **[How It Decides](https://github.com/jrhubott/adaptive-cover-pro/wiki/How-It-Decides)** · **[Climate Mode](https://github.com/jrhubott/adaptive-cover-pro/wiki/Climate-Mode)** · **[Enhanced Geometric Accuracy](https://github.com/jrhubott/adaptive-cover-pro/wiki/Enhanced-Geometric-Accuracy)**

## Companion Lovelace card

Pair with the **[Adaptive Cover Pro Card](https://github.com/jrhubott/adaptive-cover-pro-card)**, a custom Lovelace card that shows the full pipeline decision trace, a polar sun compass, live cover positions, and inline override controls — all in one card. HACS-installable. See the **[Lovelace Card](https://github.com/jrhubott/adaptive-cover-pro/wiki/Lovelace-Card)** wiki page for setup and configuration.

<img src="https://raw.githubusercontent.com/jrhubott/adaptive-cover-pro-card/main/images/card-preview.png" alt="Adaptive Cover Pro Card preview" width="600">

---

## Quick install

**HACS (recommended):** In HACS, search **Adaptive Cover Pro**, download, restart Home Assistant, then add the integration.

**Manual:** Copy `custom_components/adaptive_cover_pro/` into `config/custom_components/`, restart Home Assistant, and add the integration.

Full steps: **[Installation](https://github.com/jrhubott/adaptive-cover-pro/wiki/Installation)** · **[First-Time Setup](https://github.com/jrhubott/adaptive-cover-pro/wiki/First-Time-Setup)**

## Documentation

|                            |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 🚀 **Getting started**     | [Installation](https://github.com/jrhubott/adaptive-cover-pro/wiki/Installation) · [First-Time Setup](https://github.com/jrhubott/adaptive-cover-pro/wiki/First-Time-Setup) · [Cover Types](https://github.com/jrhubott/adaptive-cover-pro/wiki/Cover-Types) · [Migrating from Adaptive Cover](https://github.com/jrhubott/adaptive-cover-pro/wiki/Migrating-from-Adaptive-Cover)                                                                                                              |
| 🧠 **How it works**        | [How It Decides](https://github.com/jrhubott/adaptive-cover-pro/wiki/How-It-Decides) · [Basic Mode](https://github.com/jrhubott/adaptive-cover-pro/wiki/Basic-Mode) · [Climate Mode](https://github.com/jrhubott/adaptive-cover-pro/wiki/Climate-Mode) · [Enhanced Geometric Accuracy](https://github.com/jrhubott/adaptive-cover-pro/wiki/Enhanced-Geometric-Accuracy)                                                                                                                        |
| 🎨 **Dashboard**           | [Lovelace Card](https://github.com/jrhubott/adaptive-cover-pro/wiki/Lovelace-Card) — install, configure, and use the companion card that visualizes the full pipeline                                                                                                                                                                                                                                                                                                                          |
| ⚙️ **Configuration**       | [Sun Tracking](https://github.com/jrhubott/adaptive-cover-pro/wiki/Configuration-Sun-Tracking) · [Glare Zones](https://github.com/jrhubott/adaptive-cover-pro/wiki/Configuration-Glare-Zones) · [Weather Safety](https://github.com/jrhubott/adaptive-cover-pro/wiki/Configuration-Weather-Safety) · [Climate](https://github.com/jrhubott/adaptive-cover-pro/wiki/Configuration-Climate) · [Summary Screen](https://github.com/jrhubott/adaptive-cover-pro/wiki/Configuration-Summary-Screen) |
| 🔌 **Entities & services** | [Entities](https://github.com/jrhubott/adaptive-cover-pro/wiki/Entities) · [Runtime Configuration Services](https://github.com/jrhubott/adaptive-cover-pro/wiki/Runtime-Configuration-Services) · [Position Verification](https://github.com/jrhubott/adaptive-cover-pro/wiki/Position-Verification) · [Somfy RTS (My Position)](https://github.com/jrhubott/adaptive-cover-pro/wiki/My-Position-Support-Somfy-RTS)                                                                            |
| 🛠️ **Operations**          | [Troubleshooting](https://github.com/jrhubott/adaptive-cover-pro/wiki/Troubleshooting) (incl. [stopping false manual overrides](https://github.com/jrhubott/adaptive-cover-pro/wiki/Troubleshooting#workaround--stop-unexpected-manual-overrides-entirely)) · [Known Limitations](https://github.com/jrhubott/adaptive-cover-pro/wiki/Known-Limitations)                                                                                                                                       |

## Support

If Adaptive Cover Pro has been useful, you can support the project:

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20me%20a%20coffee-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://www.buymeacoffee.com/jrhubott)
