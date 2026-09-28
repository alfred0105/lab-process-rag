import { build } from 'vite';

await build({
  configFile: false,
  esbuild: { jsx: 'automatic' },
});
