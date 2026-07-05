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
            '--object',
            type=int,
            default=None,
            help='For sequential ("by object") prints where Z restarts per object: '
                 '1-based index of the object that failed. Run without it to list objects.'
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
        self.object_index = args.object

        if args.output:
            self.output_file = args.output
        else:
            orig_path = Path(args.gcode_file)
            candidate = orig_path.with_name(f"{orig_path.stem}_resumed{orig_path.suffix}")
            counter = 1
            while candidate.exists():
                candidate = orig_path.with_name(
                    f"{orig_path.stem}_resumed_{counter}{orig_path.suffix}"
                )
                counter += 1
            self.output_file = str(candidate)

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

    def extract_temperatures_at(self, content, resume_line):
        """Detect the temperatures active at the resume point.

        Scans backward from the cut for the last M104/M140 with S>0. This picks
        up the print temperature rather than the (often hotter) first-layer
        temperature from the start section.
        """
        bed_temp = None
        hotend_temp = None

        for line in reversed(content[:resume_line]):
            clean = line.split(';')[0]
            if hotend_temp is None:
                match = re.search(r'M10[49]\s+S(\d+)', clean)
                if match and int(match.group(1)) > 0:
                    hotend_temp = int(match.group(1))
            if bed_temp is None:
                match = re.search(r'M1[49]0\s+S(\d+)', clean)
                if match and int(match.group(1)) > 0:
                    bed_temp = int(match.group(1))
            if bed_temp is not None and hotend_temp is not None:
                break

        return bed_temp, hotend_temp

    def extract_state_lines(self, content, resume_line):
        """Collect state commands the resumed print still needs.

        The cut discards the start section, losing state the remaining G-code
        relies on: EXCLUDE_OBJECT_DEFINE (EXCLUDE_OBJECT_START errors without
        it), SKEW_PROFILE LOAD, and M900 pressure/linear advance.
        """
        state_lines = []
        for line in content[:resume_line]:
            stripped = line.strip()
            if (stripped.startswith('EXCLUDE_OBJECT_DEFINE')
                    or (stripped.startswith('SKEW_PROFILE') and 'LOAD=' in stripped)
                    or stripped.startswith('M900')):
                if stripped + '\n' not in state_lines:
                    state_lines.append(stripped + '\n')
        return state_lines

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

    def split_into_segments(self, layers):
        """Split the layer list into segments at Z resets.

        Sequential ("print by object") files print each object bottom-to-top
        in turn, so Z restarts for every object. Each segment is one object's
        list of (line_number, z_height) tuples.
        """
        segments = []
        current = []
        prev_z = None
        for line_num, z in layers:
            if prev_z is not None and z < prev_z:
                segments.append(current)
                current = []
            current.append((line_num, z))
            prev_z = z
        if current:
            segments.append(current)
        return segments

    def segment_object_name(self, content, segment):
        """Best-effort object name for a segment from EXCLUDE_OBJECT_START markers."""
        start_line = segment[0][0]
        end_line = segment[-1][0]
        pattern = re.compile(r'EXCLUDE_OBJECT_START\s+NAME=(\S+)')
        for line in content[start_line:end_line]:
            match = pattern.search(line)
            if match:
                return match.group(1)
        return None

    def select_segment(self, content, segments, target_height):
        """Pick the object segment to resume in.

        Single-segment files pass through untouched. For sequential prints the
        target height can exist in several objects, so we auto-select only when
        exactly one object reaches it — otherwise --object is required.
        """
        if len(segments) == 1:
            return segments[0]

        threshold = target_height - self.layer_height
        candidates = [i for i, seg in enumerate(segments) if seg[-1][1] >= threshold]

        def describe():
            print(f"\nSequential print detected: {len(segments)} objects (Z restarts between them)")
            for i, seg in enumerate(segments):
                name = self.segment_object_name(content, seg) or 'unknown'
                marker = '  <- reaches target height' if i in candidates else ''
                print(f"  --object {i + 1}: {name}  "
                      f"Z {seg[0][1]}-{seg[-1][1]}mm, lines {seg[0][0]}-{seg[-1][0]}{marker}")

        if self.object_index is not None:
            if not 1 <= self.object_index <= len(segments):
                describe()
                sys.exit(f"\nError: --object {self.object_index} out of range (1-{len(segments)})")
            return segments[self.object_index - 1]

        if len(candidates) == 1:
            seg = segments[candidates[0]]
            name = self.segment_object_name(content, seg) or 'unknown'
            print(f"Sequential print: auto-selected object {candidates[0] + 1} ({name}) — "
                  f"the only one that reaches {target_height}mm")
            return seg

        describe()
        sys.exit("\nError: the target height exists in multiple objects. "
                 "Re-run with --object N for the object that failed.")

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

            # Sequential prints: narrow to the failed object's segment first,
            # otherwise the same height matches the wrong object
            segments = self.split_into_segments(layers_with_z)
            layers_with_z = self.select_segment(content, segments, target_height)

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

    def create_resume_header(self, state_lines=None):
        """Create G-code header for the no-pause resume workflow.

        The user positions the nozzle manually BEFORE starting this file;
        the file then declares that position as the resume height and prints.

        No PAUSE is used: park-and-restore RESUME macros (Mainsail's
        RESTORE_GCODE_STATE MOVE=1) move back to the pre-jog position, which
        either errors with "Move out of range" or resumes in mid-air.
        """
        gap = self.layer_height
        header = [
            '; === PRINT RESUME TOOL (no-pause workflow) ===\n',
            '; Resume height: {:.2f}mm\n'.format(self.resume_height),
            '; Layer height: {:.2f}mm\n'.format(self.layer_height),
        ]

        if self.bed_temp:
            header.append('; Bed temperature: {}C\n'.format(self.bed_temp))
        if self.hotend_temp:
            header.append('; Hotend temperature: {}C\n'.format(self.hotend_temp))

        header.extend([
            ';\n',
            '; PREP - do this in the console/jog panel BEFORE starting this file:\n',
            ';   1. SET_KINEMATIC_POSITION Z=200   (unlocks Z jogging; NEVER home Z)\n',
            ';   2. Raise Z ~20mm, then home X and Y only: G28 X Y\n',
            ';   3. Preheat bed and nozzle, wipe ooze off the nozzle\n',
            ';   4. Jog the nozzle to ~{:.1f}mm ABOVE the highest point of the print\n'.format(gap),
            ';      (one layer height - a folded piece of paper as feeler gauge works)\n',
            ';   5. Start this file - it declares that position as Z={:.2f} and prints\n'.format(self.resume_height),
            ';      the first layer flush on the top surface (the offsets cancel)\n',
            ';\n',
            '; If something goes wrong: CANCEL_PRINT, re-jog, start again.\n',
            '; Do NOT use PAUSE/RESUME - park-and-restore macros break this workflow.\n',
            '; If XY is misaligned, correct live: SET_GCODE_OFFSET X=.. Y=.. MOVE=1\n',
            '; (and reset with SET_GCODE_OFFSET X=0 Y=0 after the print).\n',
            ';\n',
            '\n',
            '; === START RESUME SEQUENCE ===\n',
            '\n',
            'M117 Resuming from {:.2f}mm\n'.format(self.resume_height),
            'RESPOND MSG="Resume print: continuing from Z={:.2f}mm"\n'.format(self.resume_height),
            '\n',
            '; Set absolute positioning\n',
            'G90\n',
            '\n',
        ])

        # Add temperature commands if available (instant if preheated per PREP)
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
            '; Declare the manually-jogged nozzle position as the resume height\n',
            '; (no motors move; requires the PREP steps above to be done)\n',
            'SET_KINEMATIC_POSITION Z={:.3f}\n'.format(self.resume_height),
            '\n',
            '; Reset extruder position\n',
            'G92 E0\n',
            '\n',
            '; Set modes for printing\n',
            'M83 ; Extruder relative mode\n',
            'G90 ; Absolute positioning\n',
            '\n',
        ])

        if state_lines:
            header.append('; Restore state normally set by the start section\n')
            header.extend(state_lines)
            header.append('\n')

        header.extend([
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

        # Find where to resume
        resume_line = self.find_resume_layer(content, self.resume_height)
        print(f"Resuming from line {resume_line}")

        # Extract temperatures if not provided via command line: prefer the
        # temps active at the cut (print temp), fall back to the start section
        if self.bed_temp is None or self.hotend_temp is None:
            near_bed, near_hotend = self.extract_temperatures_at(content, resume_line)
            start_bed, start_hotend = self.extract_temperatures(content)
            if self.bed_temp is None:
                self.bed_temp = near_bed if near_bed is not None else start_bed
            if self.hotend_temp is None:
                self.hotend_temp = near_hotend if near_hotend is not None else start_hotend

        if self.bed_temp:
            print(f"Bed temperature: {self.bed_temp}°C")
        else:
            print("Warning: Bed temperature not detected")

        if self.hotend_temp:
            print(f"Hotend temperature: {self.hotend_temp}°C")
        else:
            print("Warning: Hotend temperature not detected")

        # Carry over state the cut discards (object defines, skew, M900)
        state_lines = self.extract_state_lines(content, resume_line)
        for line in state_lines:
            print(f"Carrying over: {line.strip()[:60]}")

        # Extract from resume point
        resumed_content = content[resume_line:]

        # Remove initial homing/start commands
        cleaned_content = self.remove_homing_and_start(resumed_content)

        # Create new file with resume header
        output_content = []
        output_content.extend(self.create_resume_header(state_lines))
        output_content.extend(cleaned_content)

        # Write output file
        with open(self.output_file, 'w') as f:
            f.writelines(output_content)

        print(f"\n✓ Created resume file: {self.output_file}")
        print("\n=== WORKFLOW (no-pause: position the nozzle BEFORE starting) ===")
        print(f"1. Upload {self.output_file} to your printer")
        print("2. Console: SET_KINEMATIC_POSITION Z=200   (unlocks Z jogging; NEVER home Z)")
        print("3. Raise Z ~20mm, then home X and Y only: G28 X Y")
        print("4. Preheat bed and nozzle, wipe ooze off the nozzle")
        print(f"5. Jog the nozzle to ~{self.layer_height}mm ABOVE the print's highest point")
        print("6. Start the file - the first layer lands flush on the top surface")
        print("\n⚠️  Monitor the first layers! If XY is off, fix live with")
        print("   SET_GCODE_OFFSET X=.. Y=.. MOVE=1 (reset to 0 after the print).")
        print("   If it goes wrong: CANCEL_PRINT and re-jog - never PAUSE.")

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
