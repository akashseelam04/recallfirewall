// Deterministic Cloud orchestration; no model credits or local dispatch fallback.
import assert from 'node:assert/strict';
import {readFileSync,writeFileSync} from 'node:fs';
import {RocketRideClient} from 'rocketride';
process.loadEnvFile(new URL('../.env',import.meta.url));
const origin=new URL(process.env.GATEWAY_PUBLIC_URL||'http://invalid');
assert(origin.protocol==='https:'&&!origin.username&&!origin.password&&origin.pathname==='/'&&!origin.search&&!origin.hash,
  'Set GATEWAY_PUBLIC_URL to the approved gateway origin');
const ingredient=process.argv[2]||'ING-041';
assert(/^[A-Z0-9][A-Z0-9-]{0,63}$/.test(ingredient),'Invalid ingredient');
const session=JSON.parse(readFileSync(new URL('../.demo/session.json',import.meta.url),'utf8'));
const graph=JSON.parse(readFileSync(new URL('../probes/results/graph_bridge.json',import.meta.url),'utf8'));
assert(graph.expected_fixture_paths_found&&graph.read.coverage.delivery_complete,'Complete demo graph handoff is required');
const cfg={gateway:origin.origin,ingredient_id:ingredient,tasks:session.tasks,claims:graph.read.claims};
const code='import json\ncfg = json.loads('+JSON.stringify(JSON.stringify(cfg))+')\n'+
  readFileSync(new URL('./facility_dispatch.py',import.meta.url),'utf8');
const pipeline={name:'Recall Firewall fixed facility dispatch',project_id:'recall-firewall',source:'source',components:[
  {id:'source',provider:'webhook',config:{}},
  {id:'dispatch',provider:'tool_python',config:{type:'tool_python',timeout:150,allowedModules:[{moduleName:'urllib'}]},
    control:[{from:'source',classType:'tool'}]}
]};
const client=new RocketRideClient({auth:process.env.ROCKETRIDE_APIKEY,uri:process.env.ROCKETRIDE_URI,persist:false,env:{}});
let token;
const report={success:false,started_at:new Date().toISOString(),ingredient_id:ingredient};
function redact(value){
  let text=JSON.stringify(value,null,2);
  for(const secret of [token,process.env.ROCKETRIDE_APIKEY,process.env.ROCKETRIDE_LLMKEY,...session.tasks.map(t=>t.token)].filter(Boolean))
    text=text.replaceAll(secret,'<redacted>');
  return text;
}
try{
  await client.login();
  ({token}=await client.use({pipeline,ttl:240,pipelineTraceLevel:'metadata'}));
  const response=await client.tool({token,nodeId:'dispatch',tool:'execute',input:{code},timeout:180000});
  report.response=response;
  assert.equal(response.exit_code,0,'Cloud dispatch failed; inspect its saved error');
  assert.equal(response.timed_out,false);
  const finding=response.result;
  assert.equal(finding.execution,'ROCKETRIDE_CLOUD_FIXED_PROCEDURE');
  assert(['QUERY_PLANT_B','REQUEST_SOURCE_COVERAGE'].includes(finding.branch));
  assert.deepEqual(finding.queried_facilities,finding.branch==='QUERY_PLANT_B'?['PLANT-A','PLANT-B']:['PLANT-A']);
  assert(finding.findings.every(f=>f.query_run_id&&f.receipt_id&&f.admission_status==='CURRENT'));
  report.success=true;
  console.log('Cloud branch: '+finding.branch+'; queried '+finding.queried_facilities.join(', '));
}catch(error){report.error=String(error.message);console.error(redact({error:report.error,response:report.response}));process.exitCode=1;}
finally{
  if(token)await client.terminate(token).catch(()=>{});
  await client.disconnect().catch(()=>{});
  report.ended_at=new Date().toISOString();
  writeFileSync(new URL('../probes/results/rocketride_dispatch.json',import.meta.url),redact(report)+'\n');
}
