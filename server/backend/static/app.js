'use strict';
const $ = id => document.getElementById(id);
const number = new Intl.NumberFormat('en-US');
let device = 'bike-001';
let summary = null;
let period = '24h';
let series = [];
let socket = null;
let reconnectDelay = 1000;
let lastHistoryFetch = 0;
let lastSessionsFetch = 0;
let lastAwardsFetch = 0;
let seenAwards = null;
let chartTimer = null;

async function api(path) {
  const r = await fetch(path, {credentials: 'same-origin', cache: 'no-store'});
  if (r.status === 401) { location.assign('/login'); throw new Error('Authentication required'); }
  if (!r.ok) throw new Error(`API ${r.status}`);
  return r.json();
}
function formatDuration(seconds) {
  let n = Math.max(0, Math.floor(seconds));
  const h = Math.floor(n / 3600);
  const m = Math.floor((n % 3600) / 60);
  const s = n % 60;
  return h ? `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}` : `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}
function ageText(ms) {
  if (ms == null) return 'No pulses yet';
  const sec = Math.max(0, Math.floor((Date.now() - ms) / 1000));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec/60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec/3600)}h ago`;
  return `${Math.floor(sec/86400)}d ago`;
}
function render() {
  $('localtime').textContent = new Date().toLocaleString('en-GB', {timeZone:'Europe/Budapest', weekday:'short',hour:'2-digit',minute:'2-digit'});
  if (!summary) return;
  const active = summary.session_active && Date.now() - summary.session_ended_ms < 180000;
  const age = summary.last_event_ms == null ? Infinity : Date.now() - summary.last_event_ms;
  const rpm = age < 6000 ? summary.live_rpm : 0;
  $('rpm').textContent = Math.round(rpm).toString();
  $('rpm-fill').style.width = `${Math.min(100,Math.max(0,rpm/140*100))}%`;
  $('lifetime').textContent = number.format(summary.lifetime_revolutions);
  $('today').textContent = number.format(summary.today_revolutions);
  $('session-revs').textContent = number.format(summary.session_revolutions);
  $('session-time').textContent = formatDuration(summary.session_duration_s + (active ? Math.max(0,Math.floor((Date.now() - summary.server_time_ms)/1000)) : 0));
  $('session-status').textContent = active ? '● PEDALING SESSION' : '● INACTIVE';
  $('session-status').classList.toggle('active',active);
  $('age').textContent = summary.last_event_ms ? ageText(summary.last_event_ms) : '—';
  $('last-event').textContent = ageText(summary.last_event_ms);
  $('unlogged').textContent = summary.unlogged_revolutions ? `${number.format(summary.unlogged_revolutions)} revolutions counted without raw events` : 'Every revolution accounted for';
}
async function loadHistory() {
  lastHistoryFetch = Date.now();
  try {
    const data = await api(`/api/v1/devices/${encodeURIComponent(device)}/history?period=${period}`);
    series = data.points;
    drawChart();
  } catch(e) { console.error('History:',e); }
}
async function loadSessions() {
  lastSessionsFetch = Date.now();
  try {
    const data = await api(`/api/v1/devices/${encodeURIComponent(device)}/sessions`);
    const out = $('sessions'); out.replaceChildren();
    if (!data.sessions.length) { const empty=document.createElement('div');empty.className='placeholder';empty.textContent='No sessions yet. Time to pedal.';out.append(empty);return; }
    for (const s of data.sessions) {
      const el=document.createElement('div'); el.className='session-row';
      const date=document.createElement('strong'); date.textContent=new Date(s.started_ms).toLocaleString('en-GB',{timeZone:'Europe/Budapest',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
      const revs=document.createElement('span');revs.textContent=`${number.format(s.revs)} rev`;
      const dur=document.createElement('span');dur.textContent=formatDuration((s.ended_ms-s.started_ms)/1000);
      el.append(date,revs,dur);out.append(el);
    }
  } catch(e) { console.error('Sessions:',e); }
}
async function loadAchievements() {
  lastAwardsFetch = Date.now();
  try {
    const data = await api(`/api/v1/devices/${encodeURIComponent(device)}/achievements`);
    const grid = $('achievement-grid');
    if (!grid) return;
    grid.replaceChildren();
    const unlocked = new Set(data.achievements.filter(a => a.unlocked_ms).map(a => a.id));
    if (seenAwards !== null) {
      const fresh = data.achievements.find(a => a.unlocked_ms && !seenAwards.has(a.id));
      if (fresh) {
        const toast=$('achievement-toast');
        toast.textContent=`${fresh.icon} ACHIEVEMENT UNLOCKED — ${fresh.name}`;
        toast.classList.add('visible');
        setTimeout(()=>toast.classList.remove('visible'), 7000);
      }
    }
    seenAwards=unlocked;
    $('achievement-progress').textContent = `${data.unlocked_count} / ${data.total_count}`;
    const awardFilter=$('achievement-filter')?.value || 'all';
    for (const a of data.achievements.filter(a=>awardFilter==='all' ||
             (awardFilter==='unlocked' ? !!a.unlocked_ms : !a.unlocked_ms))) {
      const tile=document.createElement('article');
      tile.className='achievement-tile' + (a.unlocked_ms ? ' unlocked' : ' locked');
      const sym=document.createElement('span');sym.className='achievement-icon';sym.textContent=a.icon;
      const txt=document.createElement('div');
      const name=document.createElement('strong');name.textContent=a.name;
      const rank=document.createElement('span');rank.className=`award-rank rank-${a.tier||'bronze'}`;
      rank.textContent=(a.tier||'bronze').toUpperCase();
      const desc=document.createElement('small');desc.textContent=a.description;
      const state=document.createElement('div');state.className='achievement-state';
      state.textContent=a.unlocked_ms ? `Unlocked ${new Date(a.unlocked_ms).toLocaleDateString('en-GB',{timeZone:'Europe/Budapest'})}` : `${number.format(Math.floor(a.progress))} / ${number.format(a.target)}`;
      txt.append(name,rank,desc,state);
      if (!a.unlocked_ms) {
        const track=document.createElement('div');track.className='progress-track award-track';
        const fill=document.createElement('div');fill.className='progress-fill';
        fill.style.width=`${Math.min(100,100*a.progress/a.target)}%`;
        track.append(fill);txt.append(track);
      }
      tile.append(sym,txt);grid.append(tile);
    }
  } catch(e) { console.error('Achievements:',e); }
}
function formatBucket(bucket) {
  if (typeof bucket === 'number') return new Date(bucket).toLocaleString('en-GB',{timeZone:'Europe/Budapest',day:'2-digit',month:'short',hour:'2-digit'});
  return bucket;
}
function drawChart() {
  const canvas=$('chart'), box=canvas.parentElement;
  if (!canvas) return;
  box.classList.toggle('empty', !series.some(p=>p.y>0));
  $('graph-total').textContent = `${number.format(series.reduce((s,p)=>s+p.y,0))} revolutions in view`;
  const bounds=canvas.getBoundingClientRect(), dpr=window.devicePixelRatio || 1;
  if (bounds.width < 2 || bounds.height < 2) return;
  canvas.width=Math.round(bounds.width*dpr);canvas.height=Math.round(bounds.height*dpr);
  const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);
  const W=bounds.width,H=bounds.height,left=48,right=8,top=12,bottom=33;
  const plotW=W-left-right,plotH=H-top-bottom;
  const max=Math.max(4,...series.map(p=>p.y));
  const nice=Math.max(1,Math.ceil(max/4/5)*5)*4;
  ctx.font='11px system-ui';ctx.fillStyle='#8099a5';ctx.textAlign='right';ctx.strokeStyle='#2a404d';ctx.lineWidth=1;
  for(let i=0;i<=4;i++){
    const y=top+plotH-(i/4)*plotH;
    ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(W-right,y);ctx.stroke();
    ctx.fillText(number.format(i*nice/4),left-10,y+4);
  }
  if(!series.length)return;
  const n=series.length;const width=plotW/n;
  const formatIndex = i => formatBucket(series[Math.min(n-1,Math.max(0,i))].x);
  ctx.textAlign='center';ctx.fillStyle='#90a8b2';
  [0,.25,.5,.75,1].forEach(r=>{
    const i=Math.round((n-1)*r);const x=left+width*(i+.5);
    ctx.fillText(formatIndex(i),Math.max(left+22,Math.min(W-40,x)),H-9);
  });
  if(period==='24h' && n>2){
    ctx.beginPath();ctx.strokeStyle='#66e2bd';ctx.lineWidth=2.3;ctx.lineJoin='round';
    series.forEach((p,i)=>{const x=left+width*(i+.5),y=top+plotH-(p.y/nice)*plotH; i?ctx.lineTo(x,y):ctx.moveTo(x,y);});
    ctx.stroke();
  }else{
    series.forEach((p,i)=>{
      const x=left+i*width+Math.max(0,Math.min(4,width*.1));
      const h=Math.max(1,(p.y/nice)*plotH);
      ctx.fillStyle='#66e2bd';ctx.fillRect(x,top+plotH-h,Math.max(.8,width-Math.max(1,Math.min(8,width*.2))),h);
    });
  }
}
async function receiveSummary(data) {
  summary=data;render();
  window.PedalFeatures?.onSummary();
  window.PedalForge?.onSummary();
  if(Date.now()-lastHistoryFetch>2500) loadHistory();
  if(Date.now()-lastSessionsFetch>7000) loadSessions();
  if(Date.now()-lastAwardsFetch>7000) loadAchievements();
}
function connect() {
  const scheme=location.protocol==='https:'?'wss':'ws';
  socket=new WebSocket(`${scheme}://${location.host}/ws/${encodeURIComponent(device)}`);
  $('connection').textContent='Connecting';$('status-light').classList.remove('good');
  socket.onopen=()=>{reconnectDelay=1000;$('connection').textContent='Server connected';$('status-light').classList.add('good');};
  socket.onmessage=e=>{try{const msg=JSON.parse(e.data);if(msg.type==='summary')receiveSummary(msg.data);}catch(e){console.error(e);}};
  socket.onclose=()=>{socket=null;$('connection').textContent='Reconnecting';$('status-light').classList.remove('good');setTimeout(connect,reconnectDelay);reconnectDelay=Math.min(15000,reconnectDelay*1.6);};
  socket.onerror=()=>socket?.close();
}
async function start() {
  try {
    const config=await api('/api/v1/config');device=config.device_id;window.PedalFeatures?.boot(device);window.PedalForge?.boot(device);$('export-link').href=`/api/v1/devices/${encodeURIComponent(device)}/export.csv`;
    await receiveSummary(await api(`/api/v1/devices/${encodeURIComponent(device)}/summary`));
    await loadHistory(); await loadSessions(); await loadAchievements(); connect();
  } catch(e) { console.error('Startup failed:',e);$('connection').textContent='Server unavailable';setTimeout(()=>location.reload(),10000); }
}
$('achievement-filter')?.addEventListener('change',loadAchievements);
$('period-tabs').addEventListener('click',e=>{const button=e.target.closest('button[data-period]');if(!button)return;period=button.dataset.period;document.querySelectorAll('[data-period]').forEach(b=>b.classList.toggle('selected',b===button));loadHistory();});
window.addEventListener('resize',()=>{clearTimeout(chartTimer);chartTimer=setTimeout(drawChart,100);});
setInterval(render,1000);
setInterval(()=>{if(Date.now()-lastHistoryFetch>60000)loadHistory();if(Date.now()-lastSessionsFetch>60000)loadSessions();},10000);
start();
