## A SignalK plugin for use with JBD stlye battery management systems

Configuration requires only the name assigned to the battery (done via the standard phone app over BLE) 

The plugin can handle multiple batteries, allocating them to different busses on the vessel.

## Configuration

Add batteries, one per line. Use the name of the battery *exactly* as allocated to the battery via the app.

The default buss is "house", but this is freeform text and can be alloacted as desired. Do not duplicate IDs on the same buss!

![Settings in SignalK](https://github.com/rszemeti/jbd-plugin/blob/main/images/settings.png "Signal K settings")

The battery data is then available in SignalK as usual, for example in the instrumentpanel "webapp":
![Available Paths](https://github.com/rszemeti/jbd-plugin/blob/main/images/available.png  "Available Paths") 

## Prerequisites

This package requires Python 3 and the `bleak` package for Python. Ensure you have Python 3 installed on your system. You can download it from [python.org](https://www.python.org/downloads/).

To install `bleak`, run the following command in your Python environment:

```bash
pip install bleak

