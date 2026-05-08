#!/usr/bin/env python3
"""
LoRa sniffer for RFM95W Pi Bonnet on Raspberry Pi Zero 2W.

Sweeps all LoRa parameter combinations in the 915 MHz ISM band until a
signal is detected, then captures all packets to a timestamped log file.
"""

import json
import time
import board
import busio
import digitalio
import adafruit_rfm9x
from datetime import datetime, timezone

# RFM95W Pi Bonnet pin assignments
CS_PIN   = digitalio.DigitalInOut(board.CE1)
RESET_PIN = digitalio.DigitalInOut(board.D25)
IRQ_PIN  = digitalio.DigitalInOut(board.D22)   # unused in polling mode

# 915 MHz ISM band channel plan (902–928 MHz, 200 kHz steps)
FREQUENCIES_MHZ = [f / 10 for f in range(9020, 9281, 2)]  # 902.0–928.0 MHz, 0.2 MHz step

# LoRa parameter sweep space
SPREADING_FACTORS = [7, 8, 9, 10, 11, 12]
BANDWIDTHS_HZ     = [125000, 250000, 500000]
CODING_RATES      = [5, 6, 7, 8]  # 4/5 … 4/8 (adafruit_rfm9x uses denominator)

SWEEP_LISTEN_SECS = 0.2   # how long to listen on each parameter set before moving on
RSSI_THRESHOLD    = -120  # dBm — anything above this is considered "signal present"
LOG_FILE          = datetime.now(timezone.utc).strftime("capture_%Y%m%d_%H%M%S.txt")
PARAMS_FILE       = "lora_params.json"


def save_params(freq_mhz, sf, bw_hz, cr):
    data = {"frequency_mhz": freq_mhz, "spreading_factor": sf, "bandwidth_hz": bw_hz, "coding_rate": cr}
    with open(PARAMS_FILE, "w") as f:
        json.dump(data, f, indent=2)
    print(f"[*] Parameters saved to {PARAMS_FILE}")


def init_radio(spi):
    radio = adafruit_rfm9x.RFM9x(spi, CS_PIN, RESET_PIN, 915.0)
    radio.tx_power = 5      # minimum transmit power; we're only receiving
    radio.enable_crc = True
    return radio


def configure(radio, freq_mhz, sf, bw_hz, cr):
    radio.frequency_mhz  = freq_mhz
    radio.spreading_factor = sf
    radio.signal_bandwidth = bw_hz
    radio.coding_rate      = cr


def param_label(freq_mhz, sf, bw_hz, cr):
    return f"{freq_mhz:.1f} MHz  SF{sf}  BW{bw_hz // 1000}kHz  CR4/{cr}"


def log_packet(f, params, packet, rssi, snr):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    hex_data = packet.hex()
    try:
        text_data = packet.decode("utf-8", errors="replace")
    except Exception:
        text_data = "<decode error>"
    line = (
        f"[{ts}] {params}\n"
        f"  RSSI: {rssi} dBm   SNR: {snr} dB\n"
        f"  HEX : {hex_data}\n"
        f"  TEXT: {text_data}\n"
        f"{'─' * 72}\n"
    )
    f.write(line)
    f.flush()
    print(line, end="")


def sweep_once(radio):
    """Iterate every parameter combination once; return first set that hears traffic."""
    total = len(FREQUENCIES_MHZ) * len(SPREADING_FACTORS) * len(BANDWIDTHS_HZ) * len(CODING_RATES)
    idx = 0
    for freq in FREQUENCIES_MHZ:
        for sf in SPREADING_FACTORS:
            for bw in BANDWIDTHS_HZ:
                for cr in CODING_RATES:
                    idx += 1
                    configure(radio, freq, sf, bw, cr)
                    label = param_label(freq, sf, bw, cr)
                    print(f"\r[{idx}/{total}] Trying {label}   ", end="", flush=True)

                    # Short listen window
                    packet = radio.receive(timeout=SWEEP_LISTEN_SECS, with_header=False)
                    if packet is not None:
                        print(f"\n[+] Signal found on {label}")
                        return (freq, sf, bw, cr), packet, radio.last_rssi, radio.last_snr

    return None, None, None, None


def capture_loop(radio, freq, sf, bw, cr):
    configure(radio, freq, sf, bw, cr)
    params = param_label(freq, sf, bw, cr)
    print(f"[*] Locking on {params}")
    print(f"[*] Writing packets to {LOG_FILE}")

    with open(LOG_FILE, "a") as log:
        log.write(f"\n{'=' * 72}\n")
        log.write(f"Capture session started {datetime.now(timezone.utc).isoformat()}Z\n")
        log.write(f"Parameters: {params}\n")
        log.write(f"{'=' * 72}\n\n")

        missed = 0
        max_missed = 30   # re-trigger sweep after 30 consecutive misses (~30 s)

        while True:
            packet = radio.receive(timeout=1.0, with_header=False)
            if packet is not None:
                missed = 0
                log_packet(log, params, packet, radio.last_rssi, radio.last_snr)
            else:
                missed += 1
                if missed >= max_missed:
                    print(f"\n[!] No packets for {max_missed} seconds — re-sweeping…")
                    return False   # signal caller to sweep again

    return True  # never reached unless interrupted


def main():
    spi = busio.SPI(board.SCK, MOSI=board.MOSI, MISO=board.MISO)
    radio = init_radio(spi)
    print("[*] RFM95W initialised.  Beginning parameter sweep…\n")

    while True:
        params, first_packet, rssi, snr = sweep_once(radio)
        if params is None:
            print("\n[!] Full sweep complete with no signal found.  Repeating…")
            continue

        freq, sf, bw, cr = params
        save_params(freq, sf, bw, cr)
        # Log the first packet that triggered detection
        with open(LOG_FILE, "a") as log:
            log_packet(log, param_label(freq, sf, bw, cr), first_packet, rssi, snr)

        done = capture_loop(radio, freq, sf, bw, cr)
        if done:
            break


if __name__ == "__main__":
    main()
