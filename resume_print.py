#!/usr/bin/env python3
"""
Klipper Print Resume Tool
Resumes failed/crashed prints from a specific Z-height
"""

import os
import re
import sys
import argparse
import tempfile
from pathlib import Path

class PrintResumeTool:
    def __init__(self):
        self.layer_height = 0.2  # Default, adjust as needed
        self.resume_height = None
        self.gcode_file = None

    def parse_arguments(self):
        parser = argparse.ArgumentParser(
            description='Resume failed print from specific Z-height'
        )
        parser.add_argument(
            'gcode_file',
            help='Original G-code file to modify'
        )
        parser.add_argument(
            '--height', '-z',
            type=float,
            required=True,
            help='Z-height to resume from (in mm)'
        )
        parser.add_argument(
            '--output', '-o',
            help='Output file name (default: original_filename_resumed.gcode)'
        )
        parser.add_argument(
            '--layer-height', '-lh',
            type=float,
            default=0.2,
            help='Layer height in mm (default: 0.2)'
        )
        parser.add_argument(
            '--safe-z-home-x',
            type=float,
            default=0,
            help='X position for safe Z homing'
        )
        parser.add_argument(
            '--safe-z-home-y',
            type=float,
            default=30,
            help='Y position for safe Z homing'
        )

        args = parser.parse_args()
        self.gcode_file = args.gcode_file
        self.resume_height = args.height
        self.layer_height = args.layer_height

        if args.output:
            self.output_file = args.output
        else:
            orig_path = Path(args.gcode_file)
            self.output_file = str(orig_path.with_name(
                f"{orig_path.stem}_resumed{orig_path.suffix}"
            ))

        self.safe_z_home_x = args.safe_z_home_x
        self.safe_z_home_y = args.safe_z_home_y

    def find_layer_changes(self, content):
        """Find all layer change markers in G-code"""
        layer_patterns = [
            r';LAYER_CHANGE',            # Cura
            r';LAYER:(\d+)',             # Cura/Slic3r
            r';BEFORE_LAYER_CHANGE',     # Cura
            r';AFTER_LAYER_CHANGE',      # Cura
            r'^; layer (\d+)',           # PrusaSlicer
            r'^;MESH:NONMESH',           # End of mesh
        ]

        layer_lines = []
        for i, line in enumerate(content):
            for pattern in layer_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    layer_lines.append(i)
                    break
        return layer_lines

    def find_z_moves(self, content):
        """Extract Z positions and their line numbers"""
        z_moves = []
        z_pattern = r'G[01].*Z([-\d.]+)'

        for i, line in enumerate(content):
            # Skip comments for pattern matching
            clean_line = line.split(';')[0].strip()
            match = re.search(z_pattern, clean_line)
            if match:
                try:
                    z_pos = float(match.group(1))
                    z_moves.append((i, z_pos))
                except ValueError:
                    continue

        return z_moves

    def find_resume_layer(self, content, target_height):
        """Find the best layer to resume from"""
        layer_indices = self.find_layer_changes(content)
        z_moves = self.find_z_moves(content)

        if not layer_indices:
            print("Warning: No layer change markers found!")
            return self.find_resume_by_z_only(content, target_height)

        # Find the layer where Z reaches or exceeds target height
        resume_layer_idx = None

        for i, layer_line in enumerate(layer_indices):
            # Find Z position after this layer change
            for z_line, z_pos in z_moves:
                if z_line > layer_line:
                    # Found the first Z move after layer change
                    if z_pos >= target_height - self.layer_height:
                        resume_layer_idx = i
                        break
            if resume_layer_idx is not None:
                break

        if resume_layer_idx is None:
            # If we didn't find it, use the last layer
            resume_layer_idx = len(layer_indices) - 1

        return layer_indices[resume_layer_idx]

    def find_resume_by_z_only(self, content, target_height):
        """Fallback method if no layer markers found"""
        z_moves = self.find_z_moves(content)

        for i, (line_num, z_pos) in enumerate(z_moves):
            if z_pos >= target_height - self.layer_height:
                # Go back to find a good starting point
                for j in range(max(0, i-10), i):
                    if content[z_moves[j][0]].strip().startswith(';'):
                        return z_moves[j][0]
                return z_moves[max(0, i-1)][0]

        return 0  # Fallback to start

    def remove_homing_and_start(self, content):
        """Remove initial homing and print start sequences"""
        patterns_to_remove = [
            r'^G28',          # Home all
            r'^G28 X Y',      # Home XY
            r'^G28 Z',        # Home Z
            r'^M107',         # Fan off
            r'^G92 E0',       # Reset extruder
            r'^M82',          # E absolute
            r'^G90',          # Absolute positioning
            r'^M140',         # Bed temp
            r'^M190',         # Wait bed temp
            r'^M104',         # Hotend temp
            r'^M109',         # Wait hotend temp
            r'^;PRINT_START', # Print start comment
        ]

        filtered_content = []
        in_removal_section = True

        for line in content:
            stripped = line.strip()

            # Check if we should stop removing
            if in_removal_section:
                is_removable = False
                for pattern in patterns_to_remove:
                    if re.match(pattern, stripped, re.IGNORECASE):
                        is_removable = True
                        break

                # Also remove comment-only lines at start
                if stripped.startswith(';') and not stripped.startswith(';TYPE'):
                    is_removable = True

                if not is_removable and stripped:
                    # Found first non-removable line, stop removing
                    in_removal_section = False
                    filtered_content.append(line)
                else:
                    # Skip this line
                    continue
            else:
                filtered_content.append(line)

        return filtered_content

    def create_resume_header(self):
        """Create G-code header for resume"""
        header = [
            '; === PRINT RESUME TOOL ===\n',
            '; Resume height: {:.2f}mm\n'.format(self.resume_height),
            '; Layer height: {:.2f}mm\n'.format(self.layer_height),
            ';\n',
            '; IMPORTANT: Perform these steps BEFORE printing:\n',
            '; 1. Heat bed to print temperature\n',
            '; 2. Heat nozzle to print temperature\n',
            '; 3. Home XY: G28 X Y\n',
            '; 4. Home Z at safe position: G28 Z\n',
            '; 5. Manually move nozzle to resume height\n',
            ';\n',
            'M83 ; Extruder relative\n',
            'G90 ; Absolute positioning\n',
            'M107 ; Fan off\n',
            ';\n',
            '; Set current Z position\n',
            'G92 Z{:.3f} ; Set current Z to resume height\n'.format(self.resume_height),
            ';\n',
            '; Reset extruder position\n',
            'G92 E0\n',
            ';\n',
        ]
        return header

    def process_gcode(self):
        """Main processing function"""
        print(f"Processing: {self.gcode_file}")
        print(f"Resume height: {self.resume_height}mm")
        print(f"Layer height: {self.layer_height}mm")

        # Read original file
        with open(self.gcode_file, 'r') as f:
            content = f.readlines()

        # Find where to resume
        resume_line = self.find_resume_layer(content, self.resume_height)
        print(f"Resuming from line {resume_line}")

        # Extract from resume point
        resumed_content = content[resume_line:]

        # Remove initial homing/start commands
        cleaned_content = self.remove_homing_and_start(resumed_content)

        # Create new file with resume header
        output_content = []
        output_content.extend(self.create_resume_header())
        output_content.extend(cleaned_content)

        # Write output file
        with open(self.output_file, 'w') as f:
            f.writelines(output_content)

        print(f"\n✓ Created resume file: {self.output_file}")
        print("\n=== NEXT STEPS ===")
        print("1. Heat bed to print temperature")
        print("2. Heat nozzle to print temperature")
        print("3. Home XY: G28 X Y")
        print(f"4. Home Z at safe position: G28 Z (or use safe_z_home)")
        print("5. Manually move nozzle to resume height")
        print(f"6. Start print: {self.output_file}")
        print("\n⚠️  IMPORTANT: Monitor first few layers carefully!")

    def create_macro_version(self):
        """Create a Klipper macro for easy use"""
        macro = """
[gcode_macro RESUME_PRINT]
description: Resume failed print from specific height
gcode:
    {% set Z = params.Z|default(0)|float %}
    {% set FILENAME = params.FILENAME|default("") %}
    {% set LAYER_HEIGHT = params.LAYER_HEIGHT|default(0.2)|float %}

    {% if FILENAME == "" %}
        { action_raise_error("FILENAME parameter required") }
    {% endif %}

    SAVE_GCODE_STATE NAME=resume_state

    ; Heat bed and nozzle
    M140 S{printer.heater_bed.target} ; Re-apply bed temp
    M104 S{printer.extruder.target}   ; Re-apply nozzle temp

    ; Wait for temperatures
    M190 S{printer.heater_bed.target}
    M109 S{printer.extruder.target}

    ; Home XY
    G28 X Y

    ; Home Z at safe position (adjust coordinates in your printer.cfg)
    ; Requires [safe_z_home] in printer.cfg
    SAFE_Z_HOME

    ; Pause for manual nozzle positioning
    PAUSE

    ; Set current Z position
    G92 Z{Z}

    ; Reset extruder
    G92 E0

    ; Continue with print
    RESTORE_GCODE_STATE NAME=resume_state
    RESUME

[gcode_macro SAFE_Z_HOME]
gcode:
    ; Move to safe position for Z homing
    G90
    G0 X{safe_z_home_x} Y{safe_z_home_y} F6000
    G28 Z
"""
        return macro

def main():
    tool = PrintResumeTool()
    tool.parse_arguments()
    tool.process_gcode()

if __name__ == "__main__":
    main()
