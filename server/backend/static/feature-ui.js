'use strict';
// PEDAL v0.3 cockpit — independent of the WebSocket/event-ingestion protocol.
window.PedalFeatures = (() => {
  const el = id => document.getElementById(id);
  const fmt = new Intl.NumberFormat('en-US');
  let deviceId = 'bike-001';
  let latest = null;
  let cadence = [];
  let lastFetch = 0;
  let lastCadenceFetch = 0;
  let fetching = false;
  let cadenceFetching = false;
  let firstSettings = true;
  let lastLevel = null;
  let lastChallengeState = null;
  let lastDestinationCount = null;
  let previousGoals = null;

  async function get(endpoint) {
    const r = await fetch(`/api/v1/devices/${encodeURIComponent(deviceId)}/${endpoint}`,
      {credentials: 'same-origin', cache: 'no-store'});
    if (r.status === 401) {location.assign('/login'); throw new Error('Login required');}
    if (!r.ok) throw new Error(`GET ${endpoint} → ${r.status}`);
    return r.json();
  }
  async function post(endpoint, value) {
    const r = await fetch(`/api/v1/devices/${encodeURIComponent(deviceId)}/${endpoint}`,
      {method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)});
    if (r.status === 401) {location.assign('/login');throw new Error('Login required');}
    const result = await r.json();
    if (!r.ok) throw new Error(result.error || `POST ${endpoint} → ${r.status}`);
    return result;
  }
  function text(id,value){if(el(id))el(id).textContent=String(value);}
  function progress(id,current,target){
    const node=el(id); if(!node)return;
    node.style.width=`${target>0?Math.min(100,Math.max(0,100*current/target)):0}%`;
  }
  function duration(s) {
    const n=Math.max(0,Math.floor(s||0));
    return n>=3600?`${Math.floor(n/3600)}h ${Math.floor(n%3600/60)}m`:`${Math.floor(n/60)}m ${n%60}s`;
  }
  function tile(parent, className, values) {
    const item=document.createElement('div'); item.className=className;
    for(const [tag,klass,contents] of values) {
      const child=document.createElement(tag); child.className=klass; child.textContent=contents;
      item.append(child);
    }
    parent.append(item);
  }
  function toast(message) {
    const elToast=el('achievement-toast'); if(!elToast)return;
    elToast.textContent=message; elToast.classList.add('visible');
    setTimeout(()=>elToast.classList.remove('visible'),6000);
  }
  function drawLineChart() {
    const canvas=el('live-chart'); if(!canvas || !cadence.length)return;
    const b=canvas.getBoundingClientRect(); if(b.width<20||b.height<20)return;
    const dpr=window.devicePixelRatio||1;
    canvas.width=Math.round(b.width*dpr);canvas.height=Math.round(b.height*dpr);
    const c=canvas.getContext('2d'); c.scale(dpr,dpr);
    const W=b.width,H=b.height,left=35,right=10,top=14,bottom=23;
    const pw=W-left-right,ph=H-top-bottom;
    const ceiling=Math.max(100,Math.ceil(Math.max(...cadence.map(p=>p.rpm),1)/20)*20);
    c.font='11px system-ui'; c.textAlign='right';
    for(let i=0;i<=4;i++) {
      const y=top+ph-ph*i/4;
      c.strokeStyle='#2b434b';c.beginPath();c.moveTo(left,y);c.lineTo(W-right,y);c.stroke();
      c.fillStyle='#8aa5ae'; c.fillText(String(ceiling*i/4),left-8,y+3);
    }
    c.strokeStyle='#67e5bc';c.lineWidth=2.4;c.lineJoin='round';c.beginPath();
    cadence.forEach((p,i)=>{
      const x=left+i*pw/Math.max(1,cadence.length-1);
      const y=top+ph-(p.rpm/ceiling)*ph;
      if(i)c.lineTo(x,y);else c.moveTo(x,y);
    }); c.stroke();
    c.textAlign='center';c.fillStyle='#8aa5ae';
    c.fillText('5m ago',left+30,H-4);c.fillText('now',W-right-10,H-4);
    const active=cadence.filter(p=>p.rpm>0);
    text('live-avg',active.length?`Active-bin average: ${Math.round(active.reduce((s,p)=>s+p.rpm,0)/active.length)} RPM`:'No activity in the last five minutes');
  }
  async function refreshCadence(force=false) {
    if(cadenceFetching || (!force && Date.now()-lastCadenceFetch<5000))return;
    cadenceFetching=true;lastCadenceFetch=Date.now();
    try {cadence=(await get('cadence?minutes=5')).points;drawLineChart();}
    catch(error){console.error('Cadence chart:',error);}
    finally {cadenceFetching=false;}
  }
  function showQuests(quests) {
    const box=el('quest-list');box.replaceChildren();
    for(const q of quests) {
      const card=document.createElement('div');card.className='quest';
      const heading=document.createElement('div');heading.className='quest-top';
      const title=document.createElement('strong');title.textContent=`${q.icon} ${q.name}`;
      const count=document.createElement('span');count.textContent=`${fmt.format(q.progress)} / ${fmt.format(q.target)}`;
      heading.append(title,count);
      const bar=document.createElement('div');bar.className='progress-track';
      const fill=document.createElement('div');fill.className='progress-fill';fill.style.width=`${Math.min(100,100*q.progress/q.target)}%`;
      bar.append(fill);card.append(heading,bar);box.append(card);
    }
  }
  function showHeatmap(days, streak) {
    const box=el('heatmap');box.replaceChildren();
    const max=Math.max(1,...days.map(d=>d.revs));
    const fragment=document.createDocumentFragment();
    for(const day of days) {
      const square=document.createElement('span');
      const level=day.revs===0?0:Math.min(4,Math.max(1,Math.ceil(day.revs/max*4)));
      square.className=`heat-square heat-${level}`;
      square.title=`${day.date}: ${fmt.format(day.revs)} revolutions`;
      square.setAttribute('aria-label',square.title);
      fragment.append(square);
    }
    box.append(fragment);
    text('streak-summary',`${streak.current_streak} current · ${streak.best_streak} best day streak`);
  }
  function showRecords(rec, energy) {
    const box=el('records-grid');box.replaceChildren();
    const items=[
      ['🏆 Best day',`${fmt.format(rec.best_day)} rev`],
      ['🚴 Best session',`${fmt.format(rec.best_session)} rev`],
      ['⏱️ Longest session',duration(rec.longest_session_s)],
      ['⚡ Peak sampled RPM',`${fmt.format(rec.best_rpm_since_upgrade)} RPM`],
      ['🔥 Current streak',`${rec.current_streak} days`],
      ['🗓️ Best streak',`${rec.best_streak} days`],
      ['📋 Total sessions',fmt.format(rec.session_count)],
      ['▶️ Measured moving',`${rec.moving_minutes_since_upgrade} min`],
      ['🌡️ Est. energy',energy==null?'Disabled':`~${fmt.format(energy)} kcal`],
    ];
    for(const [name,value] of items)tile(box,'record',[['small','',name],['strong','',value]]);
  }
  function showSessions(sessions) {
    const box=el('session-analytics');box.replaceChildren();
    if(!sessions.length){box.textContent='No sessions recorded yet.';return;}
    for(const s of sessions.slice(0,6)){
      const when=new Date(s.started_ms).toLocaleString('en-GB',{timeZone:'Europe/Budapest',day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'});
      tile(box,'compact-session',[['strong','',`${when} · ${fmt.format(s.revs)} rev`],
        ['span','',`${duration(s.duration_s)} span · ${s.average_rpm.toFixed(1)} avg RPM · ${duration(s.moving_ms/1000)} measured moving`]]);
    }
  }
  function showAdventure(adventure) {
    text('virtual-distance',`${adventure.distance_km.toFixed(3)} km equivalent`);
    const box=el('destinations');box.replaceChildren();
    for(const [i,d] of adventure.destinations.entries()) {
      tile(box,`destination ${d.unlocked?'reached':''}`,[
        ['span','destination-icon',d.unlocked?'✅':i===0?'🚩':'🔒'],
        ['strong','',d.name],['small','',`${d.km} km · ${d.description}`]]);
    }
  }
  function showDistribution(items) {
    const box=el('rpm-distribution');box.replaceChildren();
    const max=Math.max(1,...items.map(x=>x.samples));
    for(const item of items){
      const row=document.createElement('div');row.className='distribution-row';
      const label=document.createElement('span');label.textContent=`${item.band} RPM`;
      const track=document.createElement('div');track.className='progress-track';
      const fill=document.createElement('div');fill.className='progress-fill';
      fill.style.width=`${100*item.samples/max}%`;track.append(fill);
      const count=document.createElement('span');count.textContent=fmt.format(item.samples);
      row.append(label,track,count);box.append(row);
    }
  }
  function showChallenge(state) {
    const challenge=state.current;
    if(!challenge) {text('challenge-status','No challenge started yet.');progress('challenge-bar',0,1);return;}
    const seconds=(challenge.streak_ms/1000).toFixed(1);
    const target=challenge.duration_s;
    const label=challenge.status==='completed'?'🏆 Completed':challenge.status==='cancelled'?'Stopped':'🏁 In progress';
    text('challenge-status',`${label} · ${challenge.target_rpm} RPM for ${target}s`);
    text('challenge-message',`Current consecutive streak: ${seconds}s · best: ${(challenge.best_ms/1000).toFixed(1)}s · ${state.completed_count} challenges completed`);
    progress('challenge-bar',challenge.streak_ms,challenge.duration_s*1000);
    const signature=`${challenge.id}:${challenge.status}`;
    if(lastChallengeState && signature!==lastChallengeState && challenge.status==='completed')toast('🏁 CADENCE CHALLENGE COMPLETED! +250 XP');
    lastChallengeState=signature;
  }
  function render(data) {
    latest=data;
    const {goals,rpg,records,adventure,preferences,challenge}=data;
    text('daily-goal-label',`${fmt.format(goals.daily.value)} / ${fmt.format(goals.daily.target)}`);
    text('weekly-goal-label',`${fmt.format(goals.weekly.value)} / ${fmt.format(goals.weekly.target)}`);
    progress('daily-goal-bar',goals.daily.value,goals.daily.target);
    progress('weekly-goal-bar',goals.weekly.value,goals.weekly.target);
    text('rpg-level',rpg.level);
    const className=rpg.level>=20?'Pedal Myth':rpg.level>=10?'Office Olympian':
      rpg.level>=7?'Crank Commander':rpg.level>=4?'Cadence Cadet':
      rpg.level>=2?'Desk Cyclist':'First Timer';
    text('level-title',`— ${className}`);
    text('rpg-xp',`${fmt.format(rpg.xp)} XP`);
    text('xp-progress',`${fmt.format(rpg.xp-rpg.level_start_xp)} / ${fmt.format(rpg.next_level_xp-rpg.level_start_xp)} XP to next level`);
    progress('xp-fill',rpg.xp-rpg.level_start_xp,rpg.next_level_xp-rpg.level_start_xp);
    text('challenge-bonus',`${rpg.completed_challenges} completed challenges`);
    if(lastLevel!==null && rpg.level>lastLevel)toast(`🎉 LEVEL UP! You reached level ${rpg.level}`);
    lastLevel=rpg.level;
    showQuests(data.quests);showHeatmap(data.heatmap,records);
    showRecords(records,data.energy_kcal_estimate);
    showSessions(data.recent_sessions);
    showDistribution(data.cadence_distribution);
    showAdventure(adventure);
    const reached=adventure.destinations.filter(d=>d.unlocked).length;
    if(lastDestinationCount!==null && reached>lastDestinationCount){
      const unlocked=adventure.destinations[reached-1];
      toast(`🌎 VIRTUAL DESTINATION UNLOCKED — ${unlocked.name}`);
    }
    lastDestinationCount=reached;
    if(previousGoals){
      if(previousGoals.daily<goals.daily.target && goals.daily.value>=goals.daily.target)
        toast('🎯 DAILY GOAL COMPLETE!');
      else if(previousGoals.weekly<goals.weekly.target && goals.weekly.value>=goals.weekly.target)
        toast('🗓️ WEEKLY GOAL COMPLETE!');
    }
    previousGoals={daily:goals.daily.value,weekly:goals.weekly.value};
    showChallenge(challenge);
    if(firstSettings) {
      el('set-daily').value=preferences.daily_goal;
      el('set-weekly').value=preferences.weekly_goal;
      el('set-distance').value=preferences.meters_per_rev;
      el('set-rpm').value=preferences.target_rpm;
      el('set-weight').value=preferences.weight_kg??'';
      el('challenge-rpm').value=preferences.target_rpm;
      firstSettings=false;
    }
  }
  async function refresh(force=false) {
    if(fetching || (!force && Date.now()-lastFetch<12000))return;
    lastFetch=Date.now();fetching=true;
    try{render(await get('features'));}
    catch(error){console.error('Features:',error);text('settings-feedback',`Unable to refresh: ${error.message}`);}
    finally{fetching=false;}
  }
  function boot(id) {
    deviceId=id;
    el('challenge-form').addEventListener('submit',async event=>{
      event.preventDefault();
      try{
        await post('challenge/start',{target_rpm:Number(el('challenge-rpm').value),duration_s:Number(el('challenge-seconds').value)});
        lastFetch=0;await refresh(true);
      }catch(e){text('challenge-message',e.message);}
    });
    el('stop-challenge').addEventListener('click',async()=>{
      try{await post('challenge/stop',{});lastFetch=0;await refresh(true);}
      catch(e){text('challenge-message',e.message);}
    });
    el('settings-form').addEventListener('submit',async event=>{
      event.preventDefault();
      const weight=el('set-weight').value.trim();
      const data={daily_goal:Number(el('set-daily').value),weekly_goal:Number(el('set-weekly').value),
        meters_per_rev:Number(el('set-distance').value),target_rpm:Number(el('set-rpm').value),
        weight_kg:weight===''?null:Number(weight)};
      try{
        await post('preferences',data);text('settings-feedback','Saved!');
        lastFetch=0;firstSettings=true;await refresh(true);
      }catch(e){text('settings-feedback',`Unable to save: ${e.message}`);}
    });
    window.addEventListener('resize',()=>requestAnimationFrame(drawLineChart));
    refresh(true);refreshCadence(true);
    setInterval(()=>{if(document.visibilityState==='visible'){
      refresh();refreshCadence();}},5000);
  }
  return {boot,onSummary(){refresh();refreshCadence();}};
})();
