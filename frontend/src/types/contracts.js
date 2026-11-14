/** @typedef {{id:number,name:string,source:string,rows:number,checksum:string}} Dataset */
/** @typedef {{id:number,name:string,dataset_id:number,status:string,result:Object,approved:boolean}} AnalysisJob */
/** @typedef {{id:number,name:string,job_id:number,destination:string,next_run:number,enabled:boolean}} ReportSchedule */
/** @typedef {{id:number,window_start:string,window_end:string,cutoff_receive_no:number,status:'building'|'ready'|'failed',dataset_id:?number,included_readers:number,included_events:number,excluded_events:number,error:string}} ExperimentBatch */
/** @typedef {{id:number,batch_id:number,event_id:string,reader_id:string,decision:'included'|'excluded',reason:string,receive_no:number,occurred_at:?number}} EventLedgerRow */
export {};
