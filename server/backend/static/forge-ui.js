'use strict';
/* PEDAL GEARBOUND — arena, skills and game mode. */
window.PedalForge = (() => {
  let device = 'bike-001';
  let lastFetch = 0;
  let loading = false;
  let working = false;
  let mutation = 0;
  let previous = null;
  let shopTab = 'PRODUCTION';
  let skillTab = 'COMBAT';
  const contractCards = new Map();
  const el = id => document.getElementById(id);
  const fmt = n => new Intl.NumberFormat('en-US', {maximumFractionDigits:2}).format(n ?? 0);
  const set = (id,value) => {
    const target=el(id);
    if(target && target.textContent!==String(value)) target.textContent=String(value);
  };
  const fill = (id,value,max) => { const target=el(id); if(target) target.style.width=`${max ? Math.min(100,Math.max(0,value/max*100)) : 0}%`; };
  function node(tag,cls,content) {
    const n=document.createElement(tag);
    if(cls) n.className=cls;
    if(content !== undefined) n.textContent=String(content);
    return n;
  }
  async function request(endpoint,body) {
    const url=`/api/v1/devices/${encodeURIComponent(device)}/forge${endpoint}`;
    const response=await fetch(url,body===undefined ?
      {credentials:'same-origin',cache:'no-store'} :
      {method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(response.status===401) { location.assign('/login'); throw new Error('Please sign in again.'); }
    const result=await response.json();
    if(!response.ok) throw new Error(result.error||`Server error: ${response.status}`);
    return result;
  }
  function feedback(message,isError=false,target='forge-message') {
    set(target,message);
    el(target).classList.toggle('forge-error',isError);
  }
  function button(text,action,key,disabled=false,extra='') {
    const b=node('button',`forge-action ${extra}`,text);
    b.type='button';b.dataset.forgeAction=action;b.dataset.key=key;
    b.disabled=disabled||working;
    return b;
  }
  function upgradeCard(m) {
    const card=node('article',`forge-item${!m.unlocked?' forge-locked':''}`);
    const head=node('div','forge-item-head');
    head.append(node('strong','',m.name),node('span','forge-level',`Lv ${m.level}/${m.max_level}`));
    card.append(head,node('p','',m.description));
    if(!m.unlocked) card.append(node('small','forge-requirement',`🔒 Reach sector ${m.requires_sector}`));
    const price=m.cost===null ? 'MAX LEVEL' : `Upgrade · ${fmt(m.cost)} ⚙${m.scrap_cost ? ` + ${fmt(m.scrap_cost)} 🔩` : ''}`;
    card.append(button(price,'buy',m.id,!m.can_buy));
    return card;
  }
  function skillCard(m) {
    const card=node('article',`forge-skill${!m.unlocked?' forge-locked':''}`);
    const head=node('div','forge-item-head');
    head.append(node('strong','',m.name),node('span','forge-level',`Lv ${m.level}/${m.max_level}`));
    card.append(head,node('p','',m.description));
    if(m.prerequisite) card.append(node('small','forge-requirement',`Requires: ${m.prerequisite}`));
    card.append(button(m.level>=m.max_level?'MASTERED':m.unlocked?'Learn · 1 point':'LOCKED',
                       'skill',m.id,!m.can_learn));
    return card;
  }
  function relicCard(m) {
    const card=node('article','forge-item forge-relic-item');
    const head=node('div','forge-item-head');
    head.append(node('strong','',m.name),node('span','forge-level',`Lv ${m.level}/${m.max_level}`));
    card.append(head,node('p','',m.description));
    card.append(button(m.cost===null?'PERMANENTLY MASTERED':`Research · ${fmt(m.cost)} 💎`,
                       'relic',m.id,!m.can_buy));
    return card;
  }
  function tabs(target,values,current,category) {
    const holder=el(target);if(!holder) return;
    const frag=document.createDocumentFragment();
    values.forEach(v => {
      const b=node('button',`forge-tab${current===v?' active':''}`,v);
      b.type='button';b.dataset.forgeTab=category;b.dataset.key=v;
      b.setAttribute('aria-pressed',String(current===v));
      frag.append(b);
    });
    holder.replaceChildren(frag);
  }
  const stanceNames = {balanced:'Balanced', assault:'Assault', guard:'Guard'};
  function renderBoss(boss,tactic,active) {
    const panel=el('forge-boss-readout');
    const arena=el('forge-arena');
    panel.hidden=!boss;
    arena.dataset.bossPhase=boss?.phase ?? '';
    if(!boss) return;
    const meter=el('forge-boss-meter');
    const counter=el('forge-boss-counter');
    const response=stanceNames[boss.response];
    const windup=boss.phase==='windup';
    const open=boss.phase==='opening';
    const ready=tactic===boss.response;
    counter.hidden=!active || !windup || ready;
    counter.disabled=working;
    counter.dataset.key=boss.response;
    counter.textContent=`Switch to ${response}`;
    set('forge-boss-phase',!active ? 'FIGHT PAUSED' :
      open ? 'ARMOR OPEN' : windup ? (ready ? 'COUNTER READY' : 'INCOMING MOVE') : 'BOSS INTEL');
    set('forge-boss-move',boss.move);
    const count=boss.hits_until_move;
    const impact=count===1 ? 'Next hit' : `${count} hits until impact`;
    if(open) {
      set('forge-boss-hint',`Bonus damage for ${boss.opening_hits} more hit${boss.opening_hits===1?'':'s'}.`);
    } else if(windup) {
      set('forge-boss-hint',`${impact}. ${response} at impact opens its armor.`);
    } else {
      set('forge-boss-hint',`Watch for the windup. ${response} can counter this move.`);
    }
    meter.max=open ? boss.opening_size : boss.cycle_hits;
    meter.value=open ? boss.opening_hits : boss.cycle_hits-count;
  }
  function renderContracts(contracts,prev,active) {
    const holder=el('forge-contracts');
    for(const contract of contracts) {
      const {id,name,goal,torque,scrap,target,progress,completions}=contract;
      let card=contractCards.get(id);
      if(!card) {
        card=el('forge-contract-card').content.firstElementChild.cloneNode(true);
        card.querySelector('[data-contract-name]').textContent=name;
        card.querySelector('[data-contract-goal]').textContent=goal;
        card.querySelector('[data-contract-meter]').setAttribute('aria-label',`${name} progress`);
        holder.append(card);
        contractCards.set(id,card);
      }
      const rewards=[];
      if(torque) rewards.push(`+${fmt(torque)} Torque`);
      if(scrap) rewards.push(`+${fmt(scrap)} Scrap`);
      card.querySelector('[data-contract-reward]').textContent=rewards.join(' · ');
      const complete=progress===target;
      card.dataset.state=contract.active ? (active ? 'active' : 'paused') : complete ? 'complete' : 'idle';
      card.querySelector('[data-contract-progress]').textContent=complete ? 'Complete' : `${progress} / ${target}`;
      const meter=card.querySelector('[data-contract-meter]');
      meter.max=target;
      meter.value=progress;
      const action=card.querySelector('button');
      action.dataset.key=contract.active ? '' : id;
      action.textContent=contract.active ? 'Pause contract' : complete ? 'Ride again' :
        progress>0 ? 'Resume contract' : 'Start contract';
      action.setAttribute('aria-label',`${action.textContent}: ${name}`);
      action.disabled=!active || working;
      const old=prev?.find(item=>item.id===id);
      if(old && completions>old.completions) {
        feedback(`📜 ${name} complete! ${rewards.join(' · ')}`,false,'forge-contract-message');
      }
    }
    set('forge-contract-summary',active ? 'Pick one goal. Switch or pause it anytime and keep your progress.' :
      'Game OFF. Your contract progress is saved.');
  }
  function renderArena(c,prev,active) {
    set('forge-scrap',fmt(c.scrap));
    set('forge-relics',fmt(c.relics));
    set('forge-sector',fmt(c.sector));
    set('forge-sector-name',c.sector_name);
    set('forge-wave-count',`Wave ${c.wave} / ${c.waves_per_sector}`);
    set('forge-boss-label',c.enemy.boss?'👑 SECTOR BOSS':'⚔ FIELD ENCOUNTER');
    el('forge-boss-label').classList.toggle('boss',c.enemy.boss);
    set('forge-enemy-art',c.enemy.emoji);
    set('forge-enemy-name',c.enemy.name);
    set('forge-enemy-desc',c.enemy.subtitle);
    set('forge-enemy-health',`${fmt(c.enemy_hp)} / ${fmt(c.enemy_max_hp)}`);
    set('forge-player-health',`${fmt(c.hero_hp)} / ${fmt(c.hero_max_hp)}`);
    set('forge-attack',fmt(c.hero_attack));
    set('forge-armor',fmt(c.armor));
    set('forge-crit',fmt(c.crit_every));
    set('forge-kills',fmt(c.kills_total));
    set('forge-bosses',fmt(c.bosses_total));
    fill('forge-enemy-bar',c.enemy_hp,c.enemy_max_hp);
    fill('forge-player-bar',c.hero_hp,c.hero_max_hp);
    const waveHolder=el('forge-waves');
    const waves=document.createDocumentFragment();
    for(let i=1;i<=c.waves_per_sector;i++) {
      const step=node('span',`forge-wave${i<c.wave?' cleared':''}${i===c.wave?' active':''}${i===c.waves_per_sector?' boss':''}`,i===c.waves_per_sector?'👑':`${i}`);
      step.title=i===c.waves_per_sector?'Boss':'Wave '+i;
      waves.append(step);
    }
    waveHolder.replaceChildren(waves);
    el('forge-tactics').querySelectorAll('button').forEach(b=>{
      b.classList.toggle('active',b.dataset.key===c.tactic);
      b.setAttribute('aria-pressed',String(b.dataset.key===c.tactic));
      b.disabled=working;
    });
    set('forge-stance-explain',{balanced:'⚖️ Balanced · normal attack and incoming damage',assault:'⚔️ Assault · +50% outgoing damage, +50% incoming damage',guard:'🛡️ Guard · -20% outgoing damage, -35% incoming damage'}[c.tactic]);
    renderBoss(c.boss,c.tactic,active);
    const burst=c.burst;
    const burstPanel=el('forge-burst');
    burstPanel.hidden=!burst;
    let burstFired=false;
    if(burst) {
      const meter=el('forge-burst-meter');
      meter.max=burst.hits;
      meter.value=burst.charge;
      const remaining=burst.hits-burst.charge;
      burstPanel.classList.toggle('forge-burst-ready',remaining===1 && active);
      const charge=remaining===1 ? 'Next hit fires' : `${remaining} hits to burst`;
      set('forge-burst-status',active ? charge : `Paused · ${charge.toLowerCase()}`);
      // A dashboard refresh can include more than one pedal stroke.
      burstFired=Boolean(prev?.burst &&
        Math.floor(c.attacks/burst.hits)>Math.floor(prev.attacks/burst.hits));
    }
    const hit=c.last_hit ? `-${fmt(c.last_hit)} enemy hull${c.last_crit?' · 💥 CRITICAL':''}${c.last_counter?` · ${fmt(c.last_counter)} counter damage`:''}` : 'Pedal to land your first strike.';
    set('forge-last-hit',burstFired ? `⚡ Flywheel Burst fired! · ${hit}` : hit);
    const logHolder=el('forge-battle-feed');
    logHolder.replaceChildren(...c.log.map(item=>node('div','forge-log-line',item.description)));
    if(!c.log.length) logHolder.append(node('span','forge-log-empty','Your victories will appear here.'));
    if(prev && c.attacks>prev.attacks) {
      const art=el('forge-enemy-art');
      art.classList.remove('forge-impact','forge-burst-impact');
      void art.offsetWidth;
      art.classList.add(burstFired ? 'forge-burst-impact' : 'forge-impact');
    }
  }
  function render(s) {
    const prev=previous;
    const active=Boolean(s.enabled);
    const modeButton=el('forge-mode-toggle');
    if(modeButton) {
      modeButton.textContent=active?'Pause game · OFF':'Resume game · ON';
      modeButton.dataset.key=active?'off':'on';
      modeButton.disabled=working;
      modeButton.setAttribute('aria-pressed',String(active));
    }
    set('forge-mode-status',active?'⚔️ GAME ON':'🚴 GAME OFF · FITNESS ONLY');
    set('forge-mode-hint',active?
      'Battles and game rewards advance only while you pedal. No deaths or involuntary resets.' :
      'Exercise recording, goals and fitness achievements continue normally. Game currencies, enemies and skill progress are frozen.');
    el('forge-panel').classList.toggle('forge-paused',!active);
    if(prev && s.total_game_revs>prev.total_game_revs) {
      set('forge-pulse',`+${fmt(s.total_game_revs-prev.total_game_revs)} newly committed revolutions`);
    }
    if(prev && s.prestiges>prev.prestiges) feedback(`✨ PRESTIGE ${s.prestiges}! Your permanent relic research survived.`);
    if(prev && s.combat.bosses_total>prev.combat.bosses_total) {
      feedback(`👑 Boss defeated! Welcome to sector ${s.combat.sector}.`,false,'forge-arena-message');
    } else if(prev && s.combat.kills_total>prev.combat.kills_total) {
      feedback(`⚔️ Enemy down! Scrap bank: ${fmt(s.combat.scrap)}.`,false,'forge-arena-message');
    } else if(prev?.combat.boss && prev.combat.boss.phase!=='opening' && s.combat.boss?.phase==='opening') {
      feedback('🎯 Counter landed. Hit while the armor is open!',false,'forge-arena-message');
    } else if(prev?.combat.boss?.phase==='opening' && s.combat.boss?.phase!=='opening') {
      set('forge-arena-message','');
    }
    previous=s;
    // Browsing remains available while paused; mutations are disabled.
    set('forge-wallet',fmt(s.torque));
    set('forge-rate',`+${fmt(s.torque_per_rev)} ⚙ / revolution`);
    set('forge-run',fmt(s.run_revs));
    set('forge-credited',fmt(s.total_game_revs));
    set('forge-cores',fmt(s.cores));
    set('forge-prestige-level',fmt(s.prestiges));
    set('forge-combo',s.combo>=3 ? `🔥 ${s.combo}-pulse cadence combo · bonus damage active` :
      'Build a steady 45+ RPM cadence combo for additional damage');
    set('forge-points',`${s.skill_points_available} free / ${s.skill_points_earned} earned`);
    set('forge-point-next',`${fmt(s.next_skill_point_at-s.run_revs)} rev until next skill point`);
    set('forge-prestige-progress',`${fmt(s.run_revs)} / ${fmt(s.prestige_min_revs)} rev to prestige`);
    set('forge-prestige-reward',`+${fmt(s.next_prestige_cores)} permanent core(s) · +10% yield each`);
    fill('forge-prestige-bar',s.run_revs,s.prestige_min_revs);
    el('forge-prestige').disabled=!s.prestige_available||working;
    renderArena(s.combat,prev?.combat,active);
    renderContracts(s.contracts ?? [],prev?.contracts,active);
    const shopCategories=[...new Set(s.upgrades.map(i=>i.category))];
    if(!shopCategories.includes(shopTab)) shopTab=shopCategories[0];
    tabs('forge-shop-tabs',shopCategories,shopTab,'shop');
    set('forge-upgrade-count',`${s.upgrades.length} upgrades`);
    el('forge-upgrades').replaceChildren(...s.upgrades.filter(i=>i.category===shopTab).map(upgradeCard));
    const branches=[...new Set(s.skills.map(i=>i.branch))];
    if(!branches.includes(skillTab)) skillTab=branches[0];
    tabs('forge-skill-tabs',branches,skillTab,'skill');
    set('forge-skill-count',`${s.skills.length} nodes`);
    el('forge-skills').replaceChildren(...s.skills.filter(i=>i.branch===skillTab).map(skillCard));
    set('forge-relic-balance',`${fmt(s.combat.relics)} 💎 available`);
    el('forge-permanent').replaceChildren(...s.combat.permanent.map(relicCard));
    if(!active) el('forge-panel').querySelectorAll('button[data-forge-action]:not(#forge-mode-toggle)')
      .forEach(button=>{button.disabled=true;});
  }
  async function refresh(force=false) {
    if(loading||working||(!force&&Date.now()-lastFetch<2500)) return;
    loading=true;lastFetch=Date.now();
    const startedAt=mutation;
    try {
      const state=await request('');
      if(startedAt===mutation) render(state);
    }
    catch(error) { if(startedAt===mutation) feedback(`Gearbound is unavailable: ${error.message}`,true); }
    finally { loading=false; }
  }
  async function act(action,key) {
    if(working) return;
    if(action==='mode') {
      working=true;mutation++;
      try {
        const s=await request('/mode',{enabled:key==='on'});
        render(s);
        feedback(s.enabled?'⚔️ Game resumed!':'🚴 Game paused. Your workout tracking continues.');
      } catch(error) { feedback(error.message,true); }
      finally { working=false;lastFetch=0;await refresh(true); }
      return;
    }
    if(previous&&!previous.enabled) { feedback('Game is OFF. Resume it to make changes.',true);return; }
    if(action==='prestige'&&!confirm('Prestige resets THIS RUN: Torque, Scrap, sector, enemies, upgrades and skill levels. PERMANENT: relic research, relic bank, cores, lifetime combat wins, cycling history and achievements. Continue?')) return;
    const calls={buy:['/buy',{item_id:key}],skill:['/skill',{skill_id:key}],
      tactic:['/tactic',{tactic:key}],relic:['/relic',{trait_id:key}],prestige:['/prestige',{}],
      contract:['/contract',{contract_id:key || null}]};
    if(!calls[action]) return;
    working=true;mutation++;
    const target=action==='contract' ? 'forge-contract-message' : 'forge-message';
    try {
      const s=await request(...calls[action]);
      render(s);
      feedback({buy:'⚙️ Upgrade installed! Next pedals use it.',skill:'🌳 Skill acquired!',
        tactic:`Combat stance: ${key.toUpperCase()}`,relic:'💎 Permanent research unlocked!',
        prestige:'✨ PRESTIGE COMPLETE! The Cranklands await again.',
        contract:key ? 'Contract selected.' : 'Contract paused. Progress saved.'}[action],false,target);
    } catch(error) { feedback(error.message,true,target); }
    finally { working=false;lastFetch=0;await refresh(true); }
  }
  function boot(id) {
    device=id;
    el('forge-panel').addEventListener('click',event=>{
      const b=event.target.closest('button');
      if(!b||b.disabled) return;
      if(b.dataset.forgeTab==='shop') { shopTab=b.dataset.key; if(previous) render(previous);return; }
      if(b.dataset.forgeTab==='skill') { skillTab=b.dataset.key; if(previous) render(previous);return; }
      if(b.dataset.forgeAction) act(b.dataset.forgeAction,b.dataset.key);
    });
    refresh(true);
    setInterval(()=>{if(document.visibilityState==='visible')refresh();},3000);
  }
  return {boot,onSummary:refresh};
})();
