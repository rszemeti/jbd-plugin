const { spawn } = require('child_process');
const path = require('path');
const readline = require('readline');
const id = 'jbd-plugin';
const debug = require('debug')(id)

module.exports = function(app) {
  var plugin = {};
  var pythonProcess;
    
  plugin.id = id;
  plugin.name = 'JBD/Fogstar Battery Plugin';
  plugin.description = 'Connects to multiple JBD style batteries over BLE';
    
plugin.start = function(options, restartPlugin) {
  app.debug("Plugin starting JBD")
  app.debug(options)

  // Store python processes in an array to manage them later
  const pythonProcesses = [];
  const timers = [];
  const refresh = Number(options.refresh) > 0 ? Number(options.refresh) : 60;
  const staleTimeout = Number(options.staleTimeout) > 0 ? Number(options.staleTimeout) : 300;
  const timeoutMs = Math.max(staleTimeout, refresh * 2) * 1000;

  options.batteries.forEach(battery => {
    let lastBasicUpdate = Date.now();
    let lastCellUpdate;
    let basicExpired = false;
    let cellsExpired = false;
    let cellPaths = [];
    const scriptPath = path.join(__dirname, 'python', 'ble_proc.py');
    const pythonProcess = spawn('python', ['-u', scriptPath, battery.name, refresh.toString(),
      options.bluetoothAdapter || '', options.useBluezDevices ? 'true' : 'false']);

    pythonProcesses.push(pythonProcess);

    const lines = readline.createInterface({ input: pythonProcess.stdout });
    lines.on('line', (data) => {
      app.debug(`Received data from Python script for battery ${battery.id}: ${data.toString().trim()}`);
      try {
        const jsonData = JSON.parse(data.toString());
        if (Object.keys(jsonData).length === 1 && Array.isArray(jsonData["Cell Voltages"])) {
          const cells = jsonData["Cell Voltages"];
          if (!cells.length || !cells.every(v => Number.isFinite(v) && v > 0)) return;
          const values = cells.map((millivolts, i) => ({
            path: `electrical.batteries.${battery.bus}.cells.${battery.id}.${i + 1}.voltage`,
            value: millivolts / 1000
          }));
          cellPaths = values.map(entry => entry.path);
          app.handleMessage(plugin.id, { updates: [{
            meta: values.map((entry, i) => ({ path: entry.path,
              value: { units: 'V', displayName: `${battery.name} cell ${i + 1}` } })),
            values
          }] });
          lastCellUpdate = Date.now();
          cellsExpired = false;
          return;
        }
        if (!Number.isFinite(jsonData["Total Voltage"])) return;

        app.handleMessage(plugin.id, {
          updates: [
            {
              values: [
                {
                  path: `electrical.batteries.${battery.bus}.voltage.${battery.id}`,
                  value: jsonData["Total Voltage"]
                },
                {
                  path: `electrical.batteries.${battery.bus}.name.${battery.id}`,
                  value: battery.name
                },
                {
                  path: `electrical.batteries.${battery.bus}.capacity.nominal.${battery.id}`,
                  value: jsonData["Nominal Capacity J"]
                },
                {
                  path: `electrical.batteries.${battery.bus}.capacity.remaining.${battery.id}`,
                  value: jsonData["Residual Capacity J"]
                },
                {
                  path: `electrical.batteries.${battery.bus}.current.${battery.id}`, // Ensure this path is correct
                  value: jsonData["Current"]
                },
                {
                  path: `electrical.batteries.${battery.bus}.capacity.stateOfCharge.${battery.id}`, // Ensure this path is correct
                  value: jsonData["RSOC"]
                },
                {
                  path: `electrical.batteries.${battery.bus}.cycles.${battery.id}`, // Ensure this path is correct
                  value: jsonData["Cycle Life"]
                },
                {
                  path: `electrical.batteries.${battery.bus}.temperature.${battery.id}`, // Ensure this path is correct
                  value: jsonData["Temperature"]
                },
                {
                  path: `electrical.batteries.${battery.bus}.protection.${battery.id}`, // Ensure this path is correct
                  value: jsonData["Protection Status"]
                },
                {
                  path: `electrical.batteries.${battery.bus}.chemistry.${battery.id}`, // Ensure this path is correct
                  value: 'LiFePO4'
                }
                  
              ]
            }
          ]
        });
        lastBasicUpdate = Date.now();
        basicExpired = false;
      } catch (error) {
        app.debug(`Error parsing JSON data for battery ${battery.id}: ${error}`);
        app.debug(`Received data from Python script for battery ${battery.id}: ${data.toString().trim()}`);
      }
    });

    pythonProcess.stderr.on('data', (data) => {
      app.debug(`Python script stderr for battery ${battery.id}: ${data}`);
    });

    pythonProcess.on('error', (error) => {
      app.debug(`Cannot start Python reader for battery ${battery.id}: ${error}`);
    });

    pythonProcess.on('close', (code) => {
      app.debug(`Python script for battery ${battery.id} process exited with code ${code}`);
    });
      
    // Keep the original timestamps during gaps; expire each response type separately.
    timers.push(setInterval(() => {
      const now = Date.now();
      const values = [];
      if (!basicExpired && now - lastBasicUpdate >= timeoutMs) {
        basicExpired = true;
        for (const field of ['voltage', 'current', 'capacity.nominal', 'capacity.remaining',
                            'capacity.stateOfCharge', 'cycles', 'temperature', 'protection']) {
          values.push({ path: `electrical.batteries.${battery.bus}.${field}.${battery.id}`, value: null });
        }
      }
      if (!cellsExpired && lastCellUpdate !== undefined && now - lastCellUpdate >= timeoutMs) {
        cellsExpired = true;
        values.push(...cellPaths.map(path => ({ path, value: null })));
      }
      if (values.length) app.handleMessage(plugin.id, { updates: [{ values }] });
    }, 5000));
  });

  plugin.stop = function() {
    timers.forEach(clearInterval);
    pythonProcesses.forEach(process => {
      if (process) {
        process.kill();
      }
    });
  };
};


plugin.schema = {
  type: 'object',
  properties: {
    batteries: {
      type: 'array',
      title: 'Batteries',
      items: {
        type: 'object',
        required: ['name', 'bus', 'id'],
        properties: {
          name: {
            type: 'string',
            title: 'Name'
          },
          bus: {
            type: 'string',
            title: 'Bus'
          },
          id: {
            type: 'number',
            title: 'Battery ID'
          }
        }
      }
    },
    bluetoothAdapter: {
      type: 'string',
      title: 'Bluetooth adapter (Linux)',
      description: 'Leave blank for the default adapter, or use hci1 or a controller hardware address (stable across hci renumbering)',
      default: ''
    },
    useBluezDevices: {
      type: 'boolean',
      title: 'Use known BlueZ devices (Linux)',
      description: 'Look up existing devices before scanning; requires an explicit Bluetooth adapter',
      default: false
    },
    staleTimeout: {
      type: 'number',
      title: 'Stale timeout (seconds)',
      description: 'Retain readings for this long without a response (at least two refresh intervals)',
      minimum: 1,
      default: 300
    },
    refresh: {
      type: 'number',
      title: 'Refresh Rate',
      description: 'Seconds between reads; 60 recommended, or 30 for closer observation',
      minimum: 1,
      default: 60
    }
  }
};



    
  return plugin;
};
