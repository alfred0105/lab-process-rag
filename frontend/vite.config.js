import { spawn } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';

let testWorker;
const isolatedTestControl = {
  name: 'isolated-e2e-worker-control',
  configureServer(server) {
    const dbPath = process.env.LAB_PROCESS_DB_PATH || '';
    const isIsolatedTest = process.env.LAB_PROCESS_TESTING === '1' && path.resolve(dbPath).startsWith(path.resolve(os.tmpdir()) + path.sep);
    if (!isIsolatedTest) return;
    server.httpServer?.once('close', () => { if (testWorker && testWorker.exitCode === null) testWorker.kill('SIGTERM'); });
    server.middlewares.use('/__e2e/stop-worker', async (req, res) => {
      if (req.method !== 'POST') { res.statusCode = 405; res.end(); return; }
      if (testWorker && testWorker.exitCode === null) {
        const worker = testWorker;
        worker.kill('SIGTERM');
        await new Promise(resolve => {
          if (worker.exitCode !== null) { resolve(); return; }
          worker.once('exit', resolve);
          setTimeout(resolve, 5000);
        });
      }
      res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify({ stopped: true }));
    });
    server.middlewares.use('/__e2e/start-worker', (req, res) => {
      if (req.method !== 'POST') { res.statusCode = 405; res.end(); return; }
      if (testWorker && testWorker.exitCode === null) { res.statusCode = 409; res.end('worker already running'); return; }
      const python = process.env.LAB_PROCESS_PYTHON || 'python3';
      testWorker = spawn(python, ['-m', 'app.worker'], { cwd: process.env.LAB_PROCESS_BACKEND, env: process.env, stdio: 'ignore' });
      res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify({ started: true }));
    });
  },
  closeBundle() { if (testWorker && testWorker.exitCode === null) testWorker.kill('SIGTERM'); },
};

export default {
  esbuild: { jsx: 'automatic' },
  plugins: [isolatedTestControl],
  server: { proxy: { '/api': process.env.LAB_PROCESS_API_TARGET || 'http://localhost:8000' } },
};
