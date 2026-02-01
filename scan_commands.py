#!/usr/bin/env python3
"""
G3X Command Scanner

Scans all possible SysEx commands (0x00-0x7F) and logs responses.
Helps discover undocumented commands and find effect on/off status.

Usage:
    python scan_commands.py [-p PORT] [-o OUTPUT_FILE]
"""

import mido
import time
import sys
import argparse
from datetime import datetime

SYSEX_PREFIX = [0x52, 0x00, 0x59]


def find_g3x_port():
    """Try to find the G3X MIDI port automatically."""
    outputs = mido.get_output_names()
    for port in outputs:
        if 'zoom' in port.lower() or 'g3x' in port.lower():
            return port
    return None


def send_sysex(output_port, input_port, data, timeout=0.15):
    """Send SysEx and capture response."""
    full_msg = SYSEX_PREFIX + data
    msg = mido.Message('sysex', data=full_msg)
    output_port.send(msg)

    time.sleep(timeout)

    responses = []
    for msg in input_port.iter_pending():
        if msg.type == 'sysex':
            responses.append(list(msg.data))

    return responses


def format_hex(data):
    """Format bytes as hex string."""
    return ' '.join(f'{b:02X}' for b in data)


def analyze_response(cmd, response):
    """Look for interesting patterns in response."""
    notes = []

    if not response:
        return notes

    # Check response command byte (usually at index 3)
    if len(response) > 3:
        resp_cmd = response[3]
        # Response is often request command - 1
        if resp_cmd == cmd - 1:
            notes.append(f"resp_cmd=0x{resp_cmd:02X} (req-1)")
        elif resp_cmd == cmd:
            notes.append(f"resp_cmd=0x{resp_cmd:02X} (echo)")
        else:
            notes.append(f"resp_cmd=0x{resp_cmd:02X}")

    # Look for sequences that might be on/off flags (6 consecutive 0x00/0x01)
    for i in range(len(response) - 5):
        window = response[i:i+6]
        if all(b in [0, 1] for b in window):
            notes.append(f"possible flags @{i}: {window}")

    # Check for ASCII text
    ascii_chars = []
    for i, b in enumerate(response):
        if 32 <= b < 127:
            ascii_chars.append((i, chr(b)))
    if len(ascii_chars) >= 4:
        # Find consecutive ASCII runs
        runs = []
        current_run = []
        last_i = -2
        for i, c in ascii_chars:
            if i == last_i + 1:
                current_run.append(c)
            else:
                if len(current_run) >= 4:
                    runs.append(''.join(current_run))
                current_run = [c]
            last_i = i
        if len(current_run) >= 4:
            runs.append(''.join(current_run))
        if runs:
            notes.append(f"ASCII: {runs}")

    return notes


def scan_commands(output_port, input_port, log_file, start=0x00, end=0x7F):
    """Scan all commands and log responses."""

    print(f"\nScanning commands 0x{start:02X} to 0x{end:02X}...")
    print("=" * 70)

    results = []

    for cmd in range(start, end + 1):
        # Send simple command (just the command byte)
        responses = send_sysex(output_port, input_port, [cmd])

        result = {
            'cmd': cmd,
            'tx': SYSEX_PREFIX + [cmd],
            'responses': responses
        }
        results.append(result)

        # Log to file
        log_file.write(f"\n{'='*70}\n")
        log_file.write(f"Command 0x{cmd:02X} ({cmd})\n")
        log_file.write(f"TX: F0 {format_hex(result['tx'])} F7\n")

        if responses:
            for i, resp in enumerate(responses):
                log_file.write(f"RX[{i}]: F0 {format_hex(resp)} F7\n")
                log_file.write(f"       Length: {len(resp)} bytes\n")

                notes = analyze_response(cmd, resp)
                if notes:
                    log_file.write(f"       Notes: {'; '.join(notes)}\n")

            # Print summary to console
            resp_len = len(responses[0]) if responses else 0
            notes = analyze_response(cmd, responses[0]) if responses else []
            note_str = f" | {'; '.join(notes)}" if notes else ""
            print(f"0x{cmd:02X}: {len(responses)} response(s), {resp_len} bytes{note_str}")
        else:
            log_file.write("RX: (no response)\n")
            print(f"0x{cmd:02X}: no response")

        log_file.flush()

    return results


def scan_with_params(output_port, input_port, log_file, cmd, param_range):
    """Scan a command with different parameter values."""
    print(f"\nScanning command 0x{cmd:02X} with params 0x00-0x{param_range:02X}...")
    print("-" * 70)

    for param in range(param_range + 1):
        responses = send_sysex(output_port, input_port, [cmd, param])

        log_file.write(f"\nCommand 0x{cmd:02X} 0x{param:02X}\n")
        log_file.write(f"TX: F0 {format_hex(SYSEX_PREFIX + [cmd, param])} F7\n")

        if responses:
            for resp in responses:
                log_file.write(f"RX: F0 {format_hex(resp)} F7 ({len(resp)} bytes)\n")
            print(f"  0x{cmd:02X} 0x{param:02X}: {len(responses[0])} bytes")
        else:
            log_file.write("RX: (no response)\n")


def main():
    parser = argparse.ArgumentParser(description='Scan G3X SysEx commands')
    parser.add_argument('-p', '--port', help='MIDI port name')
    parser.add_argument('-o', '--output', default='command_scan.log',
                        help='Output log file (default: command_scan.log)')
    parser.add_argument('--start', type=lambda x: int(x, 0), default=0x00,
                        help='Start command (default: 0x00)')
    parser.add_argument('--end', type=lambda x: int(x, 0), default=0x7F,
                        help='End command (default: 0x7F)')
    parser.add_argument('--no-edit', action='store_true',
                        help='Skip entering edit mode')
    args = parser.parse_args()

    # Find port
    port_name = args.port or find_g3x_port()
    if not port_name:
        print("Could not find G3X. Available ports:")
        print(f"  Outputs: {mido.get_output_names()}")
        print(f"  Inputs: {mido.get_input_names()}")
        sys.exit(1)

    # Open ports
    try:
        output_port = mido.open_output(port_name)
        # Find matching input
        input_port = None
        for inp in mido.get_input_names():
            if port_name.split(':')[0] in inp:
                input_port = mido.open_input(inp)
                break
        if not input_port:
            print("Could not find matching input port")
            sys.exit(1)
    except Exception as e:
        print(f"Failed to open ports: {e}")
        sys.exit(1)

    print(f"Connected to: {port_name}")

    # Open log file
    with open(args.output, 'w') as log_file:
        log_file.write(f"G3X Command Scan - {datetime.now().isoformat()}\n")
        log_file.write(f"Port: {port_name}\n")
        log_file.write(f"Range: 0x{args.start:02X} - 0x{args.end:02X}\n")

        try:
            # Enter edit mode first (required for many commands)
            if not args.no_edit:
                print("\nEntering edit mode...")
                send_sysex(output_port, input_port, [0x50])
                time.sleep(0.2)
                log_file.write("\nEntered edit mode (0x50)\n")

            # Scan all commands
            results = scan_commands(output_port, input_port, log_file,
                                   args.start, args.end)

            # Summary
            responding = [r for r in results if r['responses']]
            print(f"\n{'='*70}")
            print(f"Scan complete. {len(responding)}/{len(results)} commands responded.")
            print(f"Results saved to: {args.output}")

            # List responding commands
            if responding:
                print("\nResponding commands:")
                for r in responding:
                    resp = r['responses'][0]
                    print(f"  0x{r['cmd']:02X}: {len(resp)} bytes")

        finally:
            # Exit edit mode
            if not args.no_edit:
                print("\nExiting edit mode...")
                send_sysex(output_port, input_port, [0x51])

            output_port.close()
            input_port.close()


if __name__ == '__main__':
    main()
