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
        self.bed_temp = None
        self.hotend_temp = None

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
        parser.add_argument(
            '--bed-temp',
            type=float,
            help='Bed temperature (auto-detected if not specified)'
        )
        parser.add_argument(
            '--hotend-temp',
            type=float,
            help='Hotend temperature (auto-detected if not specified)'
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
        self.bed_temp = args.bed_temp
        self.hotend_temp = args.hotend_temp

    def extract_temperatures(self, content):
        """Extract bed and hotend temperatures from original G-code.

        Searches for:
        - Klipper PRINT_START macro: PRINT_START BED=85 HOTEND=230
        - Standard G-code: M140 S85 (bed), M104 S230 (hotend)
        - With wait: M190 S85 (bed), M109 S230 (hotend)
        """
        bed_temp = None
        hotend_temp = None

        # Only search first 500 lines (start section)
        search_lines = content[:500]

        for line in search_lines:
            line = line.strip()

            # Check for Klipper PRINT_START macro
            print_start_match = re.search(
                r'PRINT_START.*BED=(\d+).*HOTEND=(\d+)',
                line, re.IGNORECASE
            )
            if print_start_match:
                bed_temp = int(print_start_match.group(1))
                hotend_temp = int(print_start_match.group(2))
                break

            # Check for standard M140/M190 (bed temperature)
            if bed_temp is None:
                bed_match = re.search(r'M1[49]0\s+S(\d+)', line)
                if bed_match and int(bed_match.group(1)) > 0:
                    bed_temp = int(bed_match.group(1))

            # Check for standard M104/M109 (hotend temperature)
            if hotend_temp is None:
                hotend_match = re.search(r'M10[49]\s+S(\d+)', line)
                if hotend_match and int(hotend_match.group(1)) > 0:
                    hotend_temp = int(hotend_match.group(1))

            # Stop if we found both
            if bed_temp is not None and hotend_temp is not None:
                break

        return bed_temp, hotend_temp

    def find_layer_changes_with_z(self, content):
        """Find all layer change markers with their Z heights from slicer comments.

        Returns list of tuples: (line_number, z_height)
        Supports multiple slicer formats.
        """
        layers = []

        # Pattern for ;Z: markers (OrcaSlicer, PrusaSlicer, Cura)
        z_comment_pattern = r'^;Z:([\d.]+)'
        # Pattern for ;LAYER:n followed by finding Z
        layer_num_pattern = r'^;LAYER:(\d+)'
        # Pattern for ; layer n, z = X.XX (some PrusaSlicer versions)
        layer_z_pattern = r'^; layer \d+, z = ([\d.]+)'

        i = 0
        while i < len(content):
            line = content[i].strip()

            # Check for ;Z: marker (most reliable)
            match = re.match(z_comment_pattern, line)
            if match:
                z_height = float(match.group(1))
                # Look back for LAYER_CHANGE marker
                layer_start = i
                for j in range(max(0, i - 5), i):
                    if ';LAYER_CHANGE' in content[j] or re.match(layer_num_pattern, content[j].strip()):
                        layer_start = j
                        break
                layers.append((layer_start, z_height))
                i += 1
                continue

            # Check for ; layer n, z = X.XX format
            match = re.match(layer_z_pattern, line)
            if match:
                z_height = float(match.group(1))
                layers.append((i, z_height))
                i += 1
                continue

            i += 1

        return layers

    def find_layer_changes(self, content):
        """Find all layer change markers in G-code (legacy method)"""
        layer_patterns = [
            r';LAYER_CHANGE',            # Cura/OrcaSlicer
            r';LAYER:(\d+)',             # Cura/Slic3r
            r';BEFORE_LAYER_CHANGE',     # Cura
            r'^; layer (\d+)',           # PrusaSlicer
        ]

        layer_lines = []
        for i, line in enumerate(content):
            for pattern in layer_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    layer_lines.append(i)
                    break
        return layer_lines

    def find_z_moves(self, content):
        """Extract Z positions from G-code moves (fallback method).

        Note: This includes travel moves which may have elevated Z.
        Prefer find_layer_changes_with_z() for accurate layer heights.
        """
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
        """Find the best layer to resume from.

        Uses slicer Z markers (;Z:) for accurate layer detection,
        falls back to G-code Z moves if markers not found.
        """
        # Try to find layers with Z heights from slicer comments (most accurate)
        layers_with_z = self.find_layer_changes_with_z(content)

        if layers_with_z:
            print(f"Found {len(layers_with_z)} layers with Z markers")

            # Find first layer where Z >= target - layer_height
            threshold = target_height - self.layer_height
            resume_line = None
            resume_z = None

            for line_num, z_height in layers_with_z:
                if z_height >= threshold:
                    resume_line = line_num
                    resume_z = z_height
                    break

            if resume_line is not None:
                print(f"Found resume layer at Z:{resume_z}mm (line {resume_line})")
                return resume_line
            else:
                # Use last layer if target is beyond all layers
                print("Warning: Target height beyond all layers, using last layer")
                return layers_with_z[-1][0]

        # Fallback: use legacy method with layer markers and Z moves
        print("Warning: No ;Z: markers found, using fallback detection")
        layer_indices = self.find_layer_changes(content)
        z_moves = self.find_z_moves(content)

        if not layer_indices:
            print("Warning: No layer change markers found!")
            return self.find_resume_by_z_only(content, target_height)

        # Find the layer where Z reaches or exceeds target height
        resume_layer_idx = None
        threshold = target_height - self.layer_height

        for i, layer_line in enumerate(layer_indices):
            # Find Z position after this layer change
            for z_line, z_pos in z_moves:
                if z_line > layer_line:
                    # Found the first Z move after layer change
                    if z_pos >= threshold:
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
        """Create G-code header for resume with automated workflow.

        Workflow:
        1. Heat bed and hotend to original temperatures
        2. Home X and Y axes
        3. PAUSE - user manually positions nozzle to resume height
        4. After RESUME: set Z position and continue printing
        """
        header = [
            '; === PRINT RESUME TOOL ===\n',
            '; Resume height: {:.2f}mm\n'.format(self.resume_height),
            '; Layer height: {:.2f}mm\n'.format(self.layer_height),
        ]

        if self.bed_temp:
            header.append('; Bed temperature: {}C\n'.format(self.bed_temp))
        if self.hotend_temp:
            header.append('; Hotend temperature: {}C\n'.format(self.hotend_temp))

        header.extend([
            ';\n',
            '; WORKFLOW:\n',
            '; 1. File will heat bed and nozzle automatically\n',
            '; 2. File will home X and Y automatically\n',
            '; 3. Printer will PAUSE - move nozzle to Z={:.2f}mm manually\n'.format(self.resume_height),
            '; 4. Click RESUME to continue printing\n',
            ';\n',
            '\n',
            '; === START RESUME SEQUENCE ===\n',
            '\n',
            '; Set absolute positioning\n',
            'G90\n',
            '\n',
        ])

        # Add temperature commands if available
        if self.bed_temp and self.hotend_temp:
            header.extend([
                '; Heat bed and nozzle\n',
                'M140 S{} ; Set bed temperature\n'.format(self.bed_temp),
                'M104 S{} ; Set hotend temperature\n'.format(self.hotend_temp),
                'M190 S{} ; Wait for bed temperature\n'.format(self.bed_temp),
                'M109 S{} ; Wait for hotend temperature\n'.format(self.hotend_temp),
                '\n',
            ])
        elif self.bed_temp:
            header.extend([
                '; Heat bed (hotend temp not detected - set manually before starting)\n',
                'M140 S{} ; Set bed temperature\n'.format(self.bed_temp),
                'M190 S{} ; Wait for bed temperature\n'.format(self.bed_temp),
                '\n',
            ])
        elif self.hotend_temp:
            header.extend([
                '; Heat hotend (bed temp not detected - set manually before starting)\n',
                'M104 S{} ; Set hotend temperature\n'.format(self.hotend_temp),
                'M109 S{} ; Wait for hotend temperature\n'.format(self.hotend_temp),
                '\n',
            ])
        else:
            header.extend([
                '; WARNING: Temperatures not detected!\n',
                '; Heat bed and nozzle manually before starting this file.\n',
                '\n',
            ])

        header.extend([
            '; Home X and Y axes\n',
            'G28 X Y\n',
            '\n',
            '; === PAUSE FOR MANUAL NOZZLE POSITIONING ===\n',
            '; Move the nozzle to Z={:.2f}mm above the print surface\n'.format(self.resume_height),
            '; Use the LCD or web interface to jog Z to the correct height\n',
            '; The nozzle should be approximately one layer height above the last printed layer\n',
            'PAUSE MSG="Move nozzle to Z={:.2f}mm, then click RESUME"\n'.format(self.resume_height),
            '\n',
            '; === AFTER RESUME ===\n',
            '; Set current Z position to resume height\n',
            'G92 Z{:.3f}\n'.format(self.resume_height),
            '\n',
            '; Reset extruder position\n',
            'G92 E0\n',
            '\n',
            '; Set modes for printing\n',
            'M83 ; Extruder relative mode\n',
            'G90 ; Absolute positioning\n',
            '\n',
            '; === BEGIN RESUMED PRINT ===\n',
            '\n',
        ])

        return header

    def process_gcode(self):
        """Main processing function"""
        print(f"Processing: {self.gcode_file}")
        print(f"Resume height: {self.resume_height}mm")
        print(f"Layer height: {self.layer_height}mm")

        # Read original file
        with open(self.gcode_file, 'r') as f:
            content = f.readlines()

        # Extract temperatures if not provided via command line
        if self.bed_temp is None or self.hotend_temp is None:
            detected_bed, detected_hotend = self.extract_temperatures(content)
            if self.bed_temp is None:
                self.bed_temp = detected_bed
            if self.hotend_temp is None:
                self.hotend_temp = detected_hotend

        if self.bed_temp:
            print(f"Bed temperature: {self.bed_temp}°C")
        else:
            print("Warning: Bed temperature not detected")

        if self.hotend_temp:
            print(f"Hotend temperature: {self.hotend_temp}°C")
        else:
            print("Warning: Hotend temperature not detected")

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
        print("\n=== WORKFLOW ===")
        print(f"1. Upload {self.output_file} to your printer")
        print("2. Start the print")
        print("3. Printer will heat up and home X/Y automatically")
        print("4. Printer will PAUSE")
        print(f"5. Manually move nozzle to Z={self.resume_height}mm")
        print("6. Click RESUME to continue printing")
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
