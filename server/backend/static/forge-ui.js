'use strict';
/* PEDAL FORGE — all state is authoritative on delta2. No click-to-earn button. */
window.PedalForge = (() => {
  let device = 'bike-001';
  let lastFetch = 0;
  let loading = false;
  let working = false;
  let previous = null;
  const el = id => document.getElementById(id);
  const fmt = n => new Intl.NumberFormat('en-US', {maximumFractionDigits:2}).format(n ?? 0);

  function set(id, value) { if (el(id)) el(id).textContent = String(value); }
  function fill(id, value, max) {
    const node = el(id);
    if (node) node.style.width = `${max ? Math.min(100, Math.max(0, 100 * value / max)) : 0}%`;
  }
  function node(tag, cls, content) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (content !== undefined) n.textContent = String(content);
    return n;
  }
  async function request(endpoint, body) {
    const url = `/api/v1/devices/${encodeURIComponent(device)}/forge${endpoint}`;
    const response = await fetch(url, body === undefined ?
      {credentials:'same-origin',cache:'no-store'} :
      {method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if (response.status === 401) { location.assign('/login'); throw new Error('Please sign in again.'); }
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `Server error: ${response.status}`);
    return data;
  }
  function showFeedback(message, error = false) {
    set('forge-message', message);
    el('forge-message').classList.toggle('forge-error', error);
  }
  function upgradeCard(meta) {
    const card=node('article','forge-item');
    const top=node('div','forge-item-head');
    top.append(node('strong','',meta.name), node('span','forge-level',`Lv ${meta.level}/${meta.max_level}`));
    const description=node('p','',meta.description);
    const button=node('button','forge-action',meta.cost === null ? 'MAXED' : `Upgrade · ${fmt(meta.cost)} ⚙`);
    button.type='button';button.dataset.forgeAction='buy';button.dataset.key=meta.id;
    button.disabled=!meta.can_buy || working;
    card.append(top,description,button);
    return card;
  }
  function skillCard(meta) {
    const card=node('article',`forge-skill ${meta.unlocked?'':'forge-locked'}`);
    const top=node('div','forge-item-head');
    top.append(node('strong','',meta.name),node('span','forge-level',`Lv ${meta.level}/${meta.max_level}`));
    card.append(top,node('p','',meta.description));
    if (meta.prerequisite) card.append(node('small','forge-requirement',`Requires: ${meta.prerequisite}`));
    const button=node('button','forge-action',meta.level >= meta.max_level ? 'MASTERED' :
      meta.unlocked ? 'Learn · 1 point' : 'LOCKED');
    button.type='button';button.dataset.forgeAction='skill';button.dataset.key=meta.id;
    button.disabled=!meta.can_learn || working;
    card.append(button);
    return card;
  }
  function render(s) {
    if (previous && previous.total_game_revs !== s.total_game_revs && s.total_game_revs > previous.total_game_revs) {
      const increase=s.total_game_revs-previous.total_game_revs;
      set('forge-pulse',`+${fmt(increase)} real revolutions recorded`);
    }
    if (previous && s.prestiges > previous.prestiges) {
      showFeedback(`PRESTIGE ${s.prestiges} COMPLETE! Permanent cores: ${s.cores}.`);
    }
    previous=s;
    set('forge-wallet',fmt(s.torque));
    set('forge-rate',`+${fmt(s.torque_per_rev)} ⚙ / revolution`);
    set('forge-run',fmt(s.run_revs));
    set('forge-credited',fmt(s.total_game_revs));
    set('forge-cores',fmt(s.cores));
    set('forge-prestige-level',fmt(s.prestiges));
    set('forge-combo',s.combo >= 3 ? `× ${s.combo} steady-pulse combo` : 'Build a streak at 45+ RPM for momentum bonuses');
    set('forge-points',`${s.skill_points_available} free / ${s.skill_points_earned} earned`);
    set('forge-point-next',`${fmt(s.next_skill_point_at - s.run_revs)} rev until the next point`);
    set('forge-prestige-progress',`${fmt(s.run_revs)} / ${fmt(s.prestige_min_revs)} rev to prestige`);
    set('forge-prestige-reward',`+${fmt(s.next_prestige_cores)} permanent core(s) · +10% yield each`);
    fill('forge-prestige-bar',s.run_revs,s.prestige_min_revs);
    const prestige=el('forge-prestige');
    prestige.disabled=!s.prestige_available || working;
    const upgrades=el('forge-upgrades'); upgrades.replaceChildren();
    s.upgrades.forEach(i=>upgrades.append(upgradeCard(i)));
    const skills=el('forge-skills');skills.replaceChildren();
    for (const branch of ['POWER','MOMENTUM','ENGINEERING']) {
      const panel=node('div','forge-branch');
      panel.append(node('h3','',branch));
      const group=node('div','forge-nodes');
      s.skills.filter(i=>i.branch===branch).forEach(i=>group.append(skillCard(i)));
      panel.append(group);skills.append(panel);
    }
  }
  async function refresh(force=false) {
    if (loading || working || (!force && Date.now()-lastFetch<2500)) return;
    loading=true;lastFetch=Date.now();
    try { render(await request('')); }
    catch (error) { showFeedback(`Forge is temporarily unavailable: ${error.message}`,true); }
    finally { loading=false; }
  }
  async function act(action,key) {
    if (working) return;
    if (action==='prestige' && !confirm('PRESTIGE WILL RESET your Torque balance, upgrade levels and skill tree. Your real cycling history, achievements, total game revolutions and permanent cores stay safe. Continue?')) return;
    working=true;
    const endpoint=action==='buy'?'/buy':action==='skill'?'/skill':'/prestige';
    const body=action==='buy'?{item_id:key}:action==='skill'?{skill_id:key}:{};
    try {
      const state=await request(endpoint,body);
      showFeedback(action==='buy'?'Upgrade purchased! Ride to put it to work.':
        action==='skill'?'Skill learned! Your next pulse uses the new bonus.':'PRESTIGE COMPLETE! Permanent bonus activated.');
      render(state);
    } catch(error) { showFeedback(error.message,true); }
    finally { working=false;lastFetch=0;await refresh(true); }
  }
  function boot(id) {
    device=id;
    el('forge-panel').addEventListener('click',event=>{
      const b=event.target.closest('button[data-forge-action]');
      if (!b || b.disabled) return;
      act(b.dataset.forgeAction,b.dataset.key);
    });
    refresh(true);
    setInterval(()=>{if (document.visibilityState==='visible') refresh();},3000);
  }
  return {boot,onSummary:refresh};
})();
