import asyncio
import sys
from battery import BMS

RETRY_DELAY = 30  # seconds


async def read_battery_data(address, delay, adapter='', use_bluez_devices=False):
    while True:
        battery = BMS(address, adapter=adapter, use_bluez_devices=use_bluez_devices)
        try:
            if not await asyncio.wait_for(battery.connect(), timeout=60):
                raise ConnectionError("Battery connection failed")
            while battery.client.is_connected:
                await battery.get_basic()
                await battery.get_cells()
                await asyncio.sleep(delay)
        except Exception as e:
            print(f"{type(e).__name__}: {e}; retrying in {RETRY_DELAY}s", file=sys.stderr)
        finally:
            try:
                await asyncio.wait_for(battery.disconnect(), timeout=10)
            except Exception as e:
                print(f"Disconnect failed: {e}", file=sys.stderr)
        await asyncio.sleep(RETRY_DELAY)


def main():
    if len(sys.argv) not in (3, 5):
        raise SystemExit("Usage: ble_proc.py NAME DELAY_SECONDS [ADAPTER USE_BLUEZ_DEVICES]")
    delay = float(sys.argv[2])
    if delay <= 0:
        raise SystemExit("DELAY_SECONDS must be positive")
    adapter = sys.argv[3] if len(sys.argv) == 5 else ''
    use_bluez_devices = len(sys.argv) == 5 and sys.argv[4] == 'true'
    if use_bluez_devices and (not adapter or not sys.platform.startswith('linux')):
        raise SystemExit("Known BlueZ devices require Linux and an explicit adapter, such as hci1")
    if ':' in adapter and not sys.platform.startswith('linux'):
        raise SystemExit("Selecting a Bluetooth adapter by hardware address requires Linux")
    asyncio.run(read_battery_data(sys.argv[1], delay, adapter, use_bluez_devices))


if __name__ == "__main__":
    main()
