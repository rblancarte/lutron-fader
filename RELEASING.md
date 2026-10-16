# Releasing Lutron Fader

## Repository layout

```
lutron-fader/
├── custom_components/
│   └── lutron_fader/
│       ├── __init__.py        # finds Lutron lights, routes fade requests, migration
│       ├── config_flow.py     # one-click setup (single entry)
│       ├── const.py           # tracked platforms and timing constants
│       ├── manifest.json      # integration metadata and version
│       ├── sensor.py          # sensor.<light>_fade entities
│       ├── strings.json       # UI text (source)
│       ├── tracker.py         # per-light fade state machine (no HA imports)
│       └── translations/
│           └── en.json        # UI text shipped to Home Assistant
├── hacs.json                  # what HACS installs and the minimum HA version
├── info.md                    # short page shown in HACS
├── README.md                  # full documentation
└── LICENSE                    # Apache 2.0
```

HACS installs only `custom_components/lutron_fader/`. The Lovelace card ships separately from the [lutron-fader-card](https://github.com/rblancarte/lutron-fader-card) repository. Tests live in the [lutron-fader-dev](https://github.com/rblancarte/lutron-fader-dev) workspace.

## Release checklist

1. Tests pass in `lutron-fader-dev` (`python -m pytest`, Python 3.14 + `pytest-homeassistant-custom-component`)
2. Bump `version` in `custom_components/lutron_fader/manifest.json` (e.g. `2.0.0`)
3. If the code now needs a newer Home Assistant, raise `homeassistant` in `hacs.json`
4. Keep `translations/en.json` in sync with `strings.json`
5. Update `README.md` / `info.md` for anything user-visible
6. Commit, then tag and push:
   ```bash
   git tag -a v2.0.0 -m "Lutron Fader 2.0.0"
   git push origin main --tags
   ```
7. Create a GitHub release from the tag, with release notes
8. In `lutron-fader-dev`, commit the updated submodule pointer

## Publishing through HACS

### Custom repository (available immediately)
Users add it themselves: HACS → ⋮ → **Custom repositories** → `https://github.com/rblancarte/lutron-fader`, category **Integration**.

### HACS default repository
1. Fork [hacs/default](https://github.com/hacs/default)
2. Add `rblancarte/lutron-fader` to `integration` in alphabetical order
3. Open a pull request titled `Add Lutron Fader`

HACS checks before accepting:
- valid `hacs.json` and `manifest.json`
- at least one GitHub release
- brand assets (an icon) registered with [home-assistant/brands](https://github.com/home-assistant/brands)
- a README with installation instructions
- an integration that works and doesn't duplicate an existing one
