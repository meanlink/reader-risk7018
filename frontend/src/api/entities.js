import {api} from './client.js';
export const datasets={list:()=>api('/datasets'),get:id=>api('/datasets/'+id),create:data=>api('/datasets',{method:'POST',body:JSON.stringify(data)})};
export const jobs={list:()=>api('/jobs'),get:id=>api('/jobs/'+id),create:data=>api('/jobs',{method:'POST',body:JSON.stringify(data)}),approve:id=>api('/jobs/'+id+'/approve',{method:'POST'})};
export const reports={list:()=>api('/reports'),create:data=>api('/reports',{method:'POST',body:JSON.stringify(data)}),toggle:id=>api('/reports/'+id+'/toggle',{method:'POST'}),deliveries:()=>api('/deliveries')};
export const intake={
 roster:()=>api('/intake/roster'),
 events:(limit=500)=>api('/intake/events?limit='+limit),
 runs:()=>api('/intake/runs'),
 batches:()=>api('/intake/batches'),
 batch:id=>api('/intake/batches/'+id),
 postRoster:data=>api('/intake/roster',{method:'POST',body:JSON.stringify(data)}),
 postEvents:data=>api('/intake/events',{method:'POST',body:JSON.stringify(data)}),
 build:()=>api('/intake/batches/build',{method:'POST'}),
 ledgerUrl:(id,format)=>'/api/intake/batches/'+id+'/ledger?format='+format,
};
