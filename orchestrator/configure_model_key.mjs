// User-authorized upload: local ROCKETRIDE_LLMKEY -> active org's model secret.
import assert from 'node:assert/strict';
import {RocketRideClient} from 'rocketride';

process.loadEnvFile(new URL('../.env',import.meta.url));
const key=process.env.ROCKETRIDE_LLMKEY?.trim();
assert(key,'Set ROCKETRIDE_LLMKEY in the gitignored .env first');
const client=new RocketRideClient({auth:process.env.ROCKETRIDE_APIKEY,
  uri:process.env.ROCKETRIDE_URI,persist:false,env:{}});
try {
  await client.login();
  const org=await client.account.getOrg();
  assert(org.id,'No active RocketRide organization');
  const existing=await client.account.getEnv('org',org.id);
  // setEnv REPLACES the complete dictionary. Preserve unrelated settings.
  await client.account.setEnv('org',{...existing,ROCKETRIDE_OPENAI_KEY:key},org.id);
  const saved=await client.account.getEnv('org',org.id);
  assert(saved.ROCKETRIDE_OPENAI_KEY===key,'Stored model key did not match');
  assert(Object.entries(existing).every(([name,value])=>
    name==='ROCKETRIDE_OPENAI_KEY' || saved[name]===value),'An unrelated setting changed');
  console.log('ROCKETRIDE_OPENAI_KEY saved and read-back verified at active organization scope; unrelated settings preserved.');
} catch(error) {
  let message=String(error.message);
  for(const secret of [key,process.env.ROCKETRIDE_APIKEY].filter(Boolean))
    message=message.replaceAll(secret,'<redacted>');
  console.error(message.replace(/sk-[A-Za-z0-9_-]+/g,'<redacted>').slice(0,1800));
  process.exitCode=1;
} finally {
  await client.disconnect().catch(()=>{});
}
