import { build } from 'vite';

await build({
  configFile: false,
  esbuild: { jsx: 'automatic' },
  build: {
    rollupOptions: {
      onwarn(warning, defaultHandler) {
        // React Flow marks its entry as a client component for framework
        // integrations. This Vite app is already a browser-only React app, so
        // Rollup correctly ignores that directive; silence only this known,
        // harmless package warning while preserving every other warning.
        if (
          warning.code === 'MODULE_LEVEL_DIRECTIVE' &&
          warning.message.includes('node_modules/@xyflow/react/') &&
          warning.message.includes('"use client"')
        ) return;
        defaultHandler(warning);
      },
    },
  },
});
