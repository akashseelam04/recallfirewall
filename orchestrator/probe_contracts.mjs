import { writeFileSync } from 'node:fs';
import { RocketRideClient } from 'rocketride';
process.loadEnvFile(new URL('../.env', import.meta.url));
const client = new RocketRideClient({auth:process.env.ROCKETRIDE_APIKEY,uri:process.env.ROCKETRIDE_URI,persist:false});
try {
 await client.login();
 const names=['mcp_client','tool_http_request','agent_rocketride','memory_internal','llm_gmi_cloud','llm_openai','llm_gemini','webhook','response_answers'];
 const definitions=Object.fromEntries(await Promise.all(names.map(async name=>[name,await client.getService(name)])));
 writeFileSync(new URL('contracts.json',import.meta.url),JSON.stringify(definitions,null,2));
 console.log('Saved '+names.length+' live provider schemas');
} finally {await client.disconnect().catch(()=>{});}
