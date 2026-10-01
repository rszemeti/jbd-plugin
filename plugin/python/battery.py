import asyncio
import json
import sys
from bleak import BleakClient, BleakScanner

class BMS:
    UUID_RX = '0000ff01-0000-1000-8000-00805f9b34fb'  # Characteristic UUID to send commands
    UUID_TX = '0000ff02-0000-1000-8000-00805f9b34fb'  # Characteristic UUID to receive notifications

    CMD_BASIC_INFO = 0x03
    CMD_CELL_VOLTAGE = 0x04
    
    def __init__(self,name, adapter='', use_bluez_devices=False):
        self.adapter = adapter
        self.adapter_address = adapter if ':' in adapter else None
        self.use_bluez_devices = use_bluez_devices
        self.bms_data = BMSData()
        self.device_name = name
        self.mac = None
        self.client = None
        self.response_buffer = bytearray()
        self.basic_received = asyncio.Event()
        self.cells_received = asyncio.Event()

    async def known_bluez_device(self):
        from dbus_fast.aio import MessageBus
        from dbus_fast.constants import BusType, MessageType
        from dbus_fast.message import Message
        from bleak.backends.device import BLEDevice
        bus = MessageBus(bus_type=BusType.SYSTEM)
        try:
            await asyncio.wait_for(bus.connect(), timeout=10)
            reply = await asyncio.wait_for(bus.call(Message(
                destination='org.bluez', path='/',
                interface='org.freedesktop.DBus.ObjectManager',
                member='GetManagedObjects')), timeout=10)
            if reply.message_type == MessageType.ERROR:
                raise RuntimeError(str(reply.error_name) + ': ' + str(reply.body))
            objects = reply.body[0]
            if self.adapter_address:
                # Resolve the hardware address each time; hci numbers can change after reboot.
                self.adapter = None
                for adapter_path, interfaces in objects.items():
                    props = interfaces.get('org.bluez.Adapter1', {})
                    address = props.get('Address')
                    if address and address.value.lower() == self.adapter_address.lower():
                        self.adapter = adapter_path.rsplit('/', 1)[-1]
                        break
                if self.adapter is None:
                    raise RuntimeError(f'Bluetooth adapter {self.adapter_address} not found')
            if not self.use_bluez_devices:
                return None
            matches = []
            for device_path, interfaces in objects.items():
                if not device_path.startswith('/org/bluez/' + self.adapter + '/'):
                    continue
                raw = interfaces.get('org.bluez.Device1')
                if raw is None:
                    continue
                props = {key: value.value for key, value in raw.items()}
                if props.get('Name') == self.device_name:
                    matches.append(BLEDevice(props['Address'], props.get('Name'),
                                             {'path': device_path, 'props': props}))
            if len(matches) > 1:
                raise RuntimeError('Multiple devices have this name; use unique battery names')
            return matches[0] if matches else None
        finally:
            bus.disconnect()

    async def connect(self):
        device = await self.known_bluez_device() if self.use_bluez_devices or self.adapter_address else None
        kwargs = {'bluez': {'adapter': self.adapter}} if self.adapter else {}
        if device is None:
            scan_kwargs = dict(kwargs)
            if self.use_bluez_devices:
                scan_kwargs['bluez'] = {'adapter': self.adapter, 'filters': {'DuplicateData': True}}
            devices = await BleakScanner.discover(**scan_kwargs)
            matches = [device for device in devices if device.name == self.device_name]
            if len(matches) > 1:
                raise RuntimeError('Multiple devices have this name; use unique battery names')
            device = matches[0] if matches else None
            if device is None and self.use_bluez_devices:
                device = await self.known_bluez_device()
        if device is None:
            print(f"Device with name {self.device_name} not found", file=sys.stderr)
            return

        self.mac = device.address
        self.client = BleakClient(device, **kwargs)
        try:
            await self.client.connect()
            if not self.client.is_connected:
                print(f"Failed to connect to {self.mac}", file=sys.stderr)
                return False
        except Exception as e:
            print(f"Connection failed: {e}", file=sys.stderr)
            return False

        await self.client.start_notify(self.UUID_RX, self.notification_handler)
        return True

    def jbd_command(self,command: int):
        return bytes([0xDD, 0xA5, command, 0x00, 0xFF, 0xFF - (command - 1), 0x77])

    async def notification_handler(self, sender, data):
        self.response_buffer.extend(data)
        while self.response_buffer:
            if self.response_buffer[0] != 0xDD:
                del self.response_buffer[0]
                continue
            if len(self.response_buffer) < 4:
                return
            length = self.response_buffer[3]
            if len(self.response_buffer) < length + 7:
                return
            frame = bytes(self.response_buffer[:length + 7])
            checksum = (-sum(frame[2:4 + length])) & 0xFFFF
            if frame[-1] != 0x77 or int.from_bytes(frame[-3:-1], 'big') != checksum:
                del self.response_buffer[0]
                continue
            del self.response_buffer[:length + 7]
            if frame[2] != 0:
                continue
            if frame[1] == self.CMD_BASIC_INFO:
                if length < 23 or not 1 <= frame[25] <= 32 or length < 23 + 2 * frame[26]:
                    continue
                self.parse_info(frame)
                self.basic_received.set()
            elif frame[1] == self.CMD_CELL_VOLTAGE:
                if not length or length % 2 or length // 2 != self.bms_data.cell_block_numbers:
                    continue
                self.parse_cells(frame)
                self.cells_received.set()

    def parse_info(self,buf):
        # Implement the logic to parse info messages
        # print("Parsing info:", buf)
        self.bms_data.parse_data(buf)
        print(self.bms_data.to_json())

    def parse_cells(self,buf):
        cells = self.bms_data.parse_cell_data(buf)
        print(json.dumps({"Cell Voltages": cells}))

    async def send_command(self,client, command):
        await self.client.write_gatt_char(self.UUID_TX, command, response=False)

    async def get_basic(self):
        self.basic_received.clear()
        await self.send_command(self.client, self.jbd_command(self.CMD_BASIC_INFO))
        await asyncio.wait_for(self.basic_received.wait(), timeout=10)

    async def get_cells(self):
        self.cells_received.clear()
        await self.send_command(self.client, self.jbd_command(self.CMD_CELL_VOLTAGE))
        await asyncio.wait_for(self.cells_received.wait(), timeout=10)
 

    async def disconnect(self):
        if self.client is not None:
            await self.client.disconnect()

class BMSData:
    def __init__(self):
        self.total_voltage = None
        self.current = None
        self.residual_capacity = None
        self.nominal_capacity = None
        self.cycle_life = None
        self.product_date = None
        self.balance_status = None
        self.balance_status_high = None
        self.protection_status = None
        self.version = None
        self.rsoc = None
        self.fet_control_status = None
        self.cell_block_numbers = None
        self.ntc_numbers = None
        self.ntc_contents = None
        self.cell_voltages = []

    def parse_cell_data(self, data):
        self.raw_cell_data = data
        self.cell_voltages = []
        for i in range(4, len(data) - 3, 2):  # Skip header and checksum, iterate through cell voltages
            # Each cell voltage is 2 bytes, high byte first
            cell_voltage = int.from_bytes(data[i:i+2], 'big')
            self.cell_voltages.append(cell_voltage)

        return self.cell_voltages

    def parse_data(self,data):
        self.raw_data = data
        if len(self.raw_data) < 30:  # Check minimum length
            print("Incomplete data")
            return
        # Check for start byte and status byte
        if self.raw_data[0] != 0xDD or self.raw_data[2] != 0x00:
            print("Invalid response or error")
            return 0

        # Parse fields based on the spec
        self.total_voltage = int.from_bytes(self.raw_data[4:6], 'big') /100.0  # in V
        self.current = int.from_bytes(self.raw_data[6:8], 'big', signed=True) /100.0  # in A
        self.residual_capacity = int.from_bytes(self.raw_data[8:10], 'big') /100.0  # in Ah
        self.nominal_capacity = int.from_bytes(self.raw_data[10:12], 'big') /100.0  # in Ah
        self.cycle_life = int.from_bytes(self.raw_data[12:14], 'big')
        self.product_date = self.parse_date(self.raw_data[14:16])
        self.balance_status = int.from_bytes(self.raw_data[16:18], 'big')
        self.balance_status_high = int.from_bytes(self.raw_data[18:20], 'big')
        self.protection_status = int.from_bytes(self.raw_data[20:22], 'big')
        self.version = self.raw_data[22]
        self.rsoc = int(self.raw_data[23])/100
        self.fet_control_status = self.raw_data[24]
        self.cell_block_numbers = self.raw_data[25]
        self.ntc_numbers = self.raw_data[26]
        self.ntc_contents = self.parse_ntc(self.raw_data[27:27 + 2 * self.ntc_numbers])

    def get_temp(self):
        if self.ntc_numbers > 0:
            temp=0.0
            for t in self.ntc_contents:
                temp += t
            temp = temp/self.ntc_numbers
            temp += 273.15
            return temp
        else:
            return None

    def to_json(self):
        data = {
            "Total Voltage": self.total_voltage,
            "Current": f"{self.current}",
            "Residual Capacity": self.residual_capacity,
            "Residual Capacity J": self.residual_capacity * self.total_voltage *3600,
            "Nominal Capacity": self.nominal_capacity,
            "Nominal Capacity J": self.nominal_capacity * self.total_voltage * 3600,
            "Cycle Life": self.cycle_life,
            "Product Date": self.product_date,
            "Balance Status": self.balance_status,
            "Balance Status High": self.balance_status_high,
            "Protection Status": self.protection_status,
            "Version": self.version,
            "RSOC": self.rsoc,
            "FET Control Status": self.fet_control_status,
            "Cell Block Numbers": self.cell_block_numbers,
            "NTC Numbers": self.ntc_numbers,
            "NTC Contents": self.ntc_contents,
            "Temperature": self.get_temp(),
            "Cell Voltages": self.cell_voltages  # Assuming this is already a list
        }
        return json.dumps(data)

    @staticmethod
    def parse_date(data):
        # Parse the date field according to the provided spec
        year = 2000 + (data[0] >> 1)
        month = ((data[0] & 0x01) << 3) | (data[1] >> 5)
        day = data[1] & 0x1F
        return f"{year}-{month:02d}-{day:02d}"

    @staticmethod
    def parse_ntc(data):
        # Parse NTC contents
        ntc_values = []
        for i in range(0, len(data), 2):
            temp = int.from_bytes(data[i:i+2], 'big') - 2731
            ntc_values.append(temp / 10)  # in Celsius
        return ntc_values

    def __str__(self):
        cell_voltages_str = ', '.join(f"{voltage}mV" for voltage in self.cell_voltages)
        return (f"Total Voltage: {self.total_voltage}mV, Current: {self.current}mA, "
                f"Residual Capacity: {self.residual_capacity}mAh, Nominal Capacity: {self.nominal_capacity}mAh, "
                f"Cycle Life: {self.cycle_life}, Product Date: {self.product_date}, "
                f"Balance Status: {self.balance_status}, Balance Status High: {self.balance_status_high}, "
                f"Protection Status: {self.protection_status}, Version: {self.version}, RSOC: {self.rsoc}%, "
                f"FET Control Status: {self.fet_control_status}, Cell Block Numbers: {self.cell_block_numbers}, "
                f"NTC Numbers: {self.ntc_numbers}, NTC Contents: {self.ntc_contents}, "
                f"Cell Voltages: [{cell_voltages_str}]")

        

