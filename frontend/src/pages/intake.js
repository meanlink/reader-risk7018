import {intake} from '../api/entities.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {table} from '../components/common/table.js';
import {esc,notify,date} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';
import {parseCSV} from '../utils/csv.js';
import {downloadUrl} from '../api/client.js';

const EVENT_FIELDS=[
 ['event_id','事件号'],['reader_id','读者'],['session_id','会话'],
 ['issue_no','期号'],['occurred_at','发生时间(ISO或时间戳)'],['completion_pct','完成率0~100']];
const ROSTER_FIELDS=[['reader_id','读者'],['expire_date','到期日(YYYY-MM-DD)'],['renewed','实际续读(1/0，可空)']];
const readonly=()=>session.user.role==='viewer';

function statusBadge(s){
 const map={ready:['已就绪 · 可供试验','ok'],building:['构建中 · 未写齐不可用','warn'],failed:['失败','err']};
 const [label,cls]=map[s]||[s,'warn'];
 return '<span class="status-pill '+cls+'">'+esc(label)+'</span>';
}

async function loadAll(){
 const [batches,runs,roster,events]=await Promise.all([
   intake.batches(),intake.runs(),intake.roster(),intake.events(20)]);
 return {batches,runs,roster,events};
}

export async function intakePage(id){
 const data=await loadAll();
 const selected=id?await intake.batch(Number(id)).catch(()=>null):null;
 const current=selected||null;
 return heading('02B / EVENT INTAKE','阅读事件分批接入',
   '按读者到期前14日生成试验批次；访问按会话去重、完成率按各期末次取均、未读天数按末次访问、已读期数按期号去重。重复事件不多计，同号异内容整批拒绝。')
 +'<div class="dataset-grid">'
 // 左列：接入表单
 +'<section class="panel"><div class="section-title"><h2>① 读者名册</h2><span>'+data.roster.length+' 位读者</span></div>'
 +'<form id="roster-form"><label>上传 CSV 或 JSON<input type="file" id="roster-file" accept=".json,.csv"></label>'
 +'<label>记录 JSON<textarea name="records" rows="4" placeholder="粘贴 JSON 数组，或先选择文件" required></textarea></label>'
 +'<p class="hint">字段：'+ROSTER_FIELDS.map(f=>esc(f[0])+' / '+esc(f[1])).join('，')+'</p>'
 +'<button type="submit" class="primary" '+(readonly()?'disabled':'')+'>接入/更新名册</button></form>'
 +'<div class="section-title" style="margin-top:24px"><h2>② 阅读事件</h2><span>事件号全局唯一</span></div>'
 +'<form id="event-form"><label>上传 CSV 或 JSON<input type="file" id="event-file" accept=".json,.csv"></label>'
 +'<label>记录 JSON<textarea name="records" rows="7" placeholder="粘贴 JSON 数组，或先选择文件" required></textarea></label>'
 +'<p class="hint">字段：'+EVENT_FIELDS.map(f=>esc(f[0])+' / '+esc(f[1])).join('，')+'</p>'
 +'<button type="submit" class="primary" '+(readonly()?'disabled':'')+'>校验并接入事件</button>'
 +'<p class="hint" id="event-receipt"></p></form>'
 +'<div class="section-title" style="margin-top:24px"><h2>最近接收</h2><span>按接入批次</span></div>'
 +'<ul class="timeline">'+data.runs.slice(0,6).map(r=>'<li><strong>'+esc(r.kind==='roster'?'名册接入':'事件接入')+' · #'+r.id+'</strong><span>'+esc(r.source)+' · 接收 '+r.accepted+'/'+r.offered+' · 截止序号 '+r.last_receive_no+'</span><small>'+date(r.created_at)+'</small></li>').join('')||'<li>尚无接收记录</li>'+'</ul>'
 +'</section>'
 // 右列：批次与台账
 +'<section class="panel"><div class="section-title"><h2>③ 试验批次</h2><span>'+data.batches.length+' 批 · 固定截止点</span>'
 +(readonly()?'':'<button class="button" id="rebuild-btn">恢复/补建 ↻</button>')+'</div>'
 +'<div class="batch-list">'+(data.batches.map(b=>'<a class="batch-item '+(current&&current.id===b.id?'active':'')+'" href="#/intake/'+b.id+'"><strong>'+esc(b.name)+'</strong><span>'+esc(b.window_start)+' ~ '+esc(b.window_end)+' · 截止序号 '+esc(b.cutoff_receive_no)+'</span><span>读者 '+b.included_readers+' · 纳入事件 '+b.included_events+' · 排除 '+b.excluded_events+'</span>'+statusBadge(b.status)+(b.error?'<small class="err">'+esc(b.error)+'</small>':'')+'</a>').join('')||'<div class="empty">尚无批次：先接入名册与事件，窗口到期后自动生成。</div>')+'</div>'
 +(current?batchDetail(current):'<div class="empty">选择左侧批次查看纳入/排除台账与下载。</div>')
 +'</section></div>';
}

function batchDetail(b){
 const ledger=b.ledger||[];
 const included=ledger.filter(x=>x.decision==='included').length;
 const excluded=ledger.filter(x=>x.decision==='excluded').length;
 const cols=[
  {key:'event_id',label:'事件号'},{key:'reader_id',label:'读者'},{key:'decision',label:'纳入/排除'},
  {key:'reason',label:'原因'},{key:'receive_no',label:'接收序号'},{key:'occurred_at',label:'发生时间'}];
 const rows=ledger.map(x=>({...x,occurred_at:x.occurred_at?date(x.occurred_at):'—',
   decision:x.decision==='included'?'纳入':'排除'}));
 return '<div class="section-title" style="margin-top:20px"><h2>批次台账 · '+esc(b.name)+'</h2><span>'+statusBadge(b.status)+'</span></div>'
 +'<p class="hint">窗口 '+esc(b.window_start)+' ~ '+esc(b.window_end)+'；固定截至接收序号 '+esc(b.cutoff_receive_no)+'，迟到记录不回写本批。纳入 '+included+' / 排除 '+excluded+'。</p>'
 +'<div class="ledger-filters"><button class="button active" data-filter="all">全部 '+ledger.length+'</button><button class="button" data-filter="included">仅纳入 '+included+'</button><button class="button" data-filter="excluded">仅排除 '+excluded+'</button>'
 +(b.status==='ready'?'<button class="primary" data-dl="csv">下载台账 CSV</button><button class="button" data-dl="json">下载台账 JSON</button>':'')
 +(b.dataset_id?'<a class="button" href="#/datasets">查看汇总样本 #'+b.dataset_id+' ↗</a>':'')+'</div>'
 +'<div id="ledger-table">'+table(cols,rows,'该批次暂无台账记录。')+'</div>';
}

function bindFile(inputId,textareaId){
 const input=document.querySelector(inputId);
 if(!input)return;
 input.addEventListener('change',async e=>{
   const file=e.target.files[0];if(!file)return;
   try{
     const text=await file.text();
     const records=file.name.endsWith('.csv')?parseCSV(text):JSON.parse(text);
     document.querySelector(textareaId).value=JSON.stringify(records,null,2);
   }catch(err){notify(err.message,true);}
 });
}

export function bindIntake(refresh){
 bindFile('#roster-file','#roster-form [name=records]');
 bindFile('#event-file','#event-form [name=records]');
 const rosterForm=document.querySelector('#roster-form');
 if(rosterForm)submit(rosterForm,async f=>{
   await intake.postRoster({source:document.querySelector('#roster-file').files[0]?.name||'manual.json',
     records:JSON.parse(f.get('records'))});
   notify('名册已接入');await refresh();
 });
 const eventForm=document.querySelector('#event-form');
 if(eventForm)submit(eventForm,async f=>{
   const res=await intake.postEvents({source:document.querySelector('#event-file').files[0]?.name||'manual.json',
     records:JSON.parse(f.get('records'))});
   const built=(res.batches||[]).length;
   notify('事件已接收 '+res.accepted+' 条，重复 '+res.duplicates.length+' 条'+(built?'，已生成/更新 '+built+' 个试验批次':''));
   await refresh();
 });
 document.querySelector('#rebuild-btn')?.addEventListener('click',async()=>{
   try{const bs=await intake.build();notify(bs.length?'已补建 '+bs.length+' 个批次':'没有待构建的到期窗口');await refresh();}
   catch(e){notify(e.message,true);}
 });
 document.querySelectorAll('[data-dl]').forEach(btn=>btn.addEventListener('click',async()=>{
   const id=location.hash.split('/')[2];
   try{await downloadUrl(intake.ledgerUrl(id,btn.dataset.dl),'批次-'+id+'-台账.'+btn.dataset.dl);}
   catch(e){notify(e.message,true);}
 }));
 document.querySelectorAll('.ledger-filters [data-filter]').forEach(btn=>btn.addEventListener('click',()=>{
   document.querySelectorAll('.ledger-filters [data-filter]').forEach(x=>x.classList.remove('active'));
   btn.classList.add('active');
   const filter=btn.dataset.filter;
   document.querySelectorAll('#ledger-table tbody tr').forEach(tr=>{
     const decision=tr.children[2]?.textContent;
     tr.style.display=(filter==='all'||decision===(filter==='included'?'纳入':'排除'))?'':'none';
   });
 }));
}
