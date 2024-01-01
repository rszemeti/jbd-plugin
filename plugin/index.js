const { spawn } = require('child_process');
const path = require('path');
const lastUpdateTimes = {};
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

  options.batteries.forEach(battery => {
    lastUpdateTimes[battery.id] = Date.now();
    const scriptPath = path.join(__dirname, 'python', 'ble_proc.py');
    const pythonProcess = spawn('python', ['-u', scriptPath, battery.name, options.refresh.toString()]);

    pythonProcesses.push(pythonProcess);

    pythonProcess.stdout.on('data', (data) => {
      app.debug(`Received data from Python script for battery ${battery.id}: ${data.toString().trim()}`);
      try {
        const jsonData = JSON.parse(data.toString());

        app.handleMessage(plugin.id, {
          updates: [
            {
              values: [
                {
                  path: `electrical.batteries.house.voltage.${battery.id}`,
                  value: jsonData["Total Voltage"]
                },
                {
                  path: `electrical.batteries.house.name.${battery.id}`,
                  value: battery.name
                },
                {
                  path: `electrical.batteries.house.capacity.nominal.${battery.id}`,
                  value: jsonData["Nominal Capacity J"]
                },
                {
                  path: `electrical.batteries.house.capacity.remaining.${battery.id}`,
                  value: jsonData["Residual Capacity J"]
                },
                {
                  path: `electrical.batteries.house.current.${battery.id}`, // Ensure this path is correct
                  value: jsonData["Current"]
                },
                {
                  path: `electrical.batteries.house.capacity.stateOfCharge.${battery.id}`, // Ensure this path is correct
                  value: jsonData["RSOC"]
                },
                {
                  path: `electrical.batteries.house.cycles.${battery.id}`, // Ensure this path is correct
                  value: jsonData["Cycle Life"]
                },
                {
                  path: `electrical.batteries.house.capacity.temperature.${battery.id}`, // Ensure this path is correct
                  value: jsonData["Temperature"]
                },
                {
                  path: `electrical.batteries.house.protection.${battery.id}`, // Ensure this path is correct
                  value: jsonData["Protection Status"]
                },
                {
                  path: `electrical.batteries.house.chemistry.${battery.id}`, // Ensure this path is correct
                  value: 'LiFePO4'
                }
                  
              ]
            }
          ]
        });
        lastUpdateTimes[battery.id] = Date.now();
      } catch (error) {
        app.debug(`Error parsing JSON data for battery ${battery.id}: ${error}`);
        app.debug(`Received data from Python script for battery ${battery.id}: ${data.toString().trim()}`);
      }
    });

    pythonProcess.stderr.on('data', (data) => {
      app.debug(`Python script stderr for battery ${battery.id}: ${data}`);
    });

    pythonProcess.on('close', (code) => {
      app.debug(`Python script for battery ${battery.id} process exited with code ${code}`);
    });
      
        // Function to check for stale data
    function checkForStaleData() {
      const TIMEOUT = 60000; // 1 minute timeout
      const currentTime = Date.now();

      options.batteries.forEach(battery => {
        if (currentTime - lastUpdateTimes[battery.id] > TIMEOUT) {
          // Data is stale, send update to set values to null or ignore
          app.debug(`Stale data for battery ID ${battery.id}`)
          app.handleMessage(plugin.id, {
            updates: [
              {
                values: [
                  { path: `electrical.batteries.house.voltage.${battery.id}`, value: null },
                  { path: `electrical.batteries.house.capacity.${battery.id}`, value: null },
                  // ... set other paths to null or ignore as needed
                ]
              }
            ]
          });
        }
      });
    }

    // Set an interval to periodically check for stale data
    setInterval(checkForStaleData, 5000); // Check every 5 seconds, for example
  });

  plugin.stop = function() {
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
    refresh: {
      type: 'number',
      title: 'Refresh Rate',
      description: 'How many seconds between updates',
      default: 1
    }
  }
};



    
  return plugin;
};
