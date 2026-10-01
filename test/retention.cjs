// Run with node test/retention.cjs; no installed plugin dependencies required.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { EventEmitter } = require('node:events');
const { PassThrough } = require('node:stream');
let now = 1000;
const timers = new Set(), children = [], messages = [];
const context = {
  module: { exports: {} }, __dirname,
  Date: { now: () => now },
  setInterval: fn => { timers.add(fn); return fn; },
  clearInterval: fn => timers.delete(fn),
  require: name => {
    if (name === 'debug') return () => () => {};
    if (name !== 'child_process') return require(name);
    return { spawn: (command, args) => {
      assert.equal(args[3], '60');
      assert.deepEqual(Array.from(args.slice(4)), ['hci1', 'true']);
      const child = new EventEmitter();
      child.stdout = new PassThrough(); child.stderr = new PassThrough();
      child.kill = () => { child.killed = true; child.stdout.end(); };
      children.push(child); return child;
    } };
  }
};
vm.runInNewContext(fs.readFileSync(__dirname + '/../plugin/index.js', 'utf8'), context);
const plugin = context.module.exports({ debug: () => {}, handleMessage: (id, msg) => messages.push(msg) });
// IDs may repeat on different buses; freshness must remain independent.
plugin.start({ refresh: 60, staleTimeout: 300, bluetoothAdapter: 'hci1', useBluezDevices: true, batteries: [
  { id: 0, bus: 'house', name: 'House' }, { id: 0, bus: 'engine', name: 'Engine' }
] });
// Basic responses also carry cached cells; they must not refresh cell timestamps.
const basic = JSON.stringify({ 'Total Voltage': 13.4, 'Cell Voltages': [3300, 3301, 3302, 3303] });
const cells = JSON.stringify({ 'Cell Voltages': [3350, 3351, 3352, 3353] });
children[0].stdout.write(basic.slice(0, 8));
assert.equal(messages.length, 0);
children[0].stdout.write(basic.slice(8) + '\n' + cells + '\n');
children[1].stdout.write(basic + '\n');
assert.equal(messages.length, 3, 'Split and coalesced stdout lines are handled');
assert.equal(messages[1].updates[0].values[0].value, 3.35);
assert.equal(messages[1].updates[0].meta[0].value.units, 'V');
children[0].stdout.write('not JSON\n{"Cell Voltages":[]}\n{"Cell Voltages":[0,3300]}\n');
assert.equal(messages.length, 3, 'Invalid output must not publish or refresh readings');
function tick(time) { now = time; timers.forEach(fn => fn()); }
tick(61000); tick(300999);
assert.equal(messages.length, 3, 'No refreshing timestamps or premature nulls');
children[0].stdout.write(basic + '\n');
messages.length = 0;
tick(301000);
let values = messages.flatMap(m => m.updates[0].values);
assert.equal(values.filter(v => v.path.includes('.cells.')).length, 4);
assert(!values.some(v => v.path === 'electrical.batteries.house.voltage.0'));
assert(values.some(v => v.path === 'electrical.batteries.engine.voltage.0'));
const count = messages.length;
tick(306000); assert.equal(messages.length, count, 'Expiry is published once');
children[0].stdout.write(cells + '\n');
messages.length = 0;
tick(606000);
assert(messages.flatMap(m => m.updates[0].values).some(v => v.path.includes('.cells.')));
plugin.stop(); assert.equal(timers.size, 0); assert(children.every(c => c.killed));
messages.length = 0;
plugin.start({ refresh: 60, staleTimeout: 1, bluetoothAdapter: 'hci1', useBluezDevices: true,
  batteries: [{ id: 0, bus: 'house', name: 'House' }] });
children[2].emit('error', new Error('spawn python ENOENT'));
tick(725999); assert.equal(messages.length, 0, 'At least two polling intervals before expiry');
tick(726000); assert.equal(messages.length, 1);
plugin.stop(); assert.equal(timers.size, 0);
console.log('PASS: JSON framing, units, retention, independent freshness, recovery, minimum timeout, missing Python and cleanup.');
