#!/usr/bin/env python3
"""
LoRa packet logger for RFM95W Pi Bonnet.

Reads LoRa parameters from lora_params.json (written by sniffer.py) and
captures all packets to a timestamped log file with RSSI and SNR.
Terminal display is a static rolling window — redrawn in-place on each packet.
"""

import json
import os
import sys
import board
import busio
import digitalio
import adafruit_rfm9x
from collections import deque
from datetime import datetime, timezone

PARAMS_FILE   = "lora_params.json"
LOG_FILE      = datetime.now(timezone.utc).strftime("capture_%Y%m%d_%H%M%S.txt")
DISPLAY_ROWS  = 20   # number of packet lines shown in the static window

CS_PIN    = digitalio.DigitalInOut(board.CE1)
RESET_PIN = digitalio.DigitalInOut(board.D25)

# ANSI helpers
CLEAR_SCREEN  = "\033[2J\033[H"   # clear + move cursor to top-left
HIDE_CURSOR   = "\033[?25l"
SHOW_CURSOR   = "\033[?25h"
BOLD          = "\033[1m"
RESET_STYLE   = "\033[0m"


def load_params():
    try:
        with open(PARAMS_FILE) as f:
            data = json.load(f)
        return (
            float(data["frequency_mhz"]),
            int(data["spreading_factor"]),
            int(data["bandwidth_hz"]),
            int(data["coding_rate"]),
        )
    except FileNotFoundError:
        print(f"[!] {PARAMS_FILE} not found — run sniffer.py first to discover parameters.")
        sys.exit(1)
    except KeyError as e:
        print(f"[!] {PARAMS_FILE} is missing field {e}.")
        sys.exit(1)


def param_label(freq_mhz, sf, bw_hz, cr):
    return f"{freq_mhz:.1f} MHz  SF{sf}  BW{bw_hz // 1000}kHz  CR4/{cr}"


def terminal_width():
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80


def redraw(params, lines, count):
    width = terminal_width()
    header = f" LoRa Sniffer — {params} "
    footer = f" {count} packet{'s' if count != 1 else ''} captured  |  {LOG_FILE} "

    out = [CLEAR_SCREEN]
    out.append(f"{BOLD}{header.center(width, '─')}{RESET_STYLE}\n")
    for line in lines:
        out.append(line + "\n")
    # pad empty rows so the footer stays in a fixed position
    for _ in range(DISPLAY_ROWS - len(lines)):
        out.append("\n")
    out.append(f"{BOLD}{footer.center(width, '─')}{RESET_STYLE}\n")
    print("".join(out), end="", flush=True)


def main():
    freq, sf, bw, cr = load_params()
    params = param_label(freq, sf, bw, cr)

    spi = busio.SPI(board.SCK, MOSI=board.MOSI, MISO=board.MISO)
    radio = adafruit_rfm9x.RFM9x(spi, CS_PIN, RESET_PIN, freq)
    radio.tx_power         = 5
    radio.enable_crc       = True
    radio.spreading_factor = sf
    radio.signal_bandwidth = bw
    radio.coding_rate      = cr

    lines   = deque(maxlen=DISPLAY_ROWS)
    count   = 0

    print(HIDE_CURSOR, end="", flush=True)
    try:
        with open(LOG_FILE, "a") as log:
            log.write(f"\n{'=' * 72}\n")
            log.write(f"Listen session started {datetime.now(timezone.utc).isoformat()}Z\n")
            log.write(f"Parameters: {params}\n")
            log.write(f"{'=' * 72}\n\n")

            redraw(params, lines, count)

            while True:
                packet = radio.receive(timeout=1.0, with_header=False)
                if packet is None:
                    continue

                ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
                try:
                    text = packet.decode("utf-8", errors="replace")
                except Exception:
                    text = "<decode error>"

                entry = f"RSSI: {radio.last_rssi} dBm  SNR: {radio.last_snr} dB  [{ts}]  {text}"
                log.write(entry + "\n")
                log.flush()

                lines.append(entry)
                count += 1
                redraw(params, lines, count)

    except KeyboardInterrupt:
        pass
    finally:
        print(SHOW_CURSOR, end="", flush=True)
        print()


if __name__ == "__main__":
    main()
