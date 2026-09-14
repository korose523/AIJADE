// Build script: zip the Jade maid Live2D model folder into jade_maid.zip.
//
// Run:  node scripts/build-jade-maid-zip.mjs
//
// The zip mirrors the existing Hiyori preset convention
// (packages/stage-ui/src/assets/live2d/models/*.zip). After the real
// Cubism binaries (jade_maid.moc3 + jade_maid_texture_00.png) are dropped
// into the folder, re-run this script to refresh the zip.
//
// NOTE: jszip is resolved from the pnpm store (it is not hoisted to the
// workspace root node_modules). Adjust the path below if the version moves.

import { readdir, readFile, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const repoRoot = join(__dirname, '..')

const JSZIP_URL = pathToFileURL('H:/AIJADE/node_modules/.pnpm/jszip@3.10.1/node_modules/jszip/lib/index.js').href
const { default: JSZip } = await import(JSZIP_URL)

const SRC_DIR = join(repoRoot, 'packages/stage-ui/src/assets/live2d/models/jade_maid')
const OUT_ZIP = join(repoRoot, 'packages/stage-ui/src/assets/live2d/models/jade_maid.zip')

async function listFiles(dir, base = '') {
  const out = []
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const rel = base ? `${base}/${entry.name}` : entry.name
    const abs = join(dir, entry.name)
    if (entry.isDirectory())
      out.push(...await listFiles(abs, rel))
    else if (entry.isFile())
      out.push(rel)
  }
  return out
}

const files = await listFiles(SRC_DIR)
console.log(`[build-jade-maid-zip] Found ${files.length} files in jade_maid/`)

const zip = new JSZip()
for (const rel of files) {
  const buf = await readFile(join(SRC_DIR, rel))
  zip.file(rel, buf)
  console.log(`  + ${rel} (${buf.length} bytes)`)
}

const content = await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE', compressionOptions: { level: 6 } })
await writeFile(OUT_ZIP, content)
console.log(`[build-jade-maid-zip] Wrote ${OUT_ZIP} (${content.length} bytes)`)
