# HACS Submission Guide

This document outlines the steps to submit Lutron Fader to HACS (Home Assistant Community Store).

## Pre-Submission Checklist

### ✅ Required Files (All Present)

- [x] `hacs.json` - HACS configuration
- [x] `README.md` - Documentation
- [x] `LICENSE` - Apache 2.0 license
- [x] `custom_components/lutron_fader/manifest.json` - Integration metadata
- [x] `custom_components/lutron_fader/__init__.py` - Integration code
- [x] `.gitignore` - Git ignore rules

### ✅ Repository Requirements

- [x] Repository is public
- [x] Repository has at least one release (create one before submitting)
- [x] README has clear installation and usage instructions
- [x] Integration follows Home Assistant standards

### ✅ Integration Quality

- [x] Config flow (UI configuration) implemented
- [x] Services documented
- [x] Works with current Home Assistant version
- [x] No hardcoded credentials or secrets
- [x] Follows Home Assistant naming conventions

## Step-by-Step HACS Submission

### Step 1: Create a GitHub Release

1. **Tag your current version:**
   ```bash
   git tag -a v0.9.0 -m "Initial release"
   git push origin v0.9.0
   ```

2. **Create a release on GitHub:**
   - Go to https://github.com/rblancarte/lutron-fader/releases
   - Click "Create a new release"
   - Select tag: `v0.9.0`
   - Release title: `v0.9.0 - Initial Release`
   - Description:
     ```markdown
     ## Features
     - Extended fade time support for Lutron Caseta Pro lights (up to 2 hours)
     - Direct telnet control via Lutron Integration Protocol (LIP)
     - Config flow for easy UI setup
     - Auto-discovery of Lutron zones from Integration Report
     - Custom Lovelace card with fade controls
     - Service: `lutron_fader.fade_to` with extended fade time support

     ## Requirements
     - Home Assistant 2023.1+
     - Lutron Caseta Pro Smart Bridge (L-BDGPRO2-WH) or equivalent
     - Telnet enabled on Lutron hub

     ## Installation
     See [README.md](https://github.com/rblancarte/lutron-fader/blob/main/README.md) for installation and setup instructions.
     ```
   - Click "Publish release"

### Step 2: Verify Repository Structure

Your repository should look like this:

```
lutron_fader/
├── custom_components/
│   └── lutron_fader/
│       ├── __init__.py
│       ├── config_flow.py
│       ├── const.py
│       ├── light.py
│       ├── lutron_telnet.py
│       ├── manifest.json
│       ├── services.yaml
│       ├── strings.json
│       └── www/
│           ├── lutron-fader-card.js
│           └── README.md
├── examples/
│   ├── README.md
│   ├── example-dashboard.yaml
│   └── auto-lutron-dashboard.yaml
├── .gitignore
├── hacs.json
├── LICENSE
└── README.md
```

### Step 3: Submit to HACS

**Option A: Default Repository (Recommended for most users)**

1. **Fork the HACS default repository:**
   - Go to https://github.com/hacs/default
   - Click "Fork" in the top right

2. **Add your integration:**
   - In your fork, edit `custom_components.json`
   - Add your repository (alphabetically):
     ```json
     "rblancarte/lutron-fader"
     ```
   - The file should look like this (partial):
     ```json
     [
       "owner1/repo1",
       "owner2/repo2",
       "rblancarte/lutron-fader",
       "owner3/repo3"
     ]
     ```

3. **Create a Pull Request:**
   - Commit your changes
   - Go to https://github.com/hacs/default/pulls
   - Click "New Pull Request"
   - Title: `Add Lutron Fader`
   - Description:
     ```markdown
     ## Integration: Lutron Fader

     **Repository:** https://github.com/rblancarte/lutron-fader
     **Category:** Integration

     ### Description
     Adds extended fade time support (minutes to hours) for Lutron Caseta Pro lights via direct telnet control using the Lutron Integration Protocol.

     ### Features
     - Long fade times not limited by standard HA transitions
     - Config flow for easy setup
     - Auto-discovery from Integration Report
     - Custom Lovelace card included
     - Hardware-accelerated smooth fading

     ### Requirements
     - Lutron Caseta Pro, RadioRA 2 Select, or HomeWorks QS/QSX
     - Telnet/LIP support required

     ### Checklist
     - [x] Repository is public
     - [x] Has at least one release (v0.9.0)
     - [x] `hacs.json` present and valid
     - [x] `README.md` with installation instructions
     - [x] Follows Home Assistant standards
     - [x] Config flow implemented
     ```

4. **Wait for review:**
   - HACS maintainers will review your submission
   - They may ask for changes
   - Once approved, your integration will appear in HACS

**Option B: Custom Repository (Immediate availability)**

While waiting for default repository approval, users can add your integration as a custom repository:

1. In Home Assistant, go to HACS
2. Click the three dots menu (⋮) → Custom repositories
3. Add:
   - Repository: `https://github.com/rblancarte/lutron-fader`
   - Category: `Integration`
4. Click "Add"

Include this in your README for users who want early access.

### Step 4: Update README for HACS

Add installation via HACS to your README (already done):

```markdown
## Installation

### Via HACS
1. Open HACS
2. Go to Integrations
3. Search for "Lutron Fader"
4. Click Install
5. Restart Home Assistant

### Manual Installation
...
```

### Step 5: Post-Submission Maintenance

After approval:

1. **For updates:**
   - Update version in `manifest.json`
   - Create a new git tag and release
   - HACS will automatically detect the new version

2. **Version format:**
   - Use semantic versioning: `MAJOR.MINOR.PATCH`
   - Example: `0.1.0` → `0.2.0` → `1.0.0`

3. **Release notes:**
   - Always include release notes in GitHub releases
   - Users see these when updating

## HACS Validation Rules

Your integration must pass these checks:

- ✅ Valid `hacs.json` file
- ✅ Valid `manifest.json` file
- ✅ Repository has releases
- ✅ No brands validation errors
- ✅ Follows Home Assistant integration standards
- ✅ Code quality (no obvious issues)

## Testing Your Submission

Before submitting, test locally:

1. **Validate hacs.json:**
   ```bash
   # Install HACS locally and test validation
   python3 -m pip install homeassistant
   # Run validation (if available)
   ```

2. **Test as custom repository:**
   - Add your repo as a custom HACS repository
   - Install from HACS
   - Verify everything works
   - Remove and reinstall to test clean installation

3. **Check manifest.json:**
   - Ensure version is correct
   - Verify all required fields are present
   - Check dependencies are correct

## Common HACS Rejection Reasons

Avoid these common issues:

- ❌ No releases on repository
- ❌ Missing or invalid `hacs.json`
- ❌ Poor documentation in README
- ❌ Broken installation/setup
- ❌ Code doesn't follow HA standards
- ❌ Integration doesn't actually work
- ❌ Duplicate functionality of existing integration

## After Approval

Once approved:

1. **Add HACS badge to README:**
   ```markdown
   [![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration)
   ```

2. **Update installation instructions** to prioritize HACS

3. **Monitor issues** - Users will report problems via GitHub issues

4. **Release updates** - Create new releases for bug fixes and features

## Resources

- [HACS Documentation](https://hacs.xyz/)
- [HACS Integration Requirements](https://hacs.xyz/docs/publish/integration)
- [Home Assistant Developer Docs](https://developers.home-assistant.io/)
- [Integration Quality Scale](https://developers.home-assistant.io/docs/integration_quality_scale_index/)

## Quick Commands

```bash
# Create and push a tag
git tag -a v0.9.0 -m "Initial release"
git push origin v0.9.0

# Check what will be released
git diff v0.9.0..HEAD

# Create next version
git tag -a v0.2.0 -m "Add feature X"
git push origin v0.2.0
```

## Status Checklist

Before submitting to HACS:

- [ ] Created v0.9.0 release on GitHub
- [ ] Tested installation as custom repository
- [ ] README has clear installation instructions
- [ ] All features documented
- [ ] License file present (Apache 2.0)
- [ ] hacs.json validated
- [ ] manifest.json validated
- [ ] Forked hacs/default repository
- [ ] Added integration to custom_components.json
- [ ] Created pull request
- [ ] Added custom repository instructions to README
