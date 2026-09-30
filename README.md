## A SignalK plugin for use with JBD stlye battery management systems

Configuration requires only the name assigned to the battery (done via the standard phone app over BLE) 

The plugin can handle multiple batteries, allocating them to different busses on the vessel.

## Configuration

Add batteries, one per line. Use the name of the battery *exactly* as allocated to the battery via the app.

The default buss is "house", but this is freeform text and can be alloacted as desired. Do not duplicate IDs on the same buss!

Use a **60-second refresh interval**, or 30 seconds for closer observation.
Readings keep their original timestamps during connection gaps and become `null`
after the **stale timeout** (300 seconds by default, at least two refresh intervals).
Basic readings and cell voltages expire independently.

Cell voltages are in volts at the custom path
`electrical.batteries.<bus>.cells.<id>.<cell>.voltage`, with cell numbers starting at 1.

![Settings in SignalK](https://github.com/rszemeti/jbd-plugin/blob/main/images/settings.png "Signal K settings")

The battery data is then available in SignalK as usual, for example in the instrumentpanel "webapp". Note that availble capacity is always shown in Joules, temperatures are in Kelvin. 

![Available Paths](https://github.com/rszemeti/jbd-plugin/blob/main/images/available.png  "Available Paths") 

Configure the paths display as needed:

![Available Paths](https://github.com/rszemeti/jbd-plugin/blob/main/images/dashboard.png  "Dashboard") 

## Temperatures

Battery temperatures are in Kelvin.  There are multiple temperature sensors in the battery, the figure displayed is the average value calculated across all the sensors.

## Prerequisites

This package requires Python 3 and the `bleak` package for Python. Ensure you have Python 3 installed on your system. You can download it from [python.org](https://www.python.org/downloads/).

To install `bleak`, run the following command in your Python environment:

```bash
pip install bleak
```

## Signal K on a Cerbo GX

Venus OS can include Python without all its standard modules. On our Cerbo,
Python 3.12.13 was installed, but `pip` and `tomllib` were missing. Check first:

```sh
python --version
python3 --version
python3 -m pip --version
PYTHONPATH=/data/jbd-python python3 -c "import tomllib; import bleak; import dbus_fast"
```

If packages are missing, check your firmware's package feed and available space:

```sh
opkg update
opkg list | grep -E '^python3-(pip|tomllib|dbus-fast) '
df -h / /data
opkg --noaction install python3-pip python3-tomllib python3-dbus-fast
```

When those packages are available, install them:

```sh
mount -o remount,rw /
opkg install python3-pip python3-tomllib python3-dbus-fast
mount -o remount,ro /
```

We used Bleak 3.0.2 with Python 3.12.13 and dbus-fast 2.21.1. To keep Bleak on `/data`:

```sh
python3 -m pip install --target /data/jbd-python --no-deps --no-cache-dir 'bleak==3.0.2'
PYTHONPATH=/data/jbd-python python3 -c "from bleak import BleakClient, BleakScanner; from bleak.backends.bluezdbus.client import BleakClientBlueZDBus; print('Imports OK')"
```

`--no-deps` uses the dependencies installed by `opkg`; other Python/Bleak versions
may need different dependencies. Signal K's service must also have
`PYTHONPATH=/data/jbd-python` in its environment; setting it only in SSH is not enough.
Restart Signal K after changing its environment. The plugin's `python` command
must resolve to the Python installation you checked.

Firmware updates can remove packages installed on `/`. Files on `/data` normally
remain, but recheck imports and the service environment after an update.

If scanning fails, use `bluetoothctl list` to find the controller. Set **Bluetooth
adapter** to its hardware address and enable **Use known BlueZ devices** to try
existing device entries before scanning. An `hci1`-style name also works, but its
number can change after updates or reboot. These Linux options use `dbus-fast`.
Adapter selection requires Bleak 3.0 or later. Use the address reported by your own
Cerbo; a replacement controller has a different address.

