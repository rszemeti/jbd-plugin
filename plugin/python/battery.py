import asyncio
import json
from bleak import BleakClient, BleakScanner

class BMS:
    UUID_RX = '0000ff01-0000-1000-8000-00805f9b34fb'  # Characteristic UUID to send commands
    UUID_TX = '0000ff02-0000-1000-8000-00805f9b34fb'  # Characteristic UUID to receive notifications

    CMD_BASIC_INFO = 0x03
    CMD_CELL_VOLTAGE = 0x04
    
    def __init__(self,name):
        self.bms_data = BMSData()
        self.device_name = name
        self.mac = None
        self.client = None
        self.response_buffer = bytearray()

    async def connect(self):
        devices = await BleakScanner.discover()

        if self.mac is None:
            for device in devices:
                if device.name == self.device_name:
                    self.mac = device.address
                    break

        if self.mac is None:
            print(f"Device with name {self.device_name} not found")
            return

        self.client = BleakClient(self.mac)
        try:
            await self.client.connect()
            if not self.client.is_connected:
                print(f"Failed to connect to {device_address}")
                return False
        except Exception as e:
            print(f"Connection failed: {e}")
            return False

        await self.client.start_notify(self.UUID_RX, self.notification_handler)
        return True

    def jbd_command(self,command: int):
        return bytes([0xDD, 0xA5, command, 0x00, 0xFF, 0xFF - (command - 1), 0x77])

    async def notification_handler(self, sender, data):

        self.response_buffer.extend(data)

        # Check if the buffer ends with the 'w' delimiter
        if self.response_buffer.endswith(b'w'):
            # Extract the command value
            command = self.response_buffer[1]

            # Copy and clear the buffer
            complete_message = self.response_buffer[:]
            self.response_buffer = bytearray()

            # Determine which parsing function to call
            if command == self.CMD_BASIC_INFO:
                self.parse_info(complete_message)
            elif command == self.CMD_CELL_VOLTAGE:
                self.parse_cells(complete_message)

    def parse_info(self,buf):
        # Implement the logic to parse info messages
        # print("Parsing info:", buf)
        self.bms_data.parse_data(buf)
        print(self.bms_data.to_json())

    def parse_cells(self,buf):
        # Implement the logic to parse cell messages
        # print("Parsing cells:", buf)
        self.bms_data.parse_cell_data(buf)
        print(self.bms_data.to_json())

    async def send_command(self,client, command):
        await self.client.write_gatt_char(self.UUID_TX, command, response=False)

    async def get_basic(self):
        await self.send_command(self.client, self.jbd_command(self.CMD_BASIC_INFO))

    async def get_cells(self):
        await self.send_command(self.client, self.jbd_command(self.CMD_CELL_VOLTAGE))
 

    async def disconnect(self):
        if self.client.is_connected:
            await self.client.stop_notify(self.UUID_RX)
        self.client.disconnect()

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
        if len(self.raw_data) < 34:  # Check minimum length
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
        return json.dumps(data, indent=4)

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

        

