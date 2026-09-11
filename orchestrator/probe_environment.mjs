import {RocketRideClient} from 'rocketride';
process.loadEnvFile(new URL('../.env',import.meta.url));
const c=new RocketRideClient({auth:process.env.ROCKETRIDE_APIKEY,uri:process.env.ROCKETRIDE_URI,persist:false});
async function check(scope,id){
 const values=await c.account.getEnv(scope,id);
 console.log(scope+' configured fields:',JSON.stringify(Object.entries(values).map(([name,value])=>({name,populated:!!value}))));
}
try{
 await c.login();
 const keys=await c.account.getEnvironmentKeys();
 console.log('Advertised ROCKETRIDE_OPENAI_KEY:',keys.includes('ROCKETRIDE_OPENAI_KEY'));
 await check('user');
 const org=await c.account.getOrg();
 console.log('organization identity:',JSON.stringify({id:org.id,name:org.name,fields:Object.keys(org)}));
 if(org.id){
  await check('org',org.id);
  const teams=await c.account.listTeams(org.id);
  console.log('team count:',Array.isArray(teams)?teams.length:'non-array');
  if(Array.isArray(teams))for(const team of teams)await check('team',team.id);
 }
}finally{await c.disconnect().catch(()=>{});}
