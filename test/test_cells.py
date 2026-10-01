import asyncio
import contextlib
import importlib.util
import io
import json
import sys
import types
from pathlib import Path

fake = types.ModuleType('bleak')
fake.BleakClient = object
fake.BleakScanner = object
sys.modules['bleak'] = fake
spec = importlib.util.spec_from_file_location('battery', Path(__file__).resolve().parents[1] / 'plugin/python/battery.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

def frame(command, payload):
    body = bytes([0, len(payload)]) + payload
    return bytes([0xdd, command]) + body + ((-sum(body)) & 0xffff).to_bytes(2, 'big') + b'\x77'

async def main():
    b = mod.BMS.__new__(mod.BMS)
    b.bms_data = mod.BMSData()
    b.response_buffer = bytearray()
    b.basic_received = asyncio.Event()
    b.cells_received = asyncio.Event()
    basic = bytearray(29)
    basic[0:2] = (1360).to_bytes(2, 'big')
    basic[4:6] = (26800).to_bytes(2, 'big')
    basic[6:8] = (28000).to_bytes(2, 'big')
    basic[19:23] = bytes([96, 3, 4, 3])
    basic[23:] = (3081).to_bytes(2, 'big') * 3
    basic_frame = frame(3, basic)
    voltages = [3447, 3351, 3402, 3400]
    cell_frame = frame(4, b''.join(v.to_bytes(2, 'big') for v in voltages))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        await b.notification_handler(None, basic_frame[:11])
        assert not b.basic_received.is_set()
        await b.notification_handler(None, basic_frame[11:])
        assert b.basic_received.is_set()
        # Split immediately after a payload byte equal to the frame delimiter.
        await b.notification_handler(None, cell_frame[:6])
        assert not b.cells_received.is_set()
        await b.notification_handler(None, cell_frame[6:])
        assert b.cells_received.is_set()
        b.cells_received.clear()
        bad = bytearray(cell_frame)
        bad[-2] ^= 1
        await b.notification_handler(None, bad)
        assert not b.cells_received.is_set()
        await b.notification_handler(None, basic_frame + cell_frame)
        assert b.cells_received.is_set()
        b.cells_received.clear()
        await b.notification_handler(None, frame(4, b'\x0d\x00'))
        assert not b.cells_received.is_set(), 'Reject mismatched cell count'
        await b.notification_handler(None, frame(4, b'\x0d'))
        assert not b.cells_received.is_set(), 'Reject odd payload length'
        # A valid one-temperature-sensor response is shorter than the old 34-byte minimum.
        basic[22] = 1
        await b.notification_handler(None, frame(3, basic[:25]))
        assert b.bms_data.ntc_numbers == 1
    messages = [json.loads(line) for line in out.getvalue().splitlines()]
    cells = [m for m in messages if list(m) == ['Cell Voltages']]
    assert len(cells) == 2
    assert all(m['Cell Voltages'] == voltages for m in cells)
    assert b.bms_data.cell_block_numbers == 4
    print('PASS: fragmented basic/cell frames, embedded 0x77, checksum rejection, resynchronization, and combined frames.')
    device = types.SimpleNamespace(name='Test battery', address='00:11:22:33:44:55')
    class Scanner:
        @staticmethod
        async def discover():
            return [device]
    class Client:
        def __init__(self, target):
            assert target is device, 'Pass discovered device; an address triggers another scan'
            self.is_connected = False
        async def connect(self):
            self.is_connected = True
        async def start_notify(self, uuid, callback):
            pass
    mod.BleakScanner = Scanner
    mod.BleakClient = Client
    assert await mod.BMS('Test battery').connect()
    print('PASS: connection reuses the discovered device object.')
    objects = {}
    buses = []
    class Bus:
        def __init__(self, **kwargs):
            self.closed = False
            buses.append(self)
        async def connect(self):
            pass
        async def call(self, message):
            return types.SimpleNamespace(message_type='reply', body=[objects])
        def disconnect(self):
            self.closed = True
    def module(name, **attributes):
        result = types.ModuleType(name)
        result.__dict__.update(attributes)
        sys.modules[name] = result
    module('dbus_fast.aio', MessageBus=Bus)
    module('dbus_fast.constants', BusType=types.SimpleNamespace(SYSTEM='system'), MessageType=types.SimpleNamespace(ERROR='error'))
    module('dbus_fast.message', Message=lambda **kwargs: kwargs)
    module('bleak.backends.device', BLEDevice=lambda address, name, details: types.SimpleNamespace(address=address, name=name, details=details))
    props = {'org.bluez.Device1': {key: types.SimpleNamespace(value=value) for key, value in
             {'Name': 'Test battery', 'Address': device.address}.items()}}
    objects['/org/bluez/hci0/dev_other'] = props
    objects['/org/bluez/hci1/dev_test'] = props
    b = mod.BMS('Test battery', adapter='hci1', use_bluez_devices=True)
    expected_adapter = 'hci1'
    class KnownClient(Client):
        def __init__(self, target, **kwargs):
            assert target.details['path'] == f'/org/bluez/{expected_adapter}/dev_test'
            assert kwargs == {'bluez': {'adapter': expected_adapter}}
            self.is_connected = False
    class NoScan:
        @staticmethod
        async def discover(**kwargs):
            raise AssertionError('Known device must not trigger scanning')
    mod.BleakClient = KnownClient
    mod.BleakScanner = NoScan
    assert await b.connect()
    objects['/org/bluez/hci1/dev_duplicate'] = props
    try:
        await b.known_bluez_device()
        raise AssertionError('Duplicate names must be rejected')
    except RuntimeError:
        pass
    del objects['/org/bluez/hci1/dev_duplicate']
    adapter_props = {'org.bluez.Adapter1': {
        'Address': types.SimpleNamespace(value='AA:BB:CC:DD:EE:FF')}}
    objects['/org/bluez/hci1'] = adapter_props
    b = mod.BMS('Test battery', adapter='aa:bb:cc:dd:ee:ff', use_bluez_devices=True)
    assert await b.connect()
    # Simulate controller renumbering between connections, keeping the same address.
    objects.clear()
    objects['/org/bluez/hci0'] = adapter_props
    objects['/org/bluez/hci0/dev_test'] = props
    expected_adapter = 'hci0'
    assert await b.connect()
    del objects['/org/bluez/hci0']
    try:
        await b.connect()
        raise AssertionError('A missing controller must not select another adapter')
    except RuntimeError as error:
        assert 'Bluetooth adapter' in str(error) and 'not found' in str(error)
    objects['/org/bluez/hci0'] = adapter_props
    class SelectedScanner:
        @staticmethod
        async def discover(**kwargs):
            assert kwargs == {'bluez': {'adapter': 'hci0'}}
            return [device]
    class SelectedClient(Client):
        def __init__(self, target, **kwargs):
            super().__init__(target)
            assert kwargs == {'bluez': {'adapter': 'hci0'}}
    mod.BleakScanner = SelectedScanner
    mod.BleakClient = SelectedClient
    assert await mod.BMS('Test battery', adapter='AA:BB:CC:DD:EE:FF').connect()
    assert all(bus.closed for bus in buses)
    print('PASS: adapter filtering, known-device lookup, duplicate rejection, controller renumbering, missing-controller failure, scanning by controller address, D-Bus cleanup.')

asyncio.run(main())
