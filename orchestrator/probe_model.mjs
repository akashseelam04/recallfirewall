import {RocketRideClient, Question} from 'rocketride';
import {mkdirSync,writeFileSync} from 'node:fs';
process.loadEnvFile(new URL('../.env',import.meta.url));
// Empty substitution env proves the key resolves from the Cloud account.
const c=new RocketRideClient({auth:process.env.ROCKETRIDE_APIKEY,uri:process.env.ROCKETRIDE_URI,persist:false,env:{}});
let token;
try {
 await c.login();
 const pipeline={name:'Recall Firewall model access probe',project_id:'recall-firewall',source:'source',components:[
 {id:'source',provider:'webhook',config:{}},
 {id:'llm',provider:'llm_openai',config:{profile:'openai-4o-mini','openai-4o-mini':{apikey:'${ROCKETRIDE_OPENAI_KEY}'}},input:[{from:'source',lane:'questions'}]},
 {id:'out',provider:'response_answers',config:{laneName:'answers'},input:[{from:'llm',lane:'answers'}]}
 ]};
 ({token}=await c.use({pipeline,ttl:90}));
 console.log('Cloud pipeline started');
 const q=new Question();q.addQuestion('Reply with the word connected.');
 const result=await c.chat({token,question:q});
 const connected=Array.isArray(result.answers) && result.answers.some(answer=>
   typeof answer==='string' && /^connected[.!]?$/i.test(answer.trim())) &&
   !result.answers.some(answer=>typeof answer==='string' && /LLM error|insufficient_quota|credit_balance_exhausted/i.test(answer));
 let report=JSON.stringify({checked_at:new Date().toISOString(),connected,result},null,2);
 for(const secret of [process.env.ROCKETRIDE_LLMKEY,process.env.ROCKETRIDE_APIKEY,token].filter(Boolean))
   report=report.replaceAll(secret,'<redacted>');
 mkdirSync(new URL('../probes/results/',import.meta.url),{recursive:true});
 writeFileSync(new URL('../probes/results/rocketride_model.json',import.meta.url),report+'\n');
 console.log(report);
 if(!connected)throw new Error('Cloud returned no successful connected response; inspect the model probe receipt');
} catch(e) {
 let message=String(e.message);
 for(const secret of [process.env.ROCKETRIDE_LLMKEY,process.env.ROCKETRIDE_APIKEY,token].filter(Boolean))
   message=message.replaceAll(secret,'<redacted>');
 console.error(message.replace(/sk-[^\s"']+/g,'<redacted>').slice(0,1800));process.exitCode=1;
}
finally {if(token) await c.terminate(token).catch(()=>{});await c.disconnect().catch(()=>{});}
