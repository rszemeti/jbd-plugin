import asyncio
import sys
from battery import BMS

MAX_RETRIES = 5
RETRY_DELAY = 30  # seconds

async def read_battery_data(address, delay):
    battery = BMS(address)

    # Retry loop for connecting
    for attempt in range(MAX_RETRIES):
        try:
            await battery.connect()
            if battery.client.is_connected:
                #print("Connected to the battery.")
                break
        except Exception as e:
            print(f"Failed to connect: {e}")
        if attempt < MAX_RETRIES - 1:
            print(f"Retrying in {RETRY_DELAY} seconds...")
            await asyncio.sleep(RETRY_DELAY)
        else:
            print("Maximum connection attempts reached. Exiting.")
            return

    try:
        while True:
            await battery.get_basic()
            await asyncio.sleep(delay)
            # The SignalK schema has no standard for individual cell voltages
            # They could be enabled and distributed with meta inf, but meh.
            #await battery.get_cells()
            #await asyncio.sleep(delay)

    finally:
        await battery.disconnect()

def main():
    if len(sys.argv) != 3:
        print("Usage: python foo.py <NAME> <DELAY_IN_SECONDS>")
        return

    device_address = sys.argv[1]
    delay = float(sys.argv[2])

    loop = asyncio.get_event_loop()
    loop.run_until_complete(read_battery_data(device_address, delay))

if __name__ == "__main__":
    main()
