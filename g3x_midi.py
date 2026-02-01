#!/usr/bin/env python3
"""
Zoom G3X MIDI Controller Interface

A Python interface for controlling the Zoom G3X multi-effects pedal via USB MIDI.
Supports patch switching, effect toggling, and parameter editing.

Requirements:
    pip install mido python-rtmidi
"""

import mido
import time
import sys
from dataclasses import dataclass, field
from typing import Optional, List

# Zoom G3X SysEx constants
SYSEX_PREFIX = [0x52, 0x00, 0x59]  # Manufacturer ID + device
MANUFACTURER_ID = 0x52  # Zoom

# Commands
CMD_GET_PATCH_DATA = 0x29
CMD_MODIFY_EFFECT = 0x31
CMD_GET_PROGRAM_NUM = 0x33
CMD_ENTER_EDIT = 0x50
CMD_EXIT_EDIT = 0x51

# Effect slot sub-commands
SUBCMD_ON_OFF = 0x00
SUBCMD_EFFECT_TYPE = 0x01
SUBCMD_KNOB_BASE = 0x02  # Knobs start at 0x02

# Known effect IDs (incomplete - add more as you discover them)
EFFECTS = {
    0x00: "None",
    0x01: "The Vibe",
    0x02: "Z-Organ",
    0x03: "Slicer",
}

# Patch data structure constants
PATCH_DATA_HEADER_SIZE = 5
EFFECT_SLOT_SIZE = 14
NUM_EFFECT_SLOTS = 6
PATCH_NAME_OFFSET = 96
PATCH_NAME_LENGTH = 11


# =============================================================================
# Patch Data Structures
# =============================================================================

@dataclass
class EffectSlot:
    """Represents a single effect slot in a patch."""
    slot_num: int
    effect_id: int = 0
    enabled: bool = False
    knob_values: List[int] = field(default_factory=lambda: [0, 0, 0, 0])
    raw_bytes: bytes = b''

    @property
    def effect_name(self) -> str:
        """Get human-readable effect name."""
        return EFFECTS.get(self.effect_id, f"Unknown (0x{self.effect_id:02X})")


@dataclass
class PatchData:
    """Represents a complete patch configuration."""
    raw_data: bytes
    patch_name: str = ""
    effect_slots: List[EffectSlot] = field(default_factory=list)
    metadata: bytes = b''

    def __str__(self) -> str:
        return f"Patch: {self.patch_name}"


def decode_14bit(low: int, high: int) -> int:
    """
    Decode a 14-bit MIDI value from two 7-bit bytes.

    MIDI uses 7 bits per byte (0-127), so large values are split across
    two bytes: low 7 bits in first byte, high 7 bits in second byte.

    Args:
        low: Low byte (bits 0-6)
        high: High byte (bits 7-13)

    Returns:
        Combined 14-bit value (0-16383)
    """
    return (low & 0x7F) | ((high & 0x7F) << 7)


def parse_patch_data(data: List[int]) -> Optional[PatchData]:
    """
    Parse raw SysEx patch data into a structured PatchData object.

    Args:
        data: Raw bytes from patch data response (without F0/F7)

    Returns:
        PatchData object, or None if parsing fails
    """
    if not data or len(data) < 100:
        print(f"Patch data too short: {len(data) if data else 0} bytes")
        return None

    # Verify header
    if data[0:3] != SYSEX_PREFIX:
        print(f"Invalid header: expected {SYSEX_PREFIX}, got {data[0:3]}")
        return None

    # Command byte should be 0x28 (response to 0x29)
    if data[3] != 0x28:
        print(f"Unexpected command byte: 0x{data[3]:02X}")
        return None

    raw_bytes = bytes(data)
    patch = PatchData(raw_data=raw_bytes)

    # Store metadata (bytes 4-7)
    patch.metadata = raw_bytes[4:8]

    # Parse patch name (bytes 97-106, null-terminated)
    if len(data) > PATCH_NAME_OFFSET + PATCH_NAME_LENGTH:
        name_bytes = data[PATCH_NAME_OFFSET:PATCH_NAME_OFFSET + PATCH_NAME_LENGTH]
        # Decode as ASCII, stop at null terminator
        name_chars = []
        for b in name_bytes:
            if b == 0:
                break
            if 32 <= b < 127:  # Printable ASCII
                name_chars.append(chr(b))
        patch.patch_name = ''.join(name_chars).strip()

    # Parse effect slots
    # Knob 2 positions (confirmed from reverse engineering):
    # Slot 0: byte 8
    # Slot 1: bytes 22-23 (14-bit)
    # Slot 2: bytes 35-36 (14-bit)
    # Slot 3: byte 50
    # Slot 4: byte 64
    # Slot 5: byte 78 (predicted)

    knob2_positions = [8, 22, 35, 50, 64, 78]

    for slot_num in range(NUM_EFFECT_SLOTS):
        slot = EffectSlot(slot_num=slot_num)

        # Calculate slot byte range (approximate, ~14 bytes per slot starting around byte 5)
        slot_start = 5 + (slot_num * EFFECT_SLOT_SIZE)
        slot_end = slot_start + EFFECT_SLOT_SIZE

        if slot_end <= len(data):
            slot.raw_bytes = raw_bytes[slot_start:slot_end]

            # Effect ID is typically in first few bytes of slot
            # Based on structure, byte 0 of slot often has effect type info
            if slot_start + 2 <= len(data):
                # Effect ID encoding varies - this is approximate
                slot.effect_id = data[slot_start] & 0x7F

            # Enabled/disabled flag (often in slot header)
            if slot_start + 1 <= len(data):
                # Enable flag position varies by effect
                slot.enabled = bool(data[slot_start + 1] & 0x01)

        # Parse knob 2 value at known position
        k2_pos = knob2_positions[slot_num]
        if k2_pos + 1 < len(data):
            # Slots 1 and 2 use 14-bit encoding
            if slot_num in [1, 2]:
                slot.knob_values[1] = decode_14bit(data[k2_pos], data[k2_pos + 1])
            else:
                slot.knob_values[1] = data[k2_pos]

        patch.effect_slots.append(slot)

    return patch


def print_patch_info(patch: PatchData):
    """
    Print human-readable patch information.

    Args:
        patch: Parsed PatchData object
    """
    print("\n" + "=" * 50)
    print(f"PATCH: {patch.patch_name or '(unnamed)'}")
    print("=" * 50)

    print(f"\nMetadata: {' '.join(f'{b:02X}' for b in patch.metadata)}")
    print(f"Total bytes: {len(patch.raw_data)}")

    print("\nEFFECT SLOTS:")
    print("-" * 50)

    for slot in patch.effect_slots:
        status = "ON " if slot.enabled else "OFF"
        knob2_val = slot.knob_values[1]

        print(f"  Slot {slot.slot_num}: [{status}] {slot.effect_name:20s} | Knob2: {knob2_val:4d}")

        # Show raw bytes for debugging
        if slot.raw_bytes:
            raw_hex = ' '.join(f'{b:02X}' for b in slot.raw_bytes[:8])
            print(f"           Raw: {raw_hex}...")

    print("-" * 50)

    # Show patch name bytes for debugging
    if len(patch.raw_data) > PATCH_NAME_OFFSET:
        name_bytes = patch.raw_data[PATCH_NAME_OFFSET:PATCH_NAME_OFFSET + PATCH_NAME_LENGTH]
        print(f"\nName bytes (@{PATCH_NAME_OFFSET}): {' '.join(f'{b:02X}' for b in name_bytes)}")
        print(f"  ASCII: {''.join(chr(b) if 32 <= b < 127 else '.' for b in name_bytes)}")


class ZoomG3X:
    """Interface for the Zoom G3X multi-effects pedal."""

    def __init__(self, port_name: Optional[str] = None):
        """
        Initialize connection to the G3X.

        Args:
            port_name: MIDI port name. If None, will attempt to auto-detect.
        """
        self.port_name = port_name
        self.port: Optional[mido.ports.BaseOutput] = None
        self.input_port: Optional[mido.ports.BaseInput] = None
        self.in_edit_mode = False

    def list_ports(self) -> tuple[List[str], List[str]]:
        """List available MIDI ports."""
        inputs = mido.get_input_names()
        outputs = mido.get_output_names()
        return inputs, outputs

    def find_g3x_port(self) -> Optional[str]:
        """Try to find the G3X MIDI port automatically."""
        outputs = mido.get_output_names()
        for port in outputs:
            # Look for common Zoom identifiers
            if 'zoom' in port.lower() or 'g3x' in port.lower():
                return port
        return None

    def connect(self) -> bool:
        """
        Connect to the G3X.

        Returns:
            True if connection successful.
        """
        if self.port_name is None:
            self.port_name = self.find_g3x_port()

        if self.port_name is None:
            print("Could not auto-detect G3X. Available ports:")
            inputs, outputs = self.list_ports()
            print(f"  Inputs: {inputs}")
            print(f"  Outputs: {outputs}")
            return False

        try:
            self.port = mido.open_output(self.port_name)
            # Try to open matching input port for responses
            inputs = mido.get_input_names()
            for inp in inputs:
                if self.port_name.split(':')[0] in inp:
                    self.input_port = mido.open_input(inp)
                    break
            print(f"Connected to: {self.port_name}")
            return True
        except Exception as e:
            print(f"Failed to connect: {e}")
            return False

    def disconnect(self):
        """Disconnect from the G3X."""
        if self.in_edit_mode:
            self.exit_edit_mode()
        if self.port:
            self.port.close()
            self.port = None
        if self.input_port:
            self.input_port.close()
            self.input_port = None

    def _send_sysex(self, data: List[int]) -> Optional[List[int]]:
        """
        Send a SysEx message and optionally receive response.

        Args:
            data: Command bytes (without prefix/suffix)

        Returns:
            Response data if input port available, else None
        """
        if not self.port:
            print("Not connected!")
            return None

        # Build full SysEx: prefix + data
        full_msg = SYSEX_PREFIX + data
        msg = mido.Message('sysex', data=full_msg)

        print(f"TX: F0 {' '.join(f'{b:02X}' for b in full_msg)} F7")
        self.port.send(msg)

        # Try to read response
        if self.input_port:
            time.sleep(0.1)  # Give device time to respond
            response = []
            for msg in self.input_port.iter_pending():
                if msg.type == 'sysex':
                    response = list(msg.data)
                    print(f"RX: F0 {' '.join(f'{b:02X}' for b in response)} F7")
            return response if response else None
        return None

    def _send_program_change(self, program: int):
        """Send a program change message."""
        if not self.port:
            print("Not connected!")
            return
        msg = mido.Message('program_change', program=program)
        print(f"TX: Program Change {program}")
        self.port.send(msg)

    # =========================================================================
    # Edit Mode
    # =========================================================================

    def enter_edit_mode(self) -> bool:
        """Enter edit mode (required for modifying patches)."""
        self._send_sysex([CMD_ENTER_EDIT])
        self.in_edit_mode = True
        print("Entered edit mode")
        return True

    def exit_edit_mode(self) -> bool:
        """Exit edit mode."""
        self._send_sysex([CMD_EXIT_EDIT])
        self.in_edit_mode = False
        print("Exited edit mode")
        return True

    # =========================================================================
    # Patch Operations
    # =========================================================================

    def get_current_patch_data(self) -> Optional[List[int]]:
        """Get full data for the current patch."""
        return self._send_sysex([CMD_GET_PATCH_DATA])

    def get_patch_info(self) -> Optional[PatchData]:
        """
        Get and parse the current patch data.

        Returns:
            Parsed PatchData object, or None if request fails
        """
        response = self.get_current_patch_data()
        if response:
            return parse_patch_data(response)
        return None

    def get_current_program(self) -> Optional[int]:
        """Get the current program/patch number."""
        response = self._send_sysex([CMD_GET_PROGRAM_NUM])
        if response:
            # Parse program number from response
            # Response format: 52 00 59 32 01 00 00 <program> ...
            # This may need adjustment based on actual response
            return response
        return None

    def change_patch(self, patch_num: int):
        """
        Change to a different patch.

        Args:
            patch_num: Patch number (0-99, or 0x00-0x63)
        """
        if patch_num < 0 or patch_num > 99:
            print(f"Invalid patch number: {patch_num} (must be 0-99)")
            return
        self._send_program_change(patch_num)
        print(f"Changed to patch {patch_num}")

    # =========================================================================
    # Effect Operations
    # =========================================================================

    def set_effect_enabled(self, slot: int, enabled: bool):
        """
        Turn an effect on or off.

        Args:
            slot: Effect slot position (0-5, left to right)
            enabled: True to enable, False to disable
        """
        if slot < 0 or slot > 5:
            print(f"Invalid slot: {slot} (must be 0-5)")
            return

        value = 0x01 if enabled else 0x00
        self._send_sysex([CMD_MODIFY_EFFECT, slot, SUBCMD_ON_OFF, value, 0x00])
        print(f"Slot {slot}: {'ON' if enabled else 'OFF'}")

    def set_effect_type(self, slot: int, effect_id: int):
        """
        Change the effect type in a slot.

        Args:
            slot: Effect slot position (0-5)
            effect_id: Effect type ID
        """
        if slot < 0 or slot > 5:
            print(f"Invalid slot: {slot} (must be 0-5)")
            return

        # Format: 31 <slot> <subcmd=01> <effect_id> <??>
        self._send_sysex([CMD_MODIFY_EFFECT, slot, SUBCMD_EFFECT_TYPE, effect_id, 0x00])
        effect_name = EFFECTS.get(effect_id, f"Unknown ({effect_id})")
        print(f"Slot {slot}: Changed to {effect_name}")

    def set_knob_value(self, slot: int, knob: int, value: int):
        """
        Set a knob/parameter value for an effect.

        Args:
            slot: Effect slot position (0-5)
            knob: Knob number (1-based, typically 1-4)
            value: Parameter value (range depends on parameter)

        Note: Values are often offset. A parameter with range -25 to +25
              might use values 0-50 in MIDI.
        """
        if slot < 0 or slot > 5:
            print(f"Invalid slot: {slot} (must be 0-5)")
            return

        # Knob command is 0x02 + (knob - 1), or just knob + 1 based on docs
        knob_cmd = knob + 0x01
        self._send_sysex([CMD_MODIFY_EFFECT, slot, 0x00, knob_cmd, value, 0x00])
        print(f"Slot {slot}, Knob {knob}: Set to {value}")


def interactive_mode(g3x: ZoomG3X):
    """Simple interactive command interface."""
    print("\n=== Zoom G3X Interactive Mode ===")
    print("Commands:")
    print("  edit      - Enter edit mode")
    print("  normal    - Exit edit mode")
    print("  patch N   - Switch to patch N (0-99)")
    print("  data      - Get current patch data (raw)")
    print("  info      - Get and parse current patch (parsed view)")
    print("  parse     - Parse last received patch data")
    print("  prog      - Get current program number")
    print("  on N      - Turn on effect in slot N (0-5)")
    print("  off N     - Turn off effect in slot N (0-5)")
    print("  knob S K V - Set slot S knob K to value V")
    print("  ports     - List MIDI ports")
    print("  quit      - Exit")
    print()

    while True:
        try:
            cmd = input("g3x> ").strip().lower().split()
            if not cmd:
                continue

            if cmd[0] == 'quit' or cmd[0] == 'q':
                break
            elif cmd[0] == 'edit':
                g3x.enter_edit_mode()
            elif cmd[0] == 'normal':
                g3x.exit_edit_mode()
            elif cmd[0] == 'patch' and len(cmd) > 1:
                g3x.change_patch(int(cmd[1]))
            elif cmd[0] == 'data':
                response = g3x.get_current_patch_data()
                if response:
                    g3x._last_patch_data = response
                    print(f"Received {len(response)} bytes (use 'parse' to decode)")
            elif cmd[0] == 'info':
                patch = g3x.get_patch_info()
                if patch:
                    g3x._last_patch_data = list(patch.raw_data)
                    print_patch_info(patch)
                else:
                    print("Failed to get patch info (are you in edit mode?)")
            elif cmd[0] == 'parse':
                if hasattr(g3x, '_last_patch_data') and g3x._last_patch_data:
                    patch = parse_patch_data(g3x._last_patch_data)
                    if patch:
                        print_patch_info(patch)
                else:
                    print("No patch data cached. Run 'data' or 'info' first.")
            elif cmd[0] == 'prog':
                g3x.get_current_program()
            elif cmd[0] == 'on' and len(cmd) > 1:
                g3x.set_effect_enabled(int(cmd[1]), True)
            elif cmd[0] == 'off' and len(cmd) > 1:
                g3x.set_effect_enabled(int(cmd[1]), False)
            elif cmd[0] == 'knob' and len(cmd) > 3:
                g3x.set_knob_value(int(cmd[1]), int(cmd[2]), int(cmd[3]))
            elif cmd[0] == 'ports':
                inputs, outputs = g3x.list_ports()
                print(f"Inputs:  {inputs}")
                print(f"Outputs: {outputs}")
            elif cmd[0] == 'raw' and len(cmd) > 1:
                # Send raw hex bytes (for experimentation)
                data = [int(x, 16) for x in cmd[1:]]
                g3x._send_sysex(data)
            else:
                print(f"Unknown command: {' '.join(cmd)}")

        except ValueError as e:
            print(f"Invalid input: {e}")
        except KeyboardInterrupt:
            print()
            break


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description='Zoom G3X MIDI Controller')
    parser.add_argument('-p', '--port', help='MIDI port name (auto-detect if not specified)')
    parser.add_argument('-l', '--list', action='store_true', help='List MIDI ports and exit')
    parser.add_argument('--patch', type=int, help='Switch to patch number and exit')
    args = parser.parse_args()

    g3x = ZoomG3X(port_name=args.port)

    if args.list:
        inputs, outputs = g3x.list_ports()
        print("MIDI Input Ports:")
        for p in inputs:
            print(f"  {p}")
        print("\nMIDI Output Ports:")
        for p in outputs:
            print(f"  {p}")
        return

    if not g3x.connect():
        print("\nTip: Use -p 'port name' to specify the port manually")
        print("     Use -l to list available ports")
        sys.exit(1)

    try:
        if args.patch is not None:
            g3x.change_patch(args.patch)
        else:
            interactive_mode(g3x)
    finally:
        g3x.disconnect()


if __name__ == '__main__':
    main()
