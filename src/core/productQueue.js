const path = require('path');
const pending = new Map();

// MCP clients can dispatch tool calls in parallel. Serialize product work so
// two calls cannot both decide that the same item needs a new tab.
function withProductQueue(options, operation) {
  const key = path.resolve(options.out || 'data');
  const previous = pending.get(key) || Promise.resolve();
  const next = previous.catch(() => {}).then(operation);
  pending.set(key, next);
  next.finally(() => { if (pending.get(key) === next) pending.delete(key); }).catch(() => {});
  return next;
}

module.exports = { withProductQueue };
