// Real RocketRide Cloud -> MCP gateway -> Hotdata, followed by receipt read-back.
// Requires the explicitly approved public gateway URL; never starts a tunnel.
import assert from 'node:assert/strict';
import {mkdirSync,readFileSync,writeFileSync} from 'node:fs';
import {RocketRideClient} from 'rocketride';
import {connectivityPipeline} from './facility_pipeline.mjs';

process.loadEnvFile(new URL('../.env',import.meta.url));
const endpoint=new URL(process.env.GATEWAY_PUBLIC_URL || 'http://invalid');
assert(endpoint.protocol==='https:' && !endpoint.username && !endpoint.password &&
  !endpoint.search && !endpoint.hash && endpoint.pathname==='/',
  'Set GATEWAY_PUBLIC_URL to the approved HTTPS gateway origin');
const session=JSON.parse(readFileSync(new URL('../.demo/session.json',import.meta.url),'utf8'));
const task=session.tasks.find(item=>item.facility_id==='PLANT-A');
assert(task, 'PLANT-A demo task is required');
const bindings=JSON.parse(readFileSync(session.bindings_file,'utf8'));
assert(bindings.find(item=>item.task_id===task.task_id)?.expires_at>Date.now()/1000+90,
  'Demo capability expired or expiring; regenerate configuration and restart gateway');
const ingredientId=process.argv[2] || 'ING-041';
assert(/^[A-Z0-9][A-Z0-9-]{0,63}$/.test(ingredientId),'Invalid ingredient ID');

const client=new RocketRideClient({auth:process.env.ROCKETRIDE_APIKEY,uri:process.env.ROCKETRIDE_URI,persist:false,env:{}});
const report={started_at:new Date().toISOString(),mode:'cloud_tool_connectivity',
  ingredient_id:ingredientId,success:false};
let token;
function decode(value) {
  assert(value && typeof value==='object' && !value.isError,'Cloud tool returned an error');
  if(Array.isArray(value.content)) {
    const parts=value.content.filter(part=>part.type==='text');
    assert(parts.length===1,'Expected one structured gateway result');
    return JSON.parse(parts[0].text);
  }
  // Some MCP clients unwrap the single JSON text block themselves.
  return value;
}
function redact(value) {
  let text=JSON.stringify(value,null,2);
  const secrets=[token,...session.tasks.map(item=>item.token),
    ...Object.entries(process.env).filter(([key])=>/KEY|TOKEN|SECRET|PASSWORD/.test(key)).map(([,value])=>value)];
  for(const secret of secrets.filter(value=>value?.length>=8))text=text.replaceAll(secret,'<redacted>');
  return text.replace(/sk-[A-Za-z0-9_-]+/g,'<redacted>');
}
try {
  await client.login();
  ({token}=await client.use({pipeline:connectivityPipeline(endpoint.origin,task),ttl:180,pipelineTraceLevel:'metadata'}));
  console.log('Cloud connectivity pipeline started; invoking scoped consumption tool.');
  report.raw_consumption=await client.tool({token,nodeId:'facility_0',tool:'plant_a.consumption',
    input:{ingredient_id:ingredientId},timeout:60000});
  const finding=decode(report.raw_consumption);
  assert.equal(finding.task_id,task.task_id);
  assert.equal(finding.facility_id,'PLANT-A');
  assert.equal(finding.arguments?.ingredient_id,ingredientId);
  assert.equal(finding.admission_status,'CURRENT');
  assert(Array.isArray(finding.rows) && finding.query_run_id && finding.receipt_id && finding.result_sha256,
    'Gateway result is missing rows, native query ID or provenance');
  assert(finding.rows.every(row=>row.plant_id==='PLANT-A' && row.ingredient_id===ingredientId),
    'Gateway returned rows outside the requested scope');
  report.raw_receipt=await client.tool({token,nodeId:'facility_0',tool:'plant_a.get_receipt',
    input:{receipt_id:finding.receipt_id},timeout:30000});
  const receipt=decode(report.raw_receipt);
  assert.equal(receipt.receipt_id,finding.receipt_id);
  assert.equal(receipt.query_run_id,finding.query_run_id);
  assert.equal(receipt.result_sha256,finding.result_sha256);
  assert.equal(receipt.current_status,'CURRENT');
  report.success=true;
  console.log(`Cloud called Hotdata through the gateway: ${finding.rows.length} rows; receipt read-back matched.`);
} catch(error) {
  report.error=String(error.message);
  console.error(redact({error:report.error}));
  process.exitCode=1;
} finally {
  if(token)await client.terminate(token).catch(()=>{});
  await client.disconnect().catch(()=>{});
  report.ended_at=new Date().toISOString();
  mkdirSync(new URL('../probes/results/',import.meta.url),{recursive:true});
  writeFileSync(new URL('../probes/results/rocketride_gateway.json',import.meta.url),redact(report)+'\n');
}
