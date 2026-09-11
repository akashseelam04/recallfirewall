// RocketRide makes the investigation decisions; helpers expose scoped tools.
export function facilityTool(baseUrl, task, index) {
  return {id:'facility_'+index,provider:'mcp_client',config:{
    type:'mcp_client',serverName:index===0?'plant_a':'plant_b',transport:'streamable-http',
    http:{endpoint:baseUrl+'/v1/tasks/'+task.task_id+'/mcp',headers:{},bearer:task.token}
  }};
}

// Connectivity probe only. Direct Cloud tool dispatch requires no model node.
export function connectivityPipeline(baseUrl, task) {
  return {
    name:'Recall Firewall Cloud gateway connection',project_id:'recall-firewall',source:'source',
    components:[{id:'source',provider:'webhook',config:{}},
      {...facilityTool(baseUrl,task,0),control:[{from:'source',classType:'tool'}]}]
  };
}

export function facilityPipeline(baseUrl, tasks) {
  const agentId='investigator';
  return {
    name:'Recall Firewall facility investigation',project_id:'recall-firewall',source:'source',components:[
      {id:'source',provider:'webhook',config:{}},
      {id:agentId,provider:'agent_rocketride',config:{max_waves:6,require_tool_call:true,instructions:[
        'Investigate the requested ingredient using the scoped facility tools. Start with plant_a.consumption.',
        'If PLANT-A returned records, query plant_b.consumption for the same ingredient and read back the PLANT-A receipt with plant_a.get_receipt. If PLANT-A returned no records, do not dispatch PLANT-B; request source coverage instead. Empty records do not mean safe.',
        'Return JSON with status (REVIEW_REQUIRED or UNRESOLVED), queried_facilities, receipt_ids, next_action (REQUEST_COMPLETION_RECORDS or REQUEST_SOURCE_COVERAGE), and gaps. Never invent a receipt, support a completed event from a note, or claim containment. A failed tool must remain a visible gap.'
      ]},input:[{from:'source',lane:'questions'}]},
      {id:'model',provider:'llm_openai',config:{profile:'openai-4o-mini','openai-4o-mini':{apikey:'${ROCKETRIDE_OPENAI_KEY}'}},control:[{from:agentId,classType:'llm'}]},
      {id:'working_memory',provider:'memory_internal',config:{},control:[{from:agentId,classType:'memory'}]},
      ...tasks.map((task,index)=>({...facilityTool(baseUrl,task,index),control:[{from:agentId,classType:'tool'}]})),
      {id:'out',provider:'response_answers',config:{laneName:'answers'},input:[{from:agentId,lane:'answers'}]}
    ]
  };
}
