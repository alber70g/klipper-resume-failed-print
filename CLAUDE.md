# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Klipper Print Resume Tool - A Python CLI tool that processes G-code files to create resume files for failed 3D prints. The tool extracts the portion of G-code from a specified Z-height and prepends an automated workflow that heats the printer, homes X/Y, pauses for manual nozzle positioning, then continues printing.

## Commands

```bash
# Run the tool (using uv - recommended)
uv run python resume_print.py <gcode_file> --height <z_height> --layer-height <layer_height>

# Example with all options
uv run python resume_print.py print.gcode --height 20.1 --layer-height 0.3 --output resumed.gcode --bed-temp 85 --hotend-temp 230

# Verify syntax
uv run python -m py_compile resume_print.py
```

## Architecture

The tool is a single-file Python script (`resume_print.py`) with one main class:

**PrintResumeTool** - Handles the complete workflow:
- `extract_temperatures()` - Parses original G-code for bed/hotend temps from `PRINT_START` macros or M-codes
- `find_layer_changes_with_z()` - Primary layer detection using slicer `;Z:` comment markers (OrcaSlicer, PrusaSlicer, Cura)
- `find_resume_layer()` - Determines the correct line to resume from based on target height minus one layer height
- `create_resume_header()` - Generates the automated resume sequence (heat → home X/Y → PAUSE → G92 Z)
- `remove_homing_and_start()` - Strips redundant start commands from the extracted G-code portion

**Generated Resume File Workflow:**
1. Sets temperatures (M140/M104/M190/M109)
2. Homes X and Y (G28 X Y)
3. Issues PAUSE command for manual Z positioning
4. After RESUME: sets Z position (G92 Z), resets extruder (G92 E0)
5. Continues with layer content

## Key Implementation Details

- Layer detection prioritizes slicer `;Z:` markers over G-code Z moves (travel moves can have elevated Z that doesn't represent layer height)
- Resume layer is selected as first layer where Z >= (target_height - layer_height)
- Temperature detection searches first 500 lines for `PRINT_START BED=X HOTEND=Y` or standard M-codes
- Supports Klipper-specific commands (PAUSE, EXCLUDE_OBJECT)

## Supporting Files

- `resume_print_macros.cfg` - Klipper macro definitions for alternative workflow
- `example_config.cfg` - Sample Klipper printer.cfg additions
- `test-files/` - Sample G-code files for testing
