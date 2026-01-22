# Distribution Guide

## Repository Structure

```
lutron_fader/
├── custom_components/
│   └── lutron_fader/
│       ├── __init__.py           # Main integration code
│       ├── config_flow.py        # UI configuration
│       ├── const.py              # Constants
│       ├── light.py              # Light platform
│       ├── lutron_telnet.py      # Telnet connection handler
│       ├── manifest.json         # Integration metadata
│       ├── services.yaml         # Service definitions
│       ├── strings.json          # UI strings
│       └── www/                  # Frontend resources (bundled)
│           ├── lutron-fader-card.js  # Custom Lovelace card
│           └── README.md         # Card documentation
├── www/                          # Development/examples (not distributed)
│   ├── lutron-fader-card.js      # Card source
│   ├── README.md                 # Card docs
│   ├── example-dashboard.yaml    # Dashboard examples
│   └── auto-lutron-dashboard.yaml
├── README.md                     # Main documentation
├── LICENSE                       # Apache 2.0 license
└── .gitignore
```

## What Gets Distributed

When users install via HACS or manual installation, they get:

1. **The integration** (`custom_components/lutron_fader/`)
   - All Python files
   - Configuration files (manifest.json, services.yaml, strings.json)
   - **The bundled custom card** (`www/lutron-fader-card.js`)

2. **Documentation**
   - README.md (main docs)
   - LICENSE

## How the Card is Distributed

### Option 1: Bundled with Integration (Current Implementation)

✅ **This is what we implemented**

The card is included in `custom_components/lutron_fader/www/` and automatically available after installing the integration.

**Advantages:**
- Single installation step
- Card is always available with the integration
- No need for separate HACS frontend installation
- Users just need to add the resource URL

**Users install like this:**
1. Install integration (via HACS or manually)
2. Add resource: `/lutron_fader_static/lutron-fader-card.js`
3. Use the card

### Option 2: Separate HACS Frontend Component (Future)

For HACS, you could also publish the card as a separate "Frontend" component.

**Advantages:**
- Shows up in HACS frontend section
- Can be updated independently
- Better visibility for users looking for cards

**Would require:**
- Separate repository or HACS configuration
- Users install integration + frontend separately

## For HACS Distribution

### Integration Submission

1. Ensure `hacs.json` exists (create if needed):
```json
{
  "name": "Lutron Fader",
  "render_readme": true,
  "domains": ["light"],
  "homeassistant": "2023.1.0"
}
```

2. Submit to HACS:
   - Fork https://github.com/hacs/default
   - Add your repo to `custom_components.json`
   - Create PR

### Frontend Submission (Optional)

If you want the card listed separately in HACS Frontend:

1. Add to `hacs.json`:
```json
{
  "name": "Lutron Fader Card",
  "content_in_root": false,
  "filename": "lutron-fader-card.js",
  "render_readme": true
}
```

2. Submit to HACS Frontend section

## Git Workflow

The `.gitignore` is configured to:
- ✅ Include `custom_components/lutron_fader/www/` (bundled card)
- ❌ Exclude `/www/` at root (development files)

This means:
- Your bundled card IS committed to git
- Example files and dev copies are NOT committed

## Version Management

Update version in:
1. `custom_components/lutron_fader/manifest.json` - Integration version
2. `custom_components/lutron_fader/www/lutron-fader-card.js` - Card version in console.info()

## Release Checklist

Before creating a release:

- [ ] Update version in `manifest.json`
- [ ] Update version in card's `console.info()` message
- [ ] Update CHANGELOG (if you have one)
- [ ] Test installation from scratch
- [ ] Test card resource URL works
- [ ] Create GitHub release with tag
- [ ] Submit to HACS (if not already listed)

## User Installation Instructions

### Via HACS (when available)
1. Open HACS → Integrations
2. Search "Lutron Fader"
3. Install
4. Restart Home Assistant
5. Add integration via UI
6. Add card resource: `/lutron_fader_static/lutron-fader-card.js`

### Manual Installation
1. Download latest release
2. Extract to `config/custom_components/lutron_fader/`
3. Restart Home Assistant
4. Add integration via UI
5. Add card resource: `/lutron_fader_static/lutron-fader-card.js`

## Current Distribution Status

✅ **Ready for distribution**
- Integration code complete
- Custom card bundled
- Frontend resources auto-registered
- Documentation complete
- Examples included

📋 **Next steps:**
- Create GitHub release
- Submit to HACS
- Test installation on fresh system
