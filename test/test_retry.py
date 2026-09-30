import asyncio
import importlib.util
import sys
import types
from pathlib import Path

instances = []
recovered = asyncio.Event()

class Client:
    is_connected = True
    def __init__(self):
        self.closed = False
    async def disconnect(self):
        self.closed = True
        self.is_connected = False

class BMS:
    def __init__(self, name, **kwargs):
        self.client = Client()
        self.number = len(instances)
        instances.append(self)
    async def connect(self):
        return self.number != 0
    async def get_basic(self):
        if self.number == 1:
            raise TimeoutError()
    async def get_cells(self):
        if self.number == 2:
            raise TimeoutError()
        recovered.set()
    async def disconnect(self):
        await self.client.disconnect()

fake = types.ModuleType('battery')
fake.BMS = BMS
sys.modules['battery'] = fake
spec = importlib.util.spec_from_file_location('reader', Path(__file__).resolve().parents[1] / 'plugin/python/ble_proc.py')
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)
real_sleep = asyncio.sleep

async def quick_sleep(delay):
    await real_sleep(0.001)

async def main():
    reader.asyncio.sleep = quick_sleep
    task = asyncio.create_task(reader.read_battery_data('Test battery', 60))
    await asyncio.wait_for(recovered.wait(), 2)
    assert len(instances) == 4
    assert all(b.client.closed for b in instances[:3])
    task.cancel()
    try:
        await asyncio.wait_for(task, 2)
    except asyncio.CancelledError:
        pass
    assert instances[3].client.closed
    print('PASS: failed connection, basic timeout and cell timeout each recover with a fresh reader; failed and cancelled connections are cleaned up.')

asyncio.run(main())
