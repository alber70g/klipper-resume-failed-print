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
- `extract_temperatures()` / `extract_temperatures_at()` - Temps from the start section, or (preferred) the last M104/M140 before the cut — avoids using the hotter first-layer temperature
- `find_layer_changes_with_z()` - Primary layer detection using slicer `;Z:` comment markers (OrcaSlicer, PrusaSlicer, Cura)
- `split_into_segments()` / `select_segment()` - Sequential ("by object") print support: splits layers at Z resets; `--object N` picks the failed object when the target height is ambiguous
- `extract_state_lines()` - Carries EXCLUDE_OBJECT_DEFINE, SKEW_PROFILE LOAD, and M900 lines from the discarded start section into the output
- `find_resume_layer()` - Determines the correct line to resume from based on target height minus one layer height
- `create_resume_header()` - Generates the no-pause resume header (temps → SET_KINEMATIC_POSITION → state lines)
- `remove_homing_and_start()` - Strips redundant start commands from the extracted G-code portion

**Generated Resume File Workflow (no-pause):**

The user positions the nozzle BEFORE starting the file (fake Z via
`SET_KINEMATIC_POSITION Z=200`, home XY only, preheat, jog to ~1 layer height
above the print top). The file then:
1. Sets temperatures (M140/M104/M190/M109 — instant if preheated)
2. Declares the jogged position as the resume height (`SET_KINEMATIC_POSITION Z=<height>`)
3. Resets extruder (G92 E0, M83, G90) and replays carried-over state lines
4. Continues with layer content — the first layer lands flush on the top surface (cut is one layer below the declared height; the jog gap cancels it)

**No PAUSE is emitted**: park-and-restore RESUME macros (Mainsail
`RESTORE_GCODE_STATE MOVE=1`) return to the pre-jog position, failing with
`Move out of range` or resuming mid-air.

## Key Implementation Details

- Layer detection prioritizes slicer `;Z:` markers over G-code Z moves (travel moves can have elevated Z that doesn't represent layer height)
- Resume layer is selected as first layer where Z >= (target_height - layer_height)
- Temperature detection searches first 500 lines for `PRINT_START BED=X HOTEND=Y` or standard M-codes
- Supports Klipper-specific commands (SET_KINEMATIC_POSITION, EXCLUDE_OBJECT)

## Supporting Files

- `resume_print_macros.cfg` - Klipper macro definitions for alternative workflow
- `example_config.cfg` - Sample Klipper printer.cfg additions
- `test-files/` - Sample G-code files for testing
