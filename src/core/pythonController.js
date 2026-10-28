const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');

function runPython(command, args) {
  const root = path.resolve(__dirname, '../..');
  const executable = process.env.HUOYAN_PYTHON || path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  if (!fs.existsSync(executable)) throw new Error('HuoYan Python environment is missing. Create .venv and install requirements.txt.');
  return new Promise((resolve, reject) => {
    const child = spawn(executable, ['-X', 'utf8', path.join(root, 'huoyan.py'), 'dispatch'], {
      cwd: process.cwd(), windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env, NO_PROXY: [process.env.NO_PROXY, '127.0.0.1,localhost,::1'].filter(Boolean).join(',') }
    });
    let stdout = '', stderr = '';
    const timer = setTimeout(() => { child.kill(); reject(new Error('Python browser operation timed out; no automatic retry.')); }, 300000);
    child.on('error', error => { clearTimeout(timer); reject(error); });
    child.stdout.on('data', chunk => { stdout += chunk; if (stdout.length > 64 * 1024 * 1024) child.kill(); });
    child.stderr.on('data', chunk => { if (stderr.length < 4000) stderr += chunk; });
    child.on('close', code => {
      clearTimeout(timer);
      let result;
      try { result = JSON.parse(stdout); }
      catch { return reject(new Error('Python controller returned no valid JSON. Check the Python environment.')); }
      if (code !== 0 || result.ok === false) {
        const error = new Error(result.error || `Python controller exited with code ${code}`);
        error.exitCode = code || 1;
        return reject(error);
      }
      resolve(result);
    });
    child.stdin.on('error', () => {});
    child.stdin.end(JSON.stringify({ command, args }));
  });
}

module.exports = { runPython };
