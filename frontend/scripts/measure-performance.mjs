// Controlled mobile lab: frozen API fixtures, identical browser/throttling,
// external requests blocked. Reports are local artifacts, never field metrics.
import assert from 'node:assert/strict'
import http from 'node:http'
import { readFileSync, existsSync, createReadStream, mkdirSync, writeFileSync } from 'node:fs'
import { resolve, extname } from 'node:path'
import { gzipSync } from 'node:zlib'
import { chromium } from 'playwright'
import lighthouse from 'lighthouse'
import { MOCK_KPI, MOCK_PRODUCTS, MOCK_DAILY_VOLUME, MOCK_SHIPMENTS, MOCK_PRODUCT_DETAIL, MOCK_VERIFY_OK } from '../e2e/helpers/data.ts'
const [distArg, outputArg] = process.argv.slice(2)
assert.ok(distArg && outputArg, 'Usage: node scripts/measure-performance.mjs DIST OUTPUT_DIRECTORY')
const dist=resolve(distArg), output=resolve(outputArg)
mkdirSync(output,{recursive:true})
const port=18010
const types={'.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.webp':'image/webp','.png':'image/png','.woff2':'font/woff2','.json':'application/json','.html':'text/html'}
const server=http.createServer((req,res)=>{
  const url=new URL(req.url,'http://127.0.0.1:'+port), path=url.pathname.replace(/\/$/,'')
  const json=data=>{res.setHeader('Content-Type','application/json');res.end(JSON.stringify(data))}
  if(path==='/health/ready')return json({status:'ready',database:'connected',indexer:{status:'current',enabled:true,ready:true}})
  if(path==='/analytics/events'){res.writeHead(200,{'Content-Type':'text/event-stream','Cache-Control':'no-cache'});res.write('event: resync\ndata: {}\n\n');const timer=setInterval(()=>res.write('event: heartbeat\ndata: {}\n\n'),5000);req.on('close',()=>clearInterval(timer));return}
  if(path==='/analytics/kpis')return json(MOCK_KPI)
  if(path==='/analytics/daily-volume')return json(MOCK_DAILY_VOLUME)
  if(path==='/analytics/anomalies'||path==='/analytics/bottlenecks')return json([])
  if(path==='/products')return json(MOCK_PRODUCTS)
  if(path==='/shipments')return json(MOCK_SHIPMENTS)
  if(path.endsWith('/verify'))return json(MOCK_VERIFY_OK)
  if(path.endsWith('/timeline'))return json({items:[],total:0})
  if(/^\/products\/[^/]+$/.test(path))return json(MOCK_PRODUCT_DETAIL)
  if(path==='/telemetry/browser'){res.writeHead(204);return res.end()}
  const filename=resolve(dist,'.'+url.pathname)
  const file=filename.startsWith(dist+'/')&&existsSync(filename)&&extname(filename)?filename:resolve(dist,'index.html')
  let body=readFileSync(file)
  res.setHeader('Content-Type',types[extname(file)]||'application/octet-stream')
  if(/gzip/.test(req.headers['accept-encoding']||'')){body=gzipSync(body);res.setHeader('Content-Encoding','gzip')}
  res.end(body)
})
await new Promise(resolve=>server.listen(port,'127.0.0.1',resolve))
const browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH||'/usr/bin/chromium',args:['--remote-debugging-port=19222','--no-sandbox']})
const samples=[]
try{
  for(let i=0;i<3;i++){
    const result=process.env.MEASURE_REUSE === '1' ? {lhr:JSON.parse(readFileSync(resolve(output,`lighthouse-${i+1}.json`),'utf8'))} : await lighthouse(`http://127.0.0.1:${port}/`,{port:19222,output:'json',logLevel:'error',onlyCategories:['performance'],formFactor:'mobile',screenEmulation:{mobile:true,width:390,height:844,deviceScaleFactor:1,disabled:false},throttlingMethod:'simulate',blockedUrlPatterns:['https://*'],maxWaitForLoad:30000,maxWaitForFcp:30000})
    const r=result.lhr
    assert.ok(!r.runtimeError,JSON.stringify(r.runtimeError))
    const sample={performance:r.categories.performance.score,fcp_ms:r.audits['first-contentful-paint'].numericValue,lcp_ms:r.audits['largest-contentful-paint'].numericValue,tbt_ms:r.audits['total-blocking-time'].numericValue,cls:r.audits['cumulative-layout-shift'].numericValue,transfer_bytes:r.audits['total-byte-weight'].numericValue}
    samples.push(sample);writeFileSync(resolve(output,`lighthouse-${i+1}.json`),JSON.stringify(r))
    console.log(JSON.stringify({sample:i+1,...sample}))
  }
  const context=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'})
  await context.route('https://**',route=>route.abort())
  const page=await context.newPage();const scripts=new Set()
  page.on('response',r=>{if(r.request().resourceType()==='script'&&r.url().startsWith(`http://127.0.0.1:${port}/assets/`))scripts.add(new URL(r.url()).pathname)})
  await page.goto(`http://127.0.0.1:${port}`,{waitUntil:'domcontentloaded'})
  await page.getByRole('button',{name:'Open navigation menu'}).waitFor()
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))))
  const before=await page.evaluate(()=>performance.now())
  await page.getByRole('button',{name:'Open navigation menu'}).click()
  await page.getByRole('navigation',{name:'Mobile navigation'}).waitFor()
  const interaction=await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve(performance.now())))))
  await page.screenshot({path:resolve(output,'mobile.png'),fullPage:true})
  const scriptFiles=[...scripts].map(url=>({path:url,bytes:readFileSync(resolve(dist,'.'+url)).length,gzip_bytes:gzipSync(readFileSync(resolve(dist,'.'+url))).length}))
  const summary={method:'Controlled mobile lab; 3 cold-cache Lighthouse runs; 390x844; simulated mobile CPU/network; gzip; frozen API fixtures; external HTTPS blocked. Interaction includes Playwright click overhead and two animation frames, not field INP.',browser:browser.version(),samples,median:Object.fromEntries(Object.keys(samples[0]).map(key=>[key,samples.map(s=>s[key]).sort((a,b)=>a-b)[1]])),menu_interaction_ms:interaction-before,initial_script_bytes:scriptFiles.reduce((n,s)=>n+s.bytes,0),initial_script_gzip_bytes:scriptFiles.reduce((n,s)=>n+s.gzip_bytes,0),scripts:scriptFiles}
  writeFileSync(resolve(output,'summary.json'),JSON.stringify(summary,null,2)+'\n');console.log(JSON.stringify(summary))
}finally{await browser.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve))}
