import assert from 'node:assert/strict';
import {mkdirSync,writeFileSync} from 'node:fs';
import {homedir} from 'node:os';
import {join,resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const {chromium}=await import(pathToFileURL(join(homedir(),'.rote/lib/playwright-runtime/node_modules/playwright/index.mjs')).href);
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const errors=[],requests=[];
const screenshots=resolve('demo/screenshots');mkdirSync(screenshots,{recursive:true});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000},deviceScaleFactor:1});
 page.on('pageerror',error=>errors.push(error.message));
 page.on('request',request=>requests.push({url:request.url(),method:request.method()}));
 await page.goto('http://127.0.0.1:8791/');
 await page.waitForLoadState('networkidle');
 const initialRequests=requests.length;
 const chapters=['overview','signal','memory','investigate','protect','reuse','security'];
 const headings=[];
 for(const chapter of chapters){
   await page.waitForFunction(expected=>document.querySelector('#chapters a.active')?.getAttribute('href')==='#'+expected,chapter);
   await page.locator('h1').waitFor();
   headings.push(await page.locator('h1').innerText());
   assert(await page.locator('.reveal').count()>0,'Missing presentation animation');
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true,'Horizontal overflow');
   await page.screenshot({path:join(screenshots,chapter+'.png'),fullPage:true,animations:'disabled'});
   if(chapter!=='security')await page.locator('.next-button').click();
 }
 assert.equal(new Set(headings).size,7);
 assert.equal(requests.length,initialRequests,'Chapter navigation triggered a network request');
 assert(requests.every(r=>r.method==='GET'&&r.url.startsWith('http://127.0.0.1:8791/')));
 await page.goto('http://127.0.0.1:8791/presentation.html#signal');
 await page.keyboard.press('ArrowRight');
 await page.waitForURL('**#memory');
 await page.waitForFunction(()=>document.querySelector('#chapters a.active')?.getAttribute('href')==='#memory');
 assert.match(await page.locator('h1').innerText(),/Keep the link/);
 await page.setViewportSize({width:390,height:844});
 await page.goto('http://127.0.0.1:8791/#security');
 await page.waitForFunction(()=>document.querySelector('#chapters a.active')?.getAttribute('href')==='#security');
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true,'Mobile horizontal overflow');
 assert.deepEqual(errors,[]);
 writeFileSync('probes/results/ui_check.json',JSON.stringify({passed:true,chapters:headings,
   navigation_network_requests:0,mutation_requests:0,browser_errors:errors,
   presentation_keyboard_navigation:true,mobile_width:390},null,2)+'\n');
 console.log('UI verified: 7 chapters, animated navigation, zero navigation requests, no browser errors; presentation keyboard and mobile layout passed.');
}finally{await browser.close();}
