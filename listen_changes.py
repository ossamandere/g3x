#!/usr/bin/env python3
"""
G3X Change Listener

Listens for SysEx messages from the G3X while you interact with the pedal.
Toggle effects on/off, turn knobs, etc. and watch what messages come through.

Press Ctrl+C to exit.
"""

import mido
import time
import sys
from datetime import datetime
from g3x_midi import SYSEX_PREFIX, decode_overflow_bytes


def find_g3x_port():
    outputs = mido.get_output_names()
    for port in outputs:
        if 'zoom' in port.lower() or 'g3x' in port.lower():
            return port
    return None


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

    log_file = open('changes.log', 'w')
    log_file.write(f"G3X Change Listener - {datetime.now().isoformat()}\n\n")

    # Enter edit mode
    print("Entering edit mode...")
    output_port.send(mido.Message('sysex', data=SYSEX_PREFIX + [0x50]))
    time.sleep(0.2)

    # Drain any pending messages
    for msg in input_port.iter_pending():
        pass

    print("\n" + "=" * 70)
    print("LISTENING FOR CHANGES")
    print("=" * 70)
    print("\nToggle effects, turn knobs, switch patches on your G3X.")
    print("Messages will appear here. Press Ctrl+C to exit.\n")

    msg_count = 0

    try:
        while True:
            for msg in input_port.iter_pending():
                msg_count += 1
                timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]

                if msg.type == 'sysex':
                    data = list(msg.data)
                    hex_str = format_hex(data)

                    # Check if it's a G3X message
                    if data[0:3] == SYSEX_PREFIX:
                        cmd = data[3]
                        payload = data[4:]

                        print(f"[{timestamp}] #{msg_count} SysEx cmd=0x{cmd:02X} ({len(data)} bytes)")

                        # For short messages, show full data
                        if len(payload) <= 16:
                            print(f"  Payload: {format_hex(payload)}")

                            # Try to decode if long enough
                            if len(payload) >= 8:
                                decoded = decode_overflow_bytes(payload)
                                print(f"  Decoded: {format_hex(decoded)}")
                        else:
                            # For patch data, show summary
                            decoded = decode_overflow_bytes(payload)
                            print(f"  Payload: {len(payload)} bytes, Decoded: {len(decoded)} bytes")
                            print(f"  First 32 decoded: {format_hex(decoded[:32])}")

                        log_file.write(f"[{timestamp}] SysEx cmd=0x{cmd:02X}\n")
                        log_file.write(f"  Raw: F0 {hex_str} F7\n")
                        if len(payload) >= 8:
                            decoded = decode_overflow_bytes(payload)
                            log_file.write(f"  Decoded: {format_hex(decoded)}\n")
                        log_file.write("\n")
                    else:
                        print(f"[{timestamp}] #{msg_count} Unknown SysEx: {hex_str[:60]}...")
                        log_file.write(f"[{timestamp}] Unknown: {hex_str}\n\n")

                    print()
                    log_file.flush()

                elif msg.type == 'control_change':
                    print(f"[{timestamp}] #{msg_count} CC: ch={msg.channel} ctrl={msg.control} val={msg.value}")
                    log_file.write(f"[{timestamp}] CC: ch={msg.channel} ctrl={msg.control} val={msg.value}\n")
                    log_file.flush()

                elif msg.type == 'program_change':
                    print(f"[{timestamp}] #{msg_count} Program Change: {msg.program}")
                    log_file.write(f"[{timestamp}] Program Change: {msg.program}\n")
                    log_file.flush()

                else:
                    print(f"[{timestamp}] #{msg_count} {msg.type}: {msg}")
                    log_file.write(f"[{timestamp}] {msg.type}: {msg}\n")
                    log_file.flush()

            time.sleep(0.01)

    except KeyboardInterrupt:
        print(f"\n\nReceived {msg_count} messages. Log saved to changes.log")

    finally:
        print("Exiting edit mode...")
        output_port.send(mido.Message('sysex', data=SYSEX_PREFIX + [0x51]))
        output_port.close()
        input_port.close()
        log_file.close()


if __name__ == '__main__':
    main()
