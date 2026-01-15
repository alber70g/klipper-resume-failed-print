# Klipper Print Resume Tool

A comprehensive tool for resuming failed or crashed 3D prints from a specific Z-height in Klipper firmware.

## Features

- **Python Script**: Automated G-code processing to create resume files
- **Klipper Macros**: Direct integration with Klipper for easy resuming
- **Multi-Slicer Support**: Works with Cura, PrusaSlicer, and other slicers
- **Smart Layer Detection**: Automatically finds the correct resume layer
- **Safety Features**: Built-in checks and manual positioning steps

## Contents

- `resume_print.py` - Python script for processing G-code files
- `resume_print_macros.cfg` - Klipper macro definitions
- `example_config.cfg` - Example Klipper configuration

## Installation

### Option 1: Python Script Only

1. Clone or download this repository
2. Install `uv` (recommended for Python management):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
3. Make the script executable:
   ```bash
   chmod +x resume_print.py
   ```
4. Run the script (see Usage section)

**Note**: You can also use `python3` directly if you prefer, but `uv` provides better dependency management.

### Option 2: Klipper Macros

1. Copy `resume_print_macros.cfg` to your Klipper config directory:
   ```bash
   cp resume_print_macros.cfg ~/printer_data/config/
   ```

2. Add to your `printer.cfg`:
   ```
   [include resume_print_macros.cfg]
   ```

3. Configure `[safe_z_home]` in your `printer.cfg` if not already set:
   ```
   [safe_z_home]
   home_xy_position: 0,30  # Adjust for your printer
   z_hop: 10
   ```

4. Restart Klipper:
   ```
   FIRMWARE_RESTART
   ```

## Usage

### Method 1: Python Script

#### Basic Usage

Using `uv` (recommended):
```bash
uv run python resume_print.py your_print.gcode --height 15.2
```

Or using `python3` directly:
```bash
python3 resume_print.py your_print.gcode --height 15.2
```

#### With Options

Using `uv`:
```bash
uv run python resume_print.py your_print.gcode \
    --height 15.2 \
    --layer-height 0.2 \
    --output resumed_print.gcode \
    --safe-z-home-x 0 \
    --safe-z-home-y 30
```

Or using `python3`:
```bash
python3 resume_print.py your_print.gcode \
    --height 15.2 \
    --layer-height 0.2 \
    --output resumed_print.gcode \
    --safe-z-home-x 0 \
    --safe-z-home-y 30
```

#### Command Line Options
- `gcode_file` - Original G-code file to process (required)
- `--height, -z` - Z-height to resume from in mm (required)
- `--output, -o` - Output filename (default: `original_resumed.gcode`)
- `--layer-height, -lh` - Layer height in mm (default: 0.2)
- `--safe-z-home-x` - X coordinate for safe Z homing (default: 0)
- `--safe-z-home-y` - Y coordinate for safe Z homing (default: 30)

#### Example Output
```
Processing: benchy.gcode
Resume height: 15.20mm
Layer height: 0.20mm
Resuming from line 4523

✓ Created resume file: benchy_resumed.gcode

=== NEXT STEPS ===
1. Heat bed to print temperature
2. Heat nozzle to print temperature
3. Home XY: G28 X Y
4. Home Z at safe position: G28 Z (or use safe_z_home)
5. Manually move nozzle to resume height
6. Start print: benchy_resumed.gcode

⚠️  IMPORTANT: Monitor first few layers carefully!
```

### Method 2: Klipper Macros

#### Available Macros

**PREPARE_RESUME** - Heat and prepare the printer
```gcode
PREPARE_RESUME Z=15.2 BED_TEMP=60 EXTRUDER_TEMP=200
```

**MANUAL_POSITION_Z** - Disable steppers for manual positioning
```gcode
MANUAL_POSITION_Z Z=15.2
```

**SET_Z_POSITION** - Set current position after manual positioning
```gcode
SET_Z_POSITION Z=15.2
```

**CHECK_RESUME_HEIGHT** - Test move to resume height
```gcode
CHECK_RESUME_HEIGHT Z=15.2
```

**RESUME_PRINT** - Complete resume workflow (requires modified G-code)
```gcode
RESUME_PRINT Z=15.2 FILENAME=benchy_resumed.gcode BED_TEMP=60 EXTRUDER_TEMP=200
```

## Step-by-Step Resume Process

### Preparation

1. **Measure the Failed Print**
   - Use calipers or a ruler to measure the height where printing stopped
   - Measure from the bed to the top of the successful print
   - Round down to the nearest layer boundary (e.g., if you measure 15.35mm and layer height is 0.2mm, use 15.2mm)

2. **Clean the Print Surface**
   - Remove any strings or blobs from the failed area
   - Ensure the print is still firmly attached to the bed
   - Check that no warping has occurred

### Using Python Script Method

1. **Process the G-code**
   ```bash
   python3 resume_print.py original.gcode --height 15.2
   ```

2. **Heat the Printer**
   - Set bed temperature: `M140 S60`
   - Set nozzle temperature: `M104 S200`
   - Wait for temperatures: `M190 S60` and `M109 S200`

3. **Home XY**
   ```gcode
   G28 X Y
   ```

4. **Home Z at Safe Location**
   ```gcode
   G90
   G0 X0 Y30 F6000
   G28 Z
   ```

5. **Position Nozzle at Resume Height**
   - Move nozzle over the print area
   - Slowly lower Z until you have ~0.3mm clearance above the print
   - Use baby stepping or manual adjustment
   - The nozzle should be just above the print surface (paper thickness)

6. **Start the Resume G-code**
   - Load `original_resumed.gcode` in your print interface
   - Start the print
   - **Monitor the first few layers closely!**

### Using Klipper Macros Method

1. **Process G-code First**
   ```bash
   # Using uv (recommended)
   uv run python resume_print.py original.gcode --height 15.2

   # Or using python3
   python3 resume_print.py original.gcode --height 15.2
   ```

2. **Run Complete Resume Workflow**
   ```gcode
   PREPARE_RESUME Z=15.2 BED_TEMP=60 EXTRUDER_TEMP=200
   ```
   (This heats the printer)

3. **Manual Positioning**
   ```gcode
   MANUAL_POSITION_Z Z=15.2
   ```
   - Manually position the nozzle with ~0.3mm clearance

4. **Set Z Position**
   ```gcode
   SET_Z_POSITION Z=15.2
   ```

5. **Start Print**
   - Load the resumed G-code file
   - Start printing
   - **Monitor carefully!**

## How It Works

### G-code Processing

The tool performs the following operations:

1. **Layer Detection**
   - Searches for layer change markers from popular slicers
   - Identifies Z-height changes throughout the file
   - Finds the optimal resume point based on target height

2. **Header Removal**
   - Strips initial homing commands (`G28`)
   - Removes temperature setting commands
   - Removes print start sequences
   - Preserves actual print moves

3. **Resume Header Addition**
   - Adds manual positioning instructions as comments
   - Inserts `G92 Z<height>` to set current position
   - Resets extruder position with `G92 E0`
   - Sets up proper modes (absolute positioning, relative extrusion)

4. **Content Preservation**
   - Keeps all moves from resume point onward
   - Maintains fan settings and temperatures from original
   - Preserves acceleration and jerk settings

### Safety Features

- Manual nozzle positioning prevents crashes
- Comments in resume file guide the process
- No automatic homing that could damage the print
- Position validation before resuming
- Clear step-by-step instructions

## Troubleshooting

### Print Doesn't Stick at Resume Point

**Symptoms**: First resumed layer doesn't adhere properly

**Solutions**:
- Ensure nozzle is at correct height (~0.3mm clearance)
- Clean the print surface around the resume area
- Increase bed temperature by 5-10°C
- Consider using a thin layer of glue stick at the resume area

### Extruder Skipping or Grinding

**Symptoms**: Clicking sound, under-extrusion after resume

**Solutions**:
- Check that extruder temperature is correct
- Verify filament isn't tangled
- Reload filament if it was removed
- Run a small purge line before resuming

### Z-Height Mismatch

**Symptoms**: Nozzle too high or too low after resume

**Solutions**:
- Re-measure the print height carefully
- Account for layer height in calculations
- Use `CHECK_RESUME_HEIGHT` macro to verify positioning
- Adjust with baby stepping if needed

### Layer Adhesion Issues

**Symptoms**: Weak bonds between layers at resume point

**Solutions**:
- Ensure nozzle and bed are at proper temperature
- Consider increasing temperature by 5-10°C for first few layers
- Slow down feed rate for first resumed layers
- Monitor closely and adjust baby stepping if needed

### G-code Processing Errors

**Symptoms**: Script fails or creates invalid G-code

**Solutions**:
- Verify input file is valid G-code
- Check file permissions
- Ensure enough disk space
- Try with `--layer-height` matching your slicer settings

## Tips and Best Practices

1. **Always Measure Carefully**
   - Use calipers for accurate height measurement
   - Round down to nearest layer boundary
   - Double-check your calculations

2. **Test First**
   - Consider doing a test resume on a sacrificial print
   - Use `CHECK_RESUME_HEIGHT` to verify positioning
   - Start with conservative heights (lower is safer)

3. **Monitor Closely**
   - Watch the first 5-10 resumed layers
   - Be ready to pause or stop if issues occur
   - Adjust baby stepping if needed

4. **Temperature Management**
   - Use the same temperatures as original print
   - Consider 5-10°C higher for better layer adhesion
   - Ensure bed stays heated throughout process

5. **Document Settings**
   - Note the resume height
   - Record any adjustments made
   - Keep track of successful resume attempts

6. **Preventive Measures**
   - Use UPS for power protection
   - Enable power loss recovery in Klipper
   - Save G-code files for easy reprocessing

## Advanced Configuration

### Custom Safe Z Home Position

Edit `resume_print_macros.cfg` to adjust the safe homing position:

```
[gcode_macro SAFE_Z_HOME]
gcode:
    G90
    G0 X150 Y150 F6000  # Center of bed for 300x300 printer
    G28 Z
```

### Multiple Printer Support

Create printer-specific configurations:

```
[include resume_print_macros.cfg]

[gcode_macro SAFE_Z_HOME]
gcode:
    {% if printer.toolhead.extruder == "extruder" %}
        G0 X0 Y30 F6000  # Printer 1
    {% elif printer.toolhead.extruder == "extruder1" %}
        G0 X50 Y50 F6000  # Printer 2 with IDEX
    {% endif %}
    G28 Z
```

### Custom Resume Start Sequence

Add a custom start macro:

```
[gcode_macro CUSTOM_RESUME_START]
gcode:
    ; Your custom start sequence
    M106 S255           ; Fan on full
    G4 P2000           ; Wait 2 seconds
    M106 S0            ; Fan off
    ; Continue with resume...
```

## Contributing

Contributions are welcome! Please feel free to submit issues, feature requests, or pull requests.

## License

This project is provided as-is for the 3D printing community. Feel free to use, modify, and distribute.

## Disclaimer

**Use at your own risk!** Always monitor your printer when resuming prints. The authors are not responsible for any damage to your printer or failed prints.

## Support

For issues, questions, or suggestions, please open an issue on the project repository.

## Credits

Developed for the Klipper community to help salvage failed prints and reduce waste.

---

**Happy Printing!** 🎉
