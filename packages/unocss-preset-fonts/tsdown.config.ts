import { defineConfig } from 'tsdown'

export default defineConfig({
  entry: [
    './src/index.ts',
  ],
  noExternal: [
    '@proj-aijade/font-cjkfonts-allseto',
    '@proj-aijade/font-departure-mono',
    '@proj-aijade/font-xiaolai',
  ],
  dts: true,
  sourcemap: true,
})
