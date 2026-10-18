/* The viewer.  It renders what the API returns and computes nothing --
   every probability, adjustment and band on this page was produced by the
   Python model, and the "raw output" panel under each answer is the literal
   text `tennis.py price` would have printed.  If this file ever appears to
   know something the CLI does not, this file is wrong.

   How it is meant to be used: type a surname, press Enter, type another,
   press Enter.  Everything else is optional and explains itself. */

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

const fmt = {
  p:  v => (v * 100).toFixed(1) + '%',
  p4: v => v.toFixed(4),
  odds: v => v.toFixed(2),
  n:  v => Math.round(v).toLocaleString(),
  sg: v => (v >= 0 ? '+' : '') + v.toFixed(4),
  pts: v => (v >= 0 ? '+' : '−') + Math.abs(v * 100).toFixed(1),
};
const esc = s => String(s ?? '').replace(/[&<>"]/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const S = { meta: null, roster: [], a: null, b: null, focus: null, next: 'a',
            hi: 0, hints: {}, hintsLower: {} };
const narrow = () => window.matchMedia('(max-width:760px)').matches;
// features.ENTRY, by index: how the archive says a player got into the draw
const ENTRY_NAMES = ['main draw', 'qualifier', 'wild card', 'lucky loser', 'protected ranking', 'special exempt', 'other'];
const entryName = v => (v === null || v === undefined) ? null : (ENTRY_NAMES[v] ?? String(v));

async function api(path, params = {}) {
  const q = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== null && v !== undefined && v !== ''));
  const r = await fetch(path + (q.toString() ? '?' + q : ''));
  const j = await r.json();
  if (j.error) throw new Error(j.error);
  return j;
}

/* ------------------------------------------------------------- header */

async function loadMeta() {
  const m = S.meta = await api('/api/meta');
  const bits = [
    `as of ${m.asof}`,
    `${fmt.n(m.rated)} rated of ${fmt.n(m.players)}`,
    `${fmt.n(m.matches)} matches`,
    `tour serve ${m.tour_avg.toFixed(4)}`,
  ];
  let html = bits.join('  ·  ');
  if (m.stale_days > 21)
    html += `  ·  <span class="warn">data ends ${m.data_end}, ${m.stale_days}d behind</span>`;
  if (!m.calibration || Math.abs(m.calibration - 1) < 1e-9)
    html += '  ·  calibration off';
  $('#meta').innerHTML = html;
  $('#venues').innerHTML = m.venues.map(v => `<option value="${esc(v)}">`).join('');
  S.hints = m.venue_hints || {};
  S.hintsLower = Object.fromEntries(Object.entries(S.hints).map(([k, v]) => [k.toLowerCase(), v]));
}

/* ------------------------------------------------------------- roster */

let rosterTimer = null;
function rosterSoon() { clearTimeout(rosterTimer); rosterTimer = setTimeout(loadRoster, 140); }

async function loadRoster() {
  clearTimeout(rosterTimer);
  const q = $('#q').value.trim();
  const r = await api('/api/players', {
    q,
    surface: $('#surface-filter').value,
    min_pts: $('#min-pts').value,
    sort: $('#sort').value,
    limit: 400,
  });
  S.roster = r.rows;
  S.hi = 0;
  const sort = $('#sort').value;
  const val = row => ({
    p_vs_avg: fmt.p(row.p_vs_avg),
    serve: row.serve.toFixed(4),
    ret: row.ret.toFixed(4),
    pts: fmt.n(row.pts),
    matches: row.matches + ' m',
    form_sd: row.form_sd.toFixed(4),
    name: fmt.p(row.p_vs_avg),
  }[sort] ?? fmt.p(row.p_vs_avg));

  $('#roster-count').textContent = q
    ? (r.n ? `${r.n} match${r.n === 1 ? '' : 'es'} — ↵ picks the first as ${S.next.toUpperCase()}, ↑↓ to choose another`
           : 'nothing matched — try fewer letters')
    : `${r.n} player${r.n === 1 ? '' : 's'}` + (r.n > r.rows.length ? `, showing ${r.rows.length}` : '');
  $('#roster-list').innerHTML = r.rows.map((row, i) => `
    <li data-id="${esc(row.id)}" class="${row.id === S.a?.id ? 'sel-a' : ''}${row.id === S.b?.id ? 'sel-b' : ''}${q && i === 0 ? ' hi' : ''}">
      <span class="rk">${row.rank}</span>
      <span class="nm">${esc(row.name)}${row.why && row.why !== 'exact' ? ` <span class="why">${esc(row.why)}</span>` : ''}${row.thin ? ' <span class="why">thin data</span>' : ''}</span>
      <span class="val">${val(row)}</span>
    </li>`).join('') || '<li class="why" style="padding:14px 12px">nothing matched</li>';
}

function moveHi(d) {
  const lis = $$('#roster-list li[data-id]');
  if (!lis.length) return;
  S.hi = Math.max(0, Math.min(lis.length - 1, S.hi + d));
  lis.forEach((li, i) => li.classList.toggle('hi', i === S.hi));
  lis[S.hi].scrollIntoView({ block: 'nearest' });
}

/* -------------------------------------------------------- the two slots */

function paintSlots() {
  for (const k of ['a', 'b']) {
    const el = $('#slot-' + k), who = S[k];
    el.classList.toggle('filled', !!who);
    el.classList.toggle('next', S.next === k && (!who || (S.a && S.b)));
    $('.who', el).textContent = who ? who.name : `player ${k.toUpperCase()} — type a name`;
  }
  $$('#roster-list li').forEach(li => {
    li.classList.toggle('sel-a', li.dataset.id === S.a?.id);
    li.classList.toggle('sel-b', li.dataset.id === S.b?.id);
  });
  // on a phone the index folds away once both players are in, so the call has the screen
  const both = S.a && S.b;
  $('#roster').classList.toggle('tucked', !!(both && narrow()));
  $('#untuck').hidden = !(both && narrow());
}

function choose(id) {
  const row = S.roster.find(r => r.id === id);
  if (!row) return;
  S.focus = row;
  if (S.a?.id === id) { S.a = null; S.next = 'a'; }
  else if (S.b?.id === id) { S.b = null; S.next = 'b'; }
  else {
    const k = S.next;
    S[k] = row;
    S.next = !S.a ? 'a' : !S.b ? 'b' : (k === 'a' ? 'b' : 'a');
  }
  paintSlots();
  refresh();
  loadPlayer(id);
}

/* ------------------------------------------------------------ the price */

function conditions() {
  return {
    a: S.a?.id, b: S.b?.id,
    surface: $('#surface').value,
    best_of: $('#best-of').value,
    at: $('#at').value.trim(),
    curves: $('#curves').checked ? 1 : 0,
    entry_a: $('#entry-a').value,
    entry_b: $('#entry-b').value,
    odds_a: $('#odds-a').value,
    odds_b: $('#odds-b').value,
  };
}

/* the address bar carries the match, so a reload -- or a pasted link -- comes back to it */
function pushState() {
  const c = conditions();
  const keep = Object.entries(c).filter(([k, v]) =>
    k === 'curves' ? v === 0 : (v !== '' && v !== null && v !== undefined));
  const h = new URLSearchParams(keep).toString();
  history.replaceState(null, '', location.pathname + (h ? '#' + h : ''));
}

async function restore() {
  const h = new URLSearchParams(location.hash.slice(1));
  if (!h.toString()) return false;
  const map = { surface: '#surface', best_of: '#best-of', at: '#at', entry_a: '#entry-a',
                entry_b: '#entry-b', odds_a: '#odds-a', odds_b: '#odds-b' };
  for (const [k, sel] of Object.entries(map)) if (h.has(k)) $(sel).value = h.get(k);
  if (h.get('curves') === '0') $('#curves').checked = false;
  for (const k of ['a', 'b']) {
    if (!h.get(k)) continue;
    try {
      const p = await api('/api/player', { id: h.get(k) });
      if (p.id) S[k] = { id: p.id, name: p.name, rank: p.rank, p_vs_avg: p.p_vs_avg,
                         serve: p.serve, ret: p.ret, pts: p.pts, form_sd: p.form_sd, matches: p.matches };
    } catch { /* an id that no longer rates: leave the slot empty */ }
  }
  S.next = !S.a ? 'a' : !S.b ? 'b' : 'a';
  // a link that names the tournament but not the surface or format takes both from the archive
  applyVenue(!h.has('surface') && !h.has('best_of'));
  paintSlots();
  if (S.a) loadPlayer(S.a.id);
  refresh();
  return true;
}

/* naming a tournament sets the two controls people forget, from the archive's own record of it */
function applyVenue(setControls = true) {
  const at = $('#at').value.trim();
  const h = S.hints[at] || S.hintsLower[at.toLowerCase()];
  const note = $('#venue-note');
  if (!at) { note.textContent = ''; return; }
  if (!h) {
    note.textContent = `no record of "${at}" in the archive — surface and format stay as set; venue conditions may still resolve`;
    return;
  }
  if (setControls) {
    if (h.surface && $$('#surface option').some(o => o.value === h.surface)) $('#surface').value = h.surface;
    if (h.best_of === 3 || h.best_of === 5) $('#best-of').value = String(h.best_of);
  }
  note.textContent = `${h.surface || 'surface unknown'}, best of ${h.best_of} — as last played there (${h.last.slice(0, 4)}); change them above if this edition differs`;
}

function guideHTML() {
  return `
    <div class="guide">
      <ol>
        <li><b>Type a surname</b> in the box on the left and press <kbd>↵</kbd>. That is player A.</li>
        <li><b>Type another</b> and press <kbd>↵</kbd>. That is player B. Clicking a name works too.</li>
        <li><b>Read the call.</b> Name the tournament above to set the surface and format and to let the
            form/run curves see the draw. Type the bookmaker's odds to see where the model disagrees.</li>
      </ol>
      <button class="primary" id="example">show me an example</button>
      <span class="small" style="margin-left:12px">the two highest-rated players on file, best of three</span>
    </div>`;
}

async function example() {
  const top = (await api('/api/players', { min_pts: 1500, limit: 2 })).rows;
  if (top.length < 2) return;
  for (const row of top) if (!S.roster.some(r => r.id === row.id)) S.roster.push(row);
  S.a = top[0]; S.b = top[1]; S.next = 'a';
  paintSlots(); refresh(); loadPlayer(S.a.id);
}

function priceHTML(r) {
  const surfBit = s => s.surf_w
    ? `surface ${fmt.p(s.surf_w)} on ${fmt.n(s.surf_n)} pts`
    : (r.surface ? 'no surface split' : 'all surfaces');
  // a CSS grid fills row-major, so the two players have to be interleaved
  // rather than concatenated, or A's third line lands in B's column
  const facts = s => [
    `serve ${s.serve.toFixed(4)}`,
    `return ${s.ret.toFixed(4)}`,
    `form_sd ${s.form_sd.toFixed(4)}`,
    `${fmt.n(s.pts)} service pts`,
    surfBit(s),
  ];
  const bits = () => {
    const A = facts(r.a), B = facts(r.b);
    return A.map((x, i) => `<div class="a">${x}</div><div class="b">${B[i]}</div>`).join('');
  };

  const rows = [];
  const row = (k, v, note = '') => rows.push(
    `<tr><td>${k}</td><td class="num">${v}</td><td class="note">${note}</td></tr>`);

  row('tour average serve here', r.tour_avg.toFixed(4),
      r.surface ? `on ${r.surface}` : 'all surfaces');
  row('point win on serve', `${r.pa_serve.toFixed(4)} / ${r.pb_serve.toFixed(4)}`,
      'A / B, opponent-adjusted');
  if (r.dens_why) row('conditions', r.dens ? fmt.sg(r.dens) : '—', esc(r.dens_why));
  if (r.dens_shift) row('air density', fmt.sg(-r.dens_shift),
                        'both serves, symmetric — barely moves a moneyline');
  if (r.curves_on)
    row('form/run curves', r.curve_dp ? fmt.sg(r.curve_dp) : '0.0000',
        r.curve_adj
          ? `log-odds ${fmt.sg(4 * r.curve_adj)}, antisymmetric — fitted shapes, not weights`
          : 'no run data at this event');
  if (r.stage_serve)
    row('three-stage serve', `${r.stage_serve[0].toFixed(4)} / ${r.stage_serve[1].toFixed(4)}`,
        'serve in, won on the first, won on the second — each adjusted for the opponent separately');
  (r.event_update || []).forEach(e =>
    row(`in-event · ${esc(e.name)}`, `${fmt.sg(e.d_serve)} / ${fmt.sg(e.d_ret)}`,
        `${e.matches} match${e.matches === 1 ? '' : 'es'} here, ${Math.round(e.pts)} service points — serve / return`));
  (r.news || []).forEach(n =>
    row(`news · ${esc(n.name)}`, `${fmt.sg(n.d_serve)} / ${fmt.sg(n.d_ret)}`
        + (n.var_x > 1 ? ` · sd ×${n.var_x.toFixed(2)}` : '')
        + (n.retire ? ` · retire ${(100 * n.retire).toFixed(0)}%` : ''),
        `severity ${n.severity}${n.issue ? ', ' + esc(n.issue) : ''} · ${esc(n.area)} · ${esc(n.sourcing)} · ${n.age_days}d old, decay ${n.decay.toFixed(2)}${n.played_since ? `, ${n.played_since} matches since` : ''}`));
  if (r.calibration) row('calibration', `${r.p_raw.toFixed(4)} → ${r.p_a.toFixed(4)}`,
                         `slope ${r.calibration.toFixed(3)}`);

  const c = r.confidence;
  const conf = c ? `
    <h3>how far to trust this one</h3>
    <div class="rows">
      <div class="r"><div class="k">band</div>
        <div class="v"><span class="band ${c.band}">${c.band}</span></div>
        <div class="s">${c.realised && c.realised.surprise !== null && c.realised.surprise !== undefined
          ? `on ${fmt.n(c.realised.n)} held-out matches this band came out ${fmt.sg(c.realised.surprise)} nats worse than the model's own confidence implied — re-derived with the model`
          : 'no measurement on file for this band'}</div></div>
      <div class="r"><div class="k">thinner side</div>
        <div class="v">${fmt.n(c.min_pts)}</div>
        <div class="s">service points behind the weaker-measured rating. Above 1,500 this
          stopped sorting the error when the band was re-derived, so it no longer moves the
          band; below 1,500 the harness never scores a match, so the band assumes the worst</div></div>
      <div class="r"><div class="k">recent matches</div>
        <div class="v">${c.matches_28d ?? '—'}</div>
        <div class="s">${c.matches_28d === null ? 'name a tournament to establish this' : 'in 28 days, thinner side'}</div></div>
      <div class="r"><div class="k">matchup</div>
        <div class="v">${c.tightness}</div>
        <div class="s">kept out of the band on purpose — a coin flip is uncertain, not untrustworthy</div></div>
      ${c.comeback ? `<div class="r"><div class="k">layoff</div>
        <div class="v mark">${c.comeback === 2 ? 'both' : 'one player'}</div>
        <div class="s">60+ days out with no run here — the heaviest term in the band</div></div>` : ''}
      <div class="r"><div class="k">vs the market</div>
        <div class="v">${fmt.sg(c.deficit)}</div>
        <div class="s">this band's measured deficit against Pinnacle closing, on the
          odds-joined matches. It is the independent check on the band rather than what
          the band was fitted to, and it sorts the same way</div></div>
      ${(r.news || []).length ? `<div class="r"><div class="k">news on file</div>
        <div class="v mark">severity ${Math.max(...r.news.map(n => n.severity))}</div>
        <div class="s">reported beside the band, not inside it: the band was measured before this input existed</div></div>` : ''}
    </div>` : '';

  const curveRows = (r.curve_detail || []).map(d => {
    const bits = [];
    if (d.age !== null && d.age !== undefined) bits.push(`age ${d.age.toFixed(1)}`);
    bits.push(`${d.matches_28d} in 28d`, `${d.event_matches} at this event`);
    if (d.event_gwp !== null && d.event_gwp !== undefined)
      bits.push(`${fmt.p(d.event_gwp)} of games, ${d.event_sets_lost ?? 0} sets lost`);
    if (d.form_spw !== null && d.form_spw !== undefined)
      bits.push(`serve ${fmt.sg(d.form_spw)} vs their own year`);
    if (entryName(d.entry)) bits.push(`entered as ${esc(entryName(d.entry))}`);
    if (d.resid_prior !== null && d.resid_prior !== undefined)
      bits.push(`beats the point model by ${fmt.pts(d.resid_prior)} pts historically`);
    if (d.home === 1) bits.push(`<b style="color:var(--mark)">at home (${esc(d.ioc)})</b>`);
    else if (d.home === 0) bits.push(`away (${esc(d.ioc)})`);
    return `
    <tr><td>${esc(d.name)}</td>
        <td class="num">${fmt.sg(d.adj)}</td>
        <td class="note">${bits.join(' · ')}</td></tr>`;
  }).join('');

  const flags = [];
  if (r.stale) flags.push(`<div class="flag">The newest match in the data is ${r.stale.end} — ${r.stale.days} days of results are missing. Run <code>python3 update.py</code>.</div>`);
  if (!r.calibration) flags.push(`<div class="flag">Calibration is off by measurement${
    r.calibration_measured ? ` (slope ${r.calibration_measured.toFixed(3)} was measured; applying it made test loss worse)` : ''}.</div>`);
  if (r.curves_on && !r.curve_adj && r.tournament)
    flags.push(`<div class="flag">No run at ${esc(r.tournament)} in the last 21 days, so the curves have nothing to say about this match.</div>`);
  if (r.curves_on && !r.tournament)
    flags.push(`<div class="flag quiet">No tournament named, so the curves see no run and no home advantage — name one above for the full call.</div>`);

  // the one-line reading, and the market check if odds were typed
  const favA = r.p_a >= 0.5;
  const fav = favA ? r.a : r.b, pf = favA ? r.p_a : r.p_b;
  const margin = Math.abs(r.p_a - 0.5);
  const how = margin < 0.04 ? 'a coin flip' : margin < 0.12 ? 'a lean' : margin < 0.25 ? 'a clear favourite' : 'a heavy favourite';
  const summary = `${r.a.name} v ${r.b.name}${r.surface ? ', ' + r.surface : ''}, best of ${r.best_of}${r.tournament ? ', ' + r.tournament : ''}: `
    + `${r.a.name} ${fmt.p(r.p_a)} (fair ${fmt.odds(r.fair_a)}), ${r.b.name} ${fmt.p(r.p_b)} (fair ${fmt.odds(r.fair_b)})`
    + (c ? `; confidence ${c.band}` : '') + `; as of ${r.asof}`;
  const verdict = `
    <p class="verdict"><span><b>${esc(fav.name)}</b> ${fmt.p(pf)}, ${how} — fair odds ${fmt.odds(1 / pf)}${
      c ? `; confidence <span class="band ${c.band}">${c.band}</span>` : ''}.</span>
      <button class="ghost copy" data-copy="${esc(summary)}">copy the call</button><span class="copied"></span></p>`;

  const mk = r.market;
  const market = mk ? (() => {
    const big = Math.abs(mk.edge_a);
    const who = mk.edge_a > 0 ? r.a.name : r.b.name;
    const reading = big < 0.02
      ? 'under two points apart: the model and the market agree'
      : `the model likes <b>${esc(who)}</b> ${fmt.pts(big).slice(1)} points more than the market does`;
    return `
    <h3>against the odds you typed</h3>
    <div class="rows market">
      <div class="r"><div class="k">market says</div>
        <div class="v">${fmt.p(mk.implied_a)} / ${fmt.p(mk.implied_b)}</div>
        <div class="s">A / B, after removing the ${fmt.p(mk.overround)} margin from ${mk.odds_a.toFixed(2)} / ${mk.odds_b.toFixed(2)}</div></div>
      <div class="r"><div class="k">model says</div>
        <div class="v">${fmt.p(r.p_a)} / ${fmt.p(r.p_b)}</div>
        <div class="s">the call above</div></div>
      <div class="r"><div class="k">difference</div>
        <div class="v ${big < 0.02 ? 'agree' : big >= 0.05 ? 'mark' : ''}">${fmt.pts(mk.edge_a)} / ${fmt.pts(mk.edge_b)}</div>
        <div class="s">${reading}</div></div>
    </div>
    <div class="flag quiet">Measured against Pinnacle's closing line the model is about 0.02 nats <i>behind</i> the market, and all of that gap lives where the two disagree by more than 10 points. A large difference is a reason to look at the player pages, not a price to take.</div>`;
  })() : '';

  return `
    <div class="call">
      <div class="side a${r.p_a >= 0.5 ? ' fav' : ''}">
        <div class="nm">${esc(r.a.name)}</div>
        <div class="p">${fmt.p(r.p_a)}</div>
        <div class="fair">${fmt.odds(r.fair_a)}</div>
      </div>
      <div class="mid">FAIR<br>ODDS</div>
      <div class="side b${r.p_b > 0.5 ? ' fav' : ''}">
        <div class="nm">${esc(r.b.name)}</div>
        <div class="p">${fmt.p(r.p_b)}</div>
        <div class="fair">${fmt.odds(r.fair_b)}</div>
      </div>
    </div>
    <div class="bar"><i class="ba" style="width:${r.p_a * 100}%"></i><i class="bb" style="width:${r.p_b * 100}%"></i></div>
    ${verdict}
    <div class="bits">${bits()}</div>
    ${flags.join('')}
    ${market}
    <h3>what moved the number</h3>
    <table class="kv">${rows.join('')}</table>
    ${curveRows ? `<h3>form and run</h3><table class="kv">${curveRows}</table>` : ''}
    ${conf}
    <details class="raw"><summary>raw output — exactly what <code>tennis.py price</code> prints</summary><pre>${esc(r.text.trim())}</pre></details>`;
}

/* ------------------------------------------------------------- totals */

function totalsHTML(r) {
  const max = Math.max(...r.dist.map(d => d.p));
  const bars = r.dist.map(d => `
    <div class="col ${Math.abs(d.games - r.corrected_mean) < 1 ? 'mid' : ''}"
         style="height:${(d.p / max) * 100}%" title="${d.games} games — ${fmt.p(d.p)}"></div>`).join('');
  const axis = r.dist.map(d => `<span>${d.games % 5 === 0 ? d.games : ''}</span>`).join('');

  const ladder = r.ladder.map(l => `
    <tr><td>${l.line.toFixed(1)}</td>
        <td>${fmt.p(l.over)}</td>
        <td>${fmt.p(1 - l.over)}</td>
        <td>${fmt.odds(1 / Math.max(l.over, 1e-9))}</td>
        <td>${fmt.odds(1 / Math.max(1 - l.over, 1e-9))}</td>
        <td class="loss">${fmt.p(l.over_sim)}</td></tr>`).join('');

  const sets = r.scorelines.map(s => `
    <tr><td>${s.a}–${s.b}</td><td>${fmt.p(s.p)}</td><td class="loss">${esc(s.who)}</td></tr>`).join('');

  return `
    <div class="rows">
      <div class="r"><div class="k">expected games</div>
        <div class="v mark">${r.corrected_mean.toFixed(2)}</div>
        <div class="s">after the fitted bias correction of ${(-r.bias).toFixed(2)} games</div></div>
      <div class="r"><div class="k">raw simulation</div>
        <div class="v">${r.mean_games.toFixed(2)}</div>
        <div class="s">independent points finish matches later than real ones do — this is the number the correction fixes</div></div>
      <div class="r"><div class="k">mean sets</div>
        <div class="v">${r.mean_sets.toFixed(2)}</div>
        <div class="s">${fmt.n(r.mean_points)} points over ${fmt.n(r.n)} simulations</div></div>
      <div class="r"><div class="k">P(${esc(r.a)})</div>
        <div class="v">${fmt.p(r.p_a)}</div>
        <div class="s">simulated; the exact recursion says ${r.p_exact.toFixed(4)}</div></div>
    </div>

    <h3>total games, corrected</h3>
    <div class="hist">${bars}</div>
    <div class="axis">${axis}</div>

    <h3>lines</h3>
    <div class="tw"><table class="data">
      <tr><th>line</th><th>over</th><th>under</th><th>fair over</th><th>fair under</th><th>sim over, uncorrected</th></tr>
      ${ladder}
    </table></div>

    <h3>set scores</h3>
    <table class="data"><tr><th>sets</th><th>p</th><th>winner</th></tr>${sets}</table>

    ${r.curves_note ? `<div class="flag">The form/run curves are <b>not</b> in these numbers. They adjust P(win) directly and there is no principled way to push a match-level shift into per-point serve probabilities. Price and Totals differ by that amount.</div>` : ''}
    <div class="flag">There are no totals odds on file, so nothing here has been scored against a market. Discrimination was validated against realised scores; the level correction was fitted and validated out of sample.</div>

    <details class="raw"><summary>raw output — exactly what <code>tennis.py sim</code> prints</summary><pre>${esc(r.text.trim())}</pre></details>`;
}

/* ------------------------------------------------------------- player */

async function loadPlayer(id) {
  const el = $('#tab-player');
  el.innerHTML = '<div class="spinner">reading the card…</div>';
  let p;
  try { p = await api('/api/player', { id, at: $('#at').value.trim() }); }
  catch (e) { el.innerHTML = `<div class="flag bad">${esc(e.message)}</div>`; return; }

  const w = p.workload;
  const splits = p.surface_splits.map(s => `
    <tr><td>${esc(s.surface)}</td>
        <td>${fmt.n(s.n)}</td>
        <td>${s.serve.toFixed(4)}</td>
        <td>${fmt.sg(s.d_serve)}</td>
        <td>${fmt.p(s.w_serve)}</td>
        <td>${s.ret.toFixed(4)}</td>
        <td>${fmt.sg(s.d_ret)}</td>
        <td>${fmt.p(s.w_ret)}</td>
        <td>${fmt.p(s.p_vs_avg)}</td></tr>`).join('');

  const recent = p.recent ? p.recent.map(m => `
    <tr><td>${m.date.slice(0, 4)}-${m.date.slice(4, 6)}-${m.date.slice(6)}</td>
        <td>${esc(m.event)}</td><td>${esc(m.round)}</td>
        <td class="${m.won ? 'win' : 'loss'}">${m.won ? 'won' : 'lost'}</td>
        <td>${esc(m.opponent)}</td>
        <td>${esc(m.score)}${m.retired ? ' <b>ret</b>' : ''}${m.walkover ? ' <b>w/o</b>' : ''}</td>
        <td>${m.serve_pct === null ? '—' : fmt.p(m.serve_pct)}</td>
        <td>${m.days_rest ?? '—'}</td>
        <td>${m.matches_28d ?? '—'}</td></tr>`).join('')
    : `<tr><td colspan="9" class="loss">${p.recent_ready ? 'no matches' : 'deriving the workload table (about nine seconds after start-up) — reopen this tab'}</td></tr>`;

  const volatile = p.form_sd > S.meta.tour_form_sd;
  const inA = S.a?.id === p.id, inB = S.b?.id === p.id;
  el.innerHTML = `
    <div class="who-hd">
      <h2>${esc(p.name)}</h2>
      <span class="rk">#${p.rank} by model rating</span>
      <button data-pick="a">${inA ? 'is A' : 'set as A'}</button>
      <button data-pick="b">${inB ? 'is B' : 'set as B'}</button>
    </div>

    <div class="rows">
      <div class="r"><div class="k">against a tour average</div>
        <div class="v mark">${fmt.p(p.p_vs_avg)}</div>
        <div class="s">the model at a fixed reference, best of three — not a new quantity</div></div>
      <div class="r"><div class="k">serve / return</div>
        <div class="v">${p.serve.toFixed(4)}</div>
        <div class="s">return ${p.ret.toFixed(4)} · the tour serves ${S.meta.tour_avg.toFixed(4)}</div></div>
      <div class="r"><div class="k">form volatility</div>
        <div class="v">${p.form_sd.toFixed(4)}</div>
        <div class="s">${volatile ? 'more volatile' : 'steadier'} than the tour (${S.meta.tour_form_sd.toFixed(3)})${p.raw_sd ? `, own estimate ${p.raw_sd.toFixed(4)}` : ''}</div></div>
      <div class="r"><div class="k">data behind it</div>
        <div class="v">${fmt.n(p.pts)}</div>
        <div class="s">recency-weighted service points, over ${p.matches} matches</div></div>
    </div>

    <h3>right now</h3>
    <table class="kv">
      <tr><td>matches in the last 28 days</td><td class="num">${w.matches_28d}</td>
          <td class="note">the curves read this as rust, not fatigue — cold players underperform</td></tr>
      <tr><td>at ${p.tournament ? esc(p.tournament) : 'this event'}</td>
          <td class="num">${p.tournament ? w.event_matches : '—'}</td>
          <td class="note">${p.tournament
            ? `${w.event_gwp === null ? 'no games yet' : fmt.p(w.event_gwp) + ' of games won'}, ${w.event_sets_lost ?? 0} sets lost, ${w.event_minutes} min`
            : 'name a tournament above to see the run'}</td></tr>
      <tr><td>age</td>
          <td class="num">${w.age ? w.age.toFixed(1) : '—'}</td>
          <td class="note">the largest term in the correction layer — a decaying
            rating lags a rising player and over-states a falling one; the
            youngest beat their price, the oldest miss it</td></tr>
      <tr><td>recent serve level</td>
          <td class="num">${w.form_spw === null || w.form_spw === undefined ? '—' : fmt.sg(w.form_spw)}</td>
          <td class="note">${w.form_spw === null || w.form_spw === undefined
            ? 'needs 150 service points in 28 days and 800 in a year'
            : 'last 28 days against their own last 365 — margin, not match count'}</td></tr>
      <tr><td>beats the point model by</td>
          <td class="num">${w.resid_prior === null || w.resid_prior === undefined ? '—' : fmt.pts(w.resid_prior) + ' pts'}</td>
          <td class="note">${w.resid_prior === null || w.resid_prior === undefined
            ? 'needs 15 priced matches on record'
            : 'their own history against the model, shrunk — what the serve and return numbers miss about this player'}</td></tr>
      <tr><td>entered as</td>
          <td class="num">${entryName(w.entry) ? esc(entryName(w.entry)) : '—'}</td>
          <td class="note">${entryName(w.entry)
            ? 'from the archive’s rows at this event — the results feed carries the draw prefix since 2026-09-14'
            : 'unknown until they have played here, or until you say — qualifiers beat their price by about two points, lucky losers miss by two'}</td></tr>
      <tr><td>country</td>
          <td class="num">${w.ioc ?? '—'}</td>
          <td class="note">${w.home === 1
            ? `<b style="color:var(--mark)">playing at home</b> — home players beat their rating by about two points`
            : w.home === 0
              ? `away${w.home_km ? ` — ${fmt.n(w.home_km)} km from home` : ''}`
              : 'name a tournament above to see whether this is home'}</td></tr>
      <tr><td>days since their last event</td>
          <td class="num">${w.days_rest ?? '—'}</td>
          <td class="note">${w.comeback
            ? '<b style="color:var(--mark)">returning from a layoff</b> — 60+ days out with no run here'
            : w.event_matches ? 'already playing at this event' : 'measured from when that event started'}</td></tr>
      <tr><td>curve adjustment</td><td class="num">${fmt.sg(w.curve_adj)}</td>
          <td class="note">this player's own shift, before it is made antisymmetric against an opponent</td></tr>
    </table>

    <h3>surface splits</h3>
    ${splits ? `<div class="tw"><table class="data">
      <tr><th>surface</th><th>n_eff</th><th>serve</th><th>Δ</th><th>weight</th><th>return</th><th>Δ</th><th>weight</th><th>vs avg</th></tr>
      ${splits}</table></div>
      <div class="sub" style="color:var(--faint);font:11px var(--mono);margin-top:6px">
        Δ is the shift from the overall rating; weight is how much of it survives shrinkage — empirical Bayes, not a chosen constant.</div>`
      : '<div class="empty">no surface split — not enough on any one surface</div>'}

    <h3>recent matches</h3>
    <div class="tw"><table class="data">
      <tr><th>date</th><th>event</th><th>rd</th><th></th><th>opponent</th><th>score</th><th>serve won</th><th>rest</th><th>28d</th></tr>
      ${recent}
    </table></div>

    <h3>injury and player news</h3>
    <div class="newsbox" id="newsbox"><div class="msg">loading…</div></div>`;

  renderNews(p.id, p.name);

  $$('#tab-player [data-pick]').forEach(btn => btn.onclick = () => {
    const row = S.roster.find(r => r.id === p.id)
      || { id: p.id, name: p.name, p_vs_avg: p.p_vs_avg, serve: p.serve, ret: p.ret,
           pts: p.pts, form_sd: p.form_sd, matches: p.matches, rank: p.rank };
    if (!S.roster.some(r => r.id === row.id)) S.roster.push(row);
    S[btn.dataset.pick] = row;
    S.next = !S.a ? 'a' : !S.b ? 'b' : (btn.dataset.pick === 'a' ? 'b' : 'a');
    paintSlots(); refresh();
    if (S.a && S.b) showTab('price');
  });
}


/* ---------------------------------------------------------------- news */
/* The one input to the model that is not derived from the archive. It is
   validated on the way in and logged on the way out, and the panel says
   plainly that the weights are a prior rather than a measurement. */

async function renderNews(id, name) {
  const box = $('#newsbox');
  if (!box) return;
  let d;
  try { d = await api('/api/news', { id }); }
  catch (e) { box.innerHTML = `<div class="msg bad">${esc(e.message)}</div>`; return; }

  const r = d.report, eff = d.effect;
  const current = r ? `
    <div class="msg">on file: severity <b>${r.fitness.severity}</b>
      · ${esc(r.fitness.area || 'other')} · ${esc(r.fitness.sourcing || 'reported')}
      · as of ${esc(r.as_of)}${r.fitness.issue ? ' · ' + esc(r.fitness.issue) : ''}
      ${eff ? `<br>applies serve ${fmt.sg(eff.d_serve)}, return ${fmt.sg(eff.d_ret)}
        (decay ${eff.decay.toFixed(2)} after ${eff.age_days}d${eff.played_since ? `, ${eff.played_since} matches since` : ''})` : ''}
      ${r.available === false ? '<br><b>marked unavailable — the model will refuse to price them</b>' : ''}
    </div>` : '<div class="msg">nothing on file. An absence of news is itself a reading.</div>';

  box.innerHTML = `
    <h4>step 1 · give this prompt to an assistant with a browser</h4>
    <pre id="news-prompt">${esc(d.prompt)}</pre>
    <div class="act">
      <button class="ghost" id="news-copy">copy prompt</button>
      <span class="msg" id="news-copied"></span>
    </div>
    <h4 style="margin-top:16px">step 2 · paste what it returns</h4>
    <textarea id="news-json" placeholder='{"player": "${esc(name)}", "as_of": "…", "available": true, "fitness": {…}, "sources": […]}'></textarea>
    <div class="act">
      <button id="news-save">store report</button>
      ${r ? '<button class="ghost" id="news-clear">clear</button>' : ''}
      <span class="msg" id="news-msg"></span>
    </div>
    ${current}
    <div class="flag quiet" style="margin-top:12px">These weights are a <b>prior, not a fit</b>.
      Every other number in the model was measured on walk-forward residuals; this one cannot
      be, because no archive exists of what the news said on the morning of each past match.
      Severity 1 / 2 / 3 move a reference match 2, 6 and 13 points. Every application is
      logged so it can be measured later.</div>`;

  $('#news-copy').onclick = async () => {
    try { await navigator.clipboard.writeText(d.prompt); $('#news-copied').textContent = 'copied'; }
    catch { $('#news-copied').textContent = 'select the text above and copy'; }
    setTimeout(() => { const el = $('#news-copied'); if (el) el.textContent = ''; }, 2500);
  };
  $('#news-save').onclick = async () => {
    const msg = $('#news-msg');
    msg.className = 'msg'; msg.textContent = 'storing…';
    try {
      const res = await fetch('/api/news', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, report: $('#news-json').value }),
      });
      const j = await res.json();
      if (j.error) throw new Error(j.error);
      msg.textContent = 'stored';
      renderNews(id, name); refresh();
    } catch (e) { msg.className = 'msg bad'; msg.textContent = e.message; }
  };
  const cl = $('#news-clear');
  if (cl) cl.onclick = async () => {
    await fetch('/api/news', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, clear: true }) });
    renderNews(id, name); refresh();
  };
}

/* --------------------------------------------------------------- model */

async function loadAbout() {
  const v = await api('/api/variables');
  const m = S.meta, h = m.headline || {};
  const rows = v.rows.map(r => `
    <tr><td>${esc(r.name)}</td>
        <td class="num">${r.status === 'LIVE' ? '<b style="color:var(--mark)">LIVE</b>' : '<span class="note">recorded</span>'}</td>
        <td class="note">${esc(r.note)}</td></tr>`).join('');

  const f5 = x => (x === null || x === undefined) ? '—' : Number(x).toFixed(5);
  const market = Object.entries(h.market || {}).sort((a, b) => b[0].localeCompare(a[0])).map(([yr, k]) => `
      <tr><td>${esc(yr)}: model, walk-forward</td><td class="num">${f5(k.model)}</td>
          <td class="note">log loss on ${fmt.n(k.n)} matches joined to Pinnacle closing odds, before the residual curves</td></tr>
      <tr><td>${esc(yr)}: Pinnacle closing, devigged</td><td class="num">${f5(k.closing)}</td>
          <td class="note">the model is ${Math.abs(k.gap).toFixed(3)} nats ${k.gap > 0 ? 'behind' : 'ahead'}${
            k.buckets && k.buckets['10%+'] ? `; where they differ by 10+ points (n ${fmt.n(k.buckets['10%+'].n)}) the gap is ${(k.buckets['10%+'].model - k.buckets['10%+'].closing).toFixed(3)}` : ''}</td></tr>`).join('');

  $('#tab-about').innerHTML = `
    <h3>fitted state</h3>
    <table class="kv">
      <tr><td>as of</td><td class="num">${m.asof}</td><td class="note">ratings decay to this day; nothing after it is used</td></tr>
      <tr><td>newest match in the data</td><td class="num">${m.data_end ?? '—'}</td>
          <td class="note">${m.stale_days > 21 ? `<b style="color:var(--mark)">${m.stale_days} days behind</b> — run update.py` : 'current'}</td></tr>
      <tr><td>tour average serve</td><td class="num">${m.tour_avg.toFixed(5)}</td><td class="note"></td></tr>
      <tr><td>tour-wide form_sd</td><td class="num">${m.tour_form_sd.toFixed(4)}</td><td class="note">per-player values shrink toward this</td></tr>
      <tr><td>form_scale</td><td class="num">${m.form_scale ?? '—'}</td><td class="note">fitted by backtest.py</td></tr>
      <tr><td>refit cadence</td><td class="num">${h.refit_days ? h.refit_days + ' days' : '—'}</td><td class="note">how often the harness refits the ratings — a model parameter, measured</td></tr>
      <tr><td>surface carry cap</td><td class="num">${h.carry_cap ?? '—'}</td><td class="note">recent form carried onto the surface rating, at most this much</td></tr>
      <tr><td>density weight</td><td class="num">${m.dens_w ?? '—'}</td><td class="note">real, and nearly worthless for a moneyline — it is symmetric</td></tr>
      <tr><td>calibration</td><td class="num">${!m.calibration || Math.abs(m.calibration - 1) < 1e-9 ? 'OFF' : m.calibration.toFixed(3)}</td>
          <td class="note">${m.calibration_measured ? `slope ${m.calibration_measured.toFixed(3)} measured` : ''}</td></tr>
      <tr><td>residual curves</td><td class="num">${m.curves.length}</td><td class="note">${esc(m.curves.join(', ')) || 'none fitted'}</td></tr>
    </table>

    <h3>measured</h3>
    <table class="kv">
      <tr><td>model, held-out test</td><td class="num">${f5(h.test_log_loss)}</td>
          <td class="note">log loss on ${h.test_matches ? fmt.n(h.test_matches) + ' test matches' : 'the test half'}, the shipped path end to end (${h.fitted_on ? esc(h.fitted_on) : 'walk-forward'})</td></tr>
      <tr><td>tuned Elo, same matches</td><td class="num">${f5(h.elo_log_loss)}</td>
          <td class="note">${h.elo_log_loss && h.test_log_loss ? `the model beats it by ${(h.elo_log_loss - h.test_log_loss).toFixed(4)} nats` : 'match results only'}</td></tr>
      ${market || `<tr><td>against the market</td><td class="num">—</td><td class="note">run <code>python3 tools/odds/m4.py 2025</code> to score against Pinnacle closing</td></tr>`}
    </table>
    <div class="flag">The gap to the market is <b>ordering, not calibration</b>: where the model agrees with the market it <i>is</i> the market, and the loss lives in confident disagreement. Read a big disagreement as a question, not an edge.</div>

    <h3>every input the model accepts</h3>
    <table class="kv">${rows}</table>`;
}

/* -------------------------------------------------------------- wiring */

function showTab(name) {
  $$('#tabs button').forEach(x => x.classList.toggle('on', x.dataset.tab === name));
  $$('.panel').forEach(p => p.classList.toggle('on', p.id === 'tab-' + name));
  if (name === 'about') loadAbout();
}

let seq = 0;
async function refresh() {
  pushState();
  const both = S.a && S.b;
  const tabs = { price: $('#tab-price'), totals: $('#tab-totals') };
  if (!both) {
    tabs.price.innerHTML = guideHTML();
    $('#example').onclick = example;
    tabs.totals.innerHTML = '<div class="empty">Two players, from the index on the left.</div>';
    return;
  }
  const mine = ++seq;
  for (const el of Object.values(tabs)) el.innerHTML = '<div class="spinner">working it out…</div>';

  try {
    const r = await api('/api/price', conditions());
    if (mine !== seq) return;
    tabs.price.innerHTML = priceHTML(r);
    const cp = $('.verdict .copy', tabs.price);
    if (cp) cp.onclick = async () => {
      const out = $('.verdict .copied', tabs.price);
      try { await navigator.clipboard.writeText(cp.dataset.copy); out.textContent = 'copied'; }
      catch { out.textContent = cp.dataset.copy; }
      setTimeout(() => { if (out) out.textContent = ''; }, 2500);
    };
  } catch (e) {
    if (mine === seq) tabs.price.innerHTML = `<div class="flag bad">${esc(e.message)}</div>`;
  }

  // the simulation costs about half a second, so it runs after the price is on screen
  try {
    const s = await api('/api/sim', conditions());
    if (mine !== seq) return;
    tabs.totals.innerHTML = totalsHTML(s);
  } catch (e) {
    if (mine === seq) tabs.totals.innerHTML = `<div class="flag bad">${esc(e.message)}</div>`;
  }
}

function wire() {
  $('#roster-list').addEventListener('click', e => {
    const li = e.target.closest('li[data-id]');
    if (li) { choose(li.dataset.id); if (S.a && S.b) showTab('price'); }
  });
  const q = $('#q');
  q.addEventListener('input', rosterSoon);
  q.addEventListener('keydown', async e => {
    if (e.key === 'ArrowDown') { e.preventDefault(); moveHi(1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); moveHi(-1); }
    else if (e.key === 'Escape') { q.value = ''; loadRoster(); }
    else if (e.key === 'Enter' || e.key === 'Return' || e.keyCode === 13) {
      e.preventDefault();
      if (rosterTimer) await loadRoster();          // a keystroke still pending
      const lis = $$('#roster-list li[data-id]');
      const li = lis[S.hi] || lis[0];
      if (!li) return;
      const id = li.dataset.id;
      if (S.a?.id === id || S.b?.id === id) return;   // already in — nothing to do
      choose(id);
      q.value = '';
      await loadRoster();
      if (S.a && S.b) showTab('price');
    }
  });
  ['#surface-filter', '#min-pts', '#sort'].forEach(s => $(s).addEventListener('change', loadRoster));
  ['#surface', '#best-of', '#curves', '#entry-a', '#entry-b'].forEach(s => $(s).addEventListener('change', refresh));
  ['#odds-a', '#odds-b'].forEach(s => {
    let t = null;
    $(s).addEventListener('input', () => { clearTimeout(t); t = setTimeout(refresh, 350); });
  });
  $('#at').addEventListener('change', () => { applyVenue(); refresh(); if (S.focus) loadPlayer(S.focus.id); });
  $('#at').addEventListener('input', () => { if (!$('#at').value.trim()) $('#venue-note').textContent = ''; });

  $('#swap').onclick = () => {
    [S.a, S.b] = [S.b, S.a];
    // the entry codes and the odds belong to the players, so they swap sides too
    for (const [x, y] of [['#entry-a', '#entry-b'], ['#odds-a', '#odds-b']]) {
      const ex = $(x), ey = $(y);
      [ex.value, ey.value] = [ey.value, ex.value];
    }
    paintSlots(); refresh();
  };
  $('#clear').onclick = () => {
    S.a = S.b = null; S.next = 'a';
    $('#entry-a').value = $('#entry-b').value = '';
    $('#odds-a').value = $('#odds-b').value = '';
    paintSlots(); refresh(); $('#q').focus();
  };
  $$('.slot').forEach(el => el.onclick = () => {
    const k = el.dataset.slot;
    if (S[k]) { S[k] = null; S.next = k; $(k === 'a' ? '#entry-a' : '#entry-b').value = ''; paintSlots(); refresh(); }
    else { S.next = k; paintSlots(); loadRoster(); }
    $('#q').focus();
  });
  $('#untuck').onclick = () => { $('#roster').classList.remove('tucked'); $('#untuck').hidden = true; $('#q').focus(); };
  window.addEventListener('resize', paintSlots);
  // a link pasted into an open tab changes only the hash: pick the match up from it
  window.addEventListener('hashchange', () => { if (location.hash.length > 1) restore(); });

  $$('#tabs button').forEach(b => b.onclick = () => showTab(b.dataset.tab));
}

(async function start() {
  wire();
  try {
    await loadMeta();
  } catch (e) {
    const msg = `<div class="flag">Cannot reach the model server (${esc(e.message)}). Start it with <code>python3 tennis.py app</code> and reload.</div>`;
    $('#meta').innerHTML = '<span class="warn">server not reachable</span>';
    $('#tab-price').innerHTML = msg;
    return;
  }
  await loadRoster();
  const restored = await restore();
  if (!restored) refresh();
  $('#q').focus();
})();
