# HACS Quick Start

Quick steps to get your integration into HACS.

## 1. Commit Everything

```bash
cd /Users/ronb/dev/Home_Assistant/lutron_fader

# Add all new files
git add hacs.json
git add examples/
git add HACS_SUBMISSION.md
git add DISTRIBUTION.md
git add custom_components/lutron_fader/www/

# Commit
git commit -m "Prepare for HACS submission

- Add hacs.json configuration
- Bundle custom Lovelace card
- Add dashboard examples
- Update documentation"

# Push to GitHub
git push origin main
```

## 2. Create v0.9.0 Release

```bash
# Tag the release
git tag -a v0.9.0 -m "Initial HACS release"
git push origin v0.9.0
```

Then on GitHub (https://github.com/rblancarte/lutron-fader):
1. Go to "Releases"
2. Click "Draft a new release"
3. Choose tag: `v0.9.0`
4. Title: `v0.9.0 - Initial Release`
5. Description: See HACS_SUBMISSION.md for template
6. Click "Publish release"

## 3. Submit to HACS

### For Immediate Use (Custom Repository)

Users can add your integration right now:

**Tell users to do this:**
1. Open HACS in Home Assistant
2. Click ⋮ → Custom repositories
3. Add: `https://github.com/rblancarte/lutron-fader`
4. Category: Integration
5. Click "Add"
6. Search for "Lutron Fader" in HACS
7. Install

### For HACS Default (Official)

1. Fork https://github.com/hacs/default
2. Edit `custom_components.json` in your fork
3. Add your repo alphabetically: `"rblancarte/lutron-fader"`
4. Commit and create a Pull Request
5. Wait for HACS team approval

## 4. Update README

Add this to the Installation section:

```markdown
### Via HACS

**Recommended:** Install via HACS for automatic updates.

1. Open HACS → Integrations
2. Click ⋮ → Custom repositories
3. Add repository: `https://github.com/rblancarte/lutron-fader`
4. Category: Integration
5. Search for "Lutron Fader"
6. Click Install
7. Restart Home Assistant

Once added to HACS default repository, you can skip step 2-4.
```

## 5. Test

Before announcing:

1. Install via HACS custom repository on a test system
2. Verify all features work
3. Test the custom card
4. Check all services
5. Test auto-discovery

## 6. Announce

Once everything works:

1. Update Home Assistant Community forum
2. Post on r/homeassistant
3. Share on Home Assistant Discord
4. Update your GitHub repo description

## Files Checklist

- [x] `hacs.json` - HACS config
- [x] `README.md` - Documentation
- [x] `LICENSE` - Apache 2.0
- [x] `custom_components/lutron_fader/manifest.json` - Metadata
- [x] `custom_components/lutron_fader/www/lutron-fader-card.js` - Custom card
- [x] `examples/` - Dashboard examples
- [ ] GitHub Release v0.9.0
- [ ] HACS submission PR
- [ ] Testing on clean install

## Quick Test Commands

```bash
# Verify structure
ls -R custom_components/lutron_fader/

# Check JSON files are valid
python3 -m json.tool hacs.json
python3 -m json.tool custom_components/lutron_fader/manifest.json

# Verify no secrets committed
git log --all --full-history -- "*secret*" "*password*" "*.env"

# Check file sizes (should all be reasonable)
find custom_components/lutron_fader -type f -size +100k
```

## Ready to Ship!

Your integration is ready for HACS when:
- ✅ All files committed and pushed
- ✅ Release created on GitHub
- ✅ Tested via custom repository
- ✅ Documentation complete
- ✅ No errors in Home Assistant logs
- ✅ Custom card works
- ✅ All services documented

## Next Steps After HACS Approval

1. Add HACS badge to README
2. Monitor GitHub issues
3. Plan v0.2.0 features
4. Consider Home Assistant core integration (future)
