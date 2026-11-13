// Isolated renderer: native UI leaves, React/Query/nanostores; synthetic host/data.
// HERMES_DESKTOP_SOURCE_ROOT=<core> ROUTER_RENDERER_OUT=<scratch> node scripts/render_execution_fixture.mjs
import {createRequire} from 'node:module'
import {readFile,writeFile,mkdir,copyFile,readdir} from 'node:fs/promises'
import {fileURLToPath} from 'node:url'
import path from 'node:path'
import {createHash} from 'node:crypto'
import {execFileSync} from 'node:child_process'
const core=process.env.HERMES_DESKTOP_SOURCE_ROOT,out=process.env.ROUTER_RENDERER_OUT
if(!core||!out||!path.isAbsolute(core)||!path.isAbsolute(out))throw Error('Explicit absolute core and scratch output paths are required')
const rel=path.relative(path.resolve(core),path.resolve(out))
if(!rel.startsWith('..'+path.sep)&&rel!=='..'&&!path.isAbsolute(rel))throw Error('Fixture output must not modify the core checkout')
const repo=fileURLToPath(new URL('../',import.meta.url)),fixtures=path.join(repo,'scripts/fixtures')
const app=path.join(core,'apps/desktop'),require=createRequire(path.join(app,'package.json'))
const {build}=require('esbuild'),source=path.join(repo,'desktop/plugin.js')
const assets=path.join(app,'dist/assets'),mainCSS=(await readdir(assets)).filter(name=>/^main-.*\.css$/.test(name))
if(mainCSS.length!==1)throw Error('Native built CSS generation is absent or ambiguous')
const css=await readFile(path.join(assets,mainCSS[0]))
await mkdir(out,{recursive:true})
await build({entryPoints:[path.join(fixtures,'fixture-operator-entry.jsx')],outfile:path.join(out,'fixture-operator.js'),bundle:true,format:'esm',platform:'browser',jsx:'automatic',
 alias:{'@hermes/plugin-sdk':path.join(fixtures,'fixture-operator-shim.jsx'),'@':path.join(app,'src'),react:path.dirname(require.resolve('react/package.json')),'react-dom':path.dirname(require.resolve('react-dom/package.json'))},
 nodePaths:[path.join(core,'node_modules'),path.join(app,'node_modules')],define:{'process.env.NODE_ENV':'"development"'},logLevel:'warning'})
await writeFile(path.join(out,'native.css'),css)
for(const match of css.toString('utf8').matchAll(/url\(['"]?(\.\/[^)'"\s]+)['"]?\)/g)){
 const name=match[1].slice(2).split(/[?#]/,1)[0]
 if(path.basename(name)===name)await copyFile(path.join(assets,name),path.join(out,name))
}
await writeFile(path.join(out,'index.html'),await readFile(path.join(fixtures,'operator.html')))
const sha=bytes=>createHash('sha256').update(bytes).digest('hex')
const metadata={core:execFileSync('git',['-C',core,'rev-parse','HEAD'],{encoding:'utf8'}).trim(),plugin_sha256:sha(await readFile(source)),native_css_sha256:sha(css),
 native_controls:['Button','Checkbox','Input','Badge','Select','Codicon','GlyphSpinner'],substitutions:['host','transport','profile/job data','theme variables','target native view stand-in'],inference:false}
await writeFile(path.join(out,'fixture-metadata.json'),JSON.stringify(metadata,null,2))
console.log(JSON.stringify({built:true,output:out,metadata}))
