#!/usr/bin/env python3
"""
G3X Command Scanner with Parameters

Scans ALL commands (0x00-0x7F) with slot parameters (0-5) to find per-slot queries.
"""

import mido
import time
import sys
from datetime import datetime

SYSEX_PREFIX = [0x52, 0x00, 0x59]


def find_g3x_port():
    outputs = mido.get_output_names()
    for port in outputs:
        if 'zoom' in port.lower() or 'g3x' in port.lower():
            return port
    return None


def send_sysex(output_port, input_port, data, timeout=0.1):
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
    return ' '.join(f'{b:02X}' for b in data)


def main():
    port_name = find_g3x_port()
    if not port_name:
        print("Could not find G3X")
        sys.exit(1)

    output_port = mido.open_output(port_name)
    input_port = None
    for inp in mido.get_input_names():
        if port_name.split(':')[0] in inp:
            input_port = mido.open_input(inp)
            break

    if not input_port:
        print("Could not find input port")
        sys.exit(1)

    print(f"Connected to: {port_name}")

    log_file = open('param_scan.log', 'w')
    log_file.write(f"G3X Full Parameter Scan - {datetime.now().isoformat()}\n")
    log_file.write(f"Scanning all commands 0x00-0x7F with slot params 0-5\n\n")

    responding_cmds = []

    try:
        # Enter edit mode
        print("Entering edit mode...")
        send_sysex(output_port, input_port, [0x50])
        time.sleep(0.2)

        print("\n" + "=" * 70)
        print("SCANNING ALL COMMANDS (0x00-0x7F) WITH SLOT PARAMETERS (0-5)")
        print("=" * 70)

        for cmd in range(0x00, 0x80):
            log_file.write(f"\n{'='*70}\nCommand 0x{cmd:02X}\n{'='*70}\n")

            cmd_has_response = False
            slot_responses = []

            for slot in range(6):
                responses = send_sysex(output_port, input_port, [cmd, slot])
                tx_str = f"F0 {format_hex(SYSEX_PREFIX + [cmd, slot])} F7"

                if responses:
                    cmd_has_response = True
                    for resp in responses:
                        rx_str = f"F0 {format_hex(resp)} F7"
                        log_file.write(f"TX: {tx_str}\nRX: {rx_str} ({len(resp)} bytes)\n\n")
                        slot_responses.append((slot, resp))
                else:
                    log_file.write(f"TX: {tx_str}\nRX: (no response)\n\n")

            # Print summary to console
            if cmd_has_response:
                responding_cmds.append(cmd)
                print(f"\n0x{cmd:02X}: RESPONDS")
                for slot, resp in slot_responses:
                    print(f"  [{slot}] {len(resp):3d} bytes: {format_hex(resp[:20])}{'...' if len(resp) > 20 else ''}")
            else:
                # Just show progress
                if cmd % 16 == 0:
                    print(f"0x{cmd:02X}...", end="", flush=True)
                elif cmd % 16 == 15:
                    print(f" 0x{cmd:02X} (no responses)")

            log_file.flush()

        print("\n\n" + "=" * 70)
        print(f"SCAN COMPLETE - {len(responding_cmds)} commands responded")
        print("=" * 70)

        if responding_cmds:
            print("\nResponding commands:")
            for cmd in responding_cmds:
                print(f"  0x{cmd:02X}")

        print(f"\nFull results saved to param_scan.log")

        log_file.write(f"\n\n{'='*70}\nSUMMARY\n{'='*70}\n")
        log_file.write(f"Responding commands: {[f'0x{c:02X}' for c in responding_cmds]}\n")

    finally:
        print("\nExiting edit mode...")
        send_sysex(output_port, input_port, [0x51])
        output_port.close()
        input_port.close()
        log_file.close()


if __name__ == '__main__':
    main()
