# Quick Start Guide

Get your failed print resumed in 5 minutes!

## For First-Time Users

### Step 1: Choose Your Method

**Method A: Python Script** (Recommended for all users)
- Works offline
- No Klipper config changes needed
- Most flexible

**Method B: Klipper Macros** (Advanced users)
- Integrated with Klipper
- Faster workflow after setup
- Requires config changes

## Method A: Python Script (Simple)

### 1. Measure Your Print
```bash
# Use calipers to measure the height where printing stopped
# Example: 15.35mm → round down to 15.2mm (for 0.2mm layers)
```

### 2. Process the G-code
```bash
# Using uv (recommended)
uv run python resume_print.py your_original_file.gcode --height 15.2

# Or using python3
python3 resume_print.py your_original_file.gcode --height 15.2
```

This creates: `your_original_file_resumed.gcode`

### 3. Prepare Your Printer

**Heat it up:**
```gcode
M140 S60    # Set bed temp (adjust for your material)
M104 S200   # Set nozzle temp (adjust for your material)
M190 S60    # Wait for bed
M109 S200   # Wait for nozzle
```

**Home XY:**
```gcode
G28 X Y
```

**Home Z safely:**
```gcode
G90
G0 X0 Y30 F6000    # Move to safe spot (adjust for your printer)
G28 Z              # Home Z
```

### 4. Position the Nozzle

1. Manually move the nozzle to just above your print
2. Lower Z slowly until there's about 0.3mm clearance
3. Use a piece of paper as a feeler gauge if needed

### 5. Start the Resume File

Load `your_original_file_resumed.gcode` and start printing!

**⚠️ WATCH THE FIRST FEW LAYERS CAREFULLY!**

---

## Method B: Klipper Macros (Advanced)

### 1. Install the Macros

```bash
# Copy the macro file to your Klipper config
cp resume_print_macros.cfg ~/printer_data/config/

# Add to printer.cfg:
# [include resume_print_macros.cfg]

# Restart Klipper
```

### 2. Process G-code
```bash
# Using uv (recommended)
uv run python resume_print.py original.gcode --height 15.2

# Or using python3
python3 resume_print.py original.gcode --height 15.2
```

### 3. Use the Macros

In your Klipper console:

```gcode
# Heat and prepare
PREPARE_RESUME Z=15.2 BED_TEMP=60 EXTRUDER_TEMP=200

# Disable steppers for manual positioning
MANUAL_POSITION_Z Z=15.2

# (Manually position the nozzle)

# Set the position
SET_Z_POSITION Z=15.2

# Start the resumed G-code file
```

---

## Common Issues

### Issue: "Nozzle too high/low"
**Solution:** Re-measure carefully, round to nearest layer boundary

### Issue: "First layer doesn't stick"
**Solution:**
- Increase bed temp by 5-10°C
- Clean the area around resume point
- Ensure proper nozzle height (0.3mm clearance)

### Issue: "Extruder clicking"
**Solution:**
- Check filament isn't tangled
- Verify correct temperature
- Reload filament if it was removed

---

## Tips for Success

1. **Always round down** to nearest layer boundary
2. **Clean the print** area before resuming
3. **Monitor closely** for the first 5-10 layers
4. **Keep original files** in case you need to reprocess
5. **Test on sacrificial prints** first

---

## Example Session

```bash
# 1. Measure: 15.35mm measured → use 15.2mm (0.2mm layers)

# 2. Process (using uv)
uv run python resume_print.py benchy.gcode --height 15.2
# Or: python3 resume_print.py benchy.gcode --height 15.2

# 3. Heat (via terminal or LCD)
M140 S60
M190 S60
M104 S200
M109 S200

# 4. Home
G28 X Y
G90
G0 X0 Y30 F6000
G28 Z

# 5. Position manually (use LCD or paper test)

# 6. Start benchy_resumed.gcode

# 7. Watch carefully!
```

---

## Need Help?

- Check the full README.md for detailed instructions
- See example_config.cfg for Klipper setup examples
- Open an issue if you encounter problems

**Happy printing!** 🎉
