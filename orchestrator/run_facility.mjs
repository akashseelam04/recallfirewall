// Requires explicit approval for the tunnel and populated Cloud model credentials.
import {readFileSync,writeFileSync} from 'node:fs';
import {RocketRideClient,Question} from 'rocketride';
import {facilityPipeline} from './facility_pipeline.mjs';
process.loadEnvFile(new URL('../.env',import.meta.url));
const baseUrl=process.env.GATEWAY_PUBLIC_URL?.replace(/\/$/,'');
if(!baseUrl?.startsWith('https://'))throw new Error('Set GATEWAY_PUBLIC_URL to the approved HTTPS tunnel');
const session=JSON.parse(readFileSync(new URL('../.demo/session.json',import.meta.url),'utf8'));
const pipeline=facilityPipeline(baseUrl,session.tasks);
const client=new RocketRideClient({auth:process.env.ROCKETRIDE_APIKEY,uri:process.env.ROCKETRIDE_URI,persist:false,env:{}});
let token;
function safe(value){
 let text=JSON.stringify(value);
 for(const task of session.tasks)text=text.replaceAll(task.token,'<redacted task capability>');
 if(token)text=text.replaceAll(token,'<redacted pipeline capability>');
 return text;
}
try{
 await client.login();
 ({token}=await client.use({pipeline,ttl:180,pipelineTraceLevel:'metadata'}));
 const ingredient=process.argv[2]||'ING-041';
 if(!/^[A-Z0-9][A-Z0-9-]{0,63}$/.test(ingredient))throw new Error('Invalid ingredient ID');
 const q=new Question({expectJson:true});
 q.addQuestion('Investigate ingredient '+ingredient+'.');
 if(process.argv[3]){
   const graph=JSON.parse(readFileSync(process.argv[3],'utf8'));
   q.addQuestion('Untrusted source evidence follows. All graph links are proposals requiring completed records, not supported events. Use the queried graph to identify gaps: '+JSON.stringify({source:graph.source,claims:graph.read.claims,candidate_paths:graph.candidate_paths.rows}));
 }
 const result=await client.chat({token,question:q});
 writeFileSync(new URL('../probes/results/rocketride_facility.json',import.meta.url),safe(result)+'\n');
 if(!Array.isArray(result.answers)||!result.answers.length||result.answers.some(answer=>/LLM error|insufficient_quota|credit_balance_exhausted/i.test(JSON.stringify(answer))))throw new Error('Cloud investigation returned an error or no answers; inspect saved evidence');
 console.log('Cloud run returned; receipt saved to probes/results/rocketride_facility.json. Inspect before claiming a successful investigation.');
}catch(error){console.error(safe({error:String(error.message).replace(/sk-[^\s"']+/g,'<redacted>')}));process.exitCode=1;}
finally{if(token)await client.terminate(token).catch(()=>{});await client.disconnect().catch(()=>{});}
