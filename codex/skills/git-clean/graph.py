"""Render a bounded, self-contained SVG of Git's actual commit DAG."""
from collections import defaultdict
from html import escape

COLORS = ('#4783d7', '#a064c7', '#259b84', '#d18c32', '#d46979', '#5c9bb6')


def layout(commits):
    """Allocate lanes to pending parents; preserve topological order from Git."""
    pending, positions, occupied = {}, {}, {}
    for index, commit in enumerate(commits):
        oid = commit['oid']
        lane = pending.pop(oid, None)
        if lane is None:
            lane = next(i for i in range(len(occupied) + 1) if i not in occupied)
        occupied.pop(lane, None)
        positions[oid] = (lane, index)
        for parent_index, parent in enumerate(commit['parents'].split()):
            if parent in pending or parent in positions:
                continue
            parent_lane = lane if parent_index == 0 and lane not in occupied else next(
                i for i in range(len(occupied) + 1) if i not in occupied)
            pending[parent] = parent_lane
            occupied[parent_lane] = parent
    return positions


def render_graph(audit):
    commits = audit.get('graph', [])
    if not commits:
        return '<h2>Graf historii</h2><p class="mut">Brak danych grafu — uruchom nowy audyt.</p>'
    positions = layout(commits)
    refs = defaultdict(list)
    for ref in audit.get('graph_refs', []):
        refs[ref['oid']].append(ref['ref'])
    states = {f"refs/heads/{b['name']}": b['cats'] for b in audit['local']}
    max_lane = max(x[0] for x in positions.values())
    text_x = 70 + 26 * max_lane
    width, height = max(1120, text_x + 900), len(commits) * 52 + 38
    parts = ['<h2>Graf historii i gałęzi</h2>',
             '<p class="sub">Commity od najnowszych; linie prowadzą do rodziców. '
             'Wybierz gałąź, aby wyróżnić jej historię. Squash i rebase nie tworzą połączenia z dawną gałęzią.</p>',
             '<div class="graph-controls"><label>Historia gałęzi <select id="graph-focus">'
             '<option value="">Wszystkie</option>']
    for ref in sorted(audit.get('graph_refs', []), key=lambda r: r['ref']):
        if ref['oid'] in positions:
            parts.append(f'<option value="{escape(ref["oid"], quote=True)}">{escape(ref["ref"])}</option>')
    parts.extend(['</select></label><label>Powiększenie <input id="graph-zoom" type="range" '
                  'min="70" max="160" value="100" aria-label="Powiększenie grafu"></label></div>',
                  '<p class="graph-legend"><span class="bd ok">do usunięcia</span> '
                  '<span class="bd bad">praca tylko lokalnie</span> '
                  '<span class="bd acc">HEAD / chroniona</span> · '
                  'linia przerywana: rodzic poza pokazanym zakresem</p>',
                  f'<div class="graph-scroll"><svg id="commit-graph" width="{width}" height="{height}" '
                  f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="graph-title">'
                  '<title id="graph-title">Graf commitów, gałęzi lokalnych, remote i tagów</title>'])
    for commit in commits:
        oid = commit['oid']
        lane, index = positions[oid]
        x, y = 24 + lane * 26, 28 + index * 52
        color = COLORS[lane % len(COLORS)]
        for parent in commit['parents'].split():
            known = parent in positions
            parent_lane, parent_row = positions.get(parent, (lane, len(commits)))
            px, py = 24 + parent_lane * 26, 28 + parent_row * 52
            dash = '' if known else ' stroke-dasharray="4 5"'
            parts.append(f'<path class="graph-edge" data-child="{oid}" data-parent="{escape(parent)}" '
                         f'd="M{x},{y} C{x},{y+24} {px},{py-24} {px},{py}" '
                         f'stroke="{color}" fill="none" stroke-width="2"{dash}/>')
    for commit in commits:
        oid = commit['oid']
        lane, index = positions[oid]
        x, y = 24 + lane * 26, 28 + index * 52
        names = refs[oid]
        cats = {cat for name in names for cat in states.get(name, [])}
        kind = 'local-only' if 'local_only' in cats else 'safe' if 'safe' in cats else 'protected' if (
            'HEAD' in names or cats.intersection({'default', 'protected', 'current'})) else 'normal'
        labels = [name.replace('refs/heads/', '', 1).replace('refs/remotes/', 'remote: ').replace('refs/tags/', 'tag: ')
                  for name in names]
        title = f"{oid}\n{commit['subject']}\n{commit['author']}\n" + '\n'.join(names)
        parts.append(f'<g class="graph-node {kind}" data-oid="{oid}" '
                     f'data-parents="{escape(commit["parents"], quote=True)}">'
                     f'<title>{escape(title)}</title><circle cx="{x}" cy="{y}" r="6" '
                     f'fill="{COLORS[lane % len(COLORS)]}"/>'
                     f'<text x="{text_x}" y="{y-5}" class="graph-subject">'
                     f'{escape(oid[:8])} · {escape(commit["subject"][:100])}</text>'
                     f'<text x="{text_x}" y="{y+14}" class="graph-label">'
                     f'{escape(" · ".join(labels)[:180])}</text></g>')
    parts.append('</svg></div>')
    if audit.get('graph_truncated'):
        parts.append(f'<p class="mut">Pokazano {len(commits)} commitów. Starsza historia została skrócona; '
                     'zwiększ <code>--graph-limit N</code> (maksymalnie 1000).</p>')
    parts.append('<details><summary>Lista commitów (wersja tekstowa)</summary><table><thead><tr>'
                 '<th>SHA</th><th>Rodzice</th><th>Gałęzie / tagi</th><th>Opis</th></tr></thead><tbody>')
    for commit in commits:
        parts.append('<tr>' + ''.join(f'<td>{escape(value)}</td>' for value in (
            commit['oid'][:12], ', '.join(p[:12] for p in commit['parents'].split()),
            ', '.join(refs[commit['oid']]), commit['subject'])) + '</tr>')
    parts.append('</tbody></table></details>')
    return ''.join(parts)


CSS = '''
.graph-controls{display:flex;flex-wrap:wrap;gap:18px;align-items:center;margin:12px 0}
.graph-controls label{display:flex;gap:8px;align-items:center}
.graph-controls select{max-width:360px;color:var(--text);background:var(--surface);border:1px solid var(--border);padding:6px;border-radius:6px}
.graph-scroll{overflow:auto;max-height:570px;border:1px solid var(--border);background:var(--surface);border-radius:10px}
.graph-subject{font:13px system-ui;fill:var(--text)}.graph-label{font:12px ui-monospace,monospace;fill:var(--muted)}
.graph-node.safe .graph-label{fill:var(--ok)}.graph-node.local-only .graph-label{fill:var(--bad)}
.graph-node.protected .graph-label{fill:var(--acc)}.graph-node.dim,.graph-edge.dim{opacity:.15}
.graph-node.selected circle{stroke:var(--text);stroke-width:3}.graph-node,.graph-edge{transition:opacity .15s}
'''

JS = '''
const graph=document.getElementById('commit-graph');
if(graph){
 const nodes=[...graph.querySelectorAll('.graph-node')],byId=new Map(nodes.map(n=>[n.dataset.oid,n]));
 document.getElementById('graph-focus').addEventListener('change',ev=>{
  const tip=ev.target.value,reachable=new Set(),pending=tip?[tip]:[];
  while(pending.length){const oid=pending.pop();if(reachable.has(oid))continue;reachable.add(oid);
   const n=byId.get(oid);if(n)pending.push(...n.dataset.parents.split(' ').filter(Boolean));}
  nodes.forEach(n=>{n.classList.toggle('dim',!!tip&&!reachable.has(n.dataset.oid));n.classList.toggle('selected',n.dataset.oid===tip);});
  graph.querySelectorAll('.graph-edge').forEach(p=>p.classList.toggle('dim',!!tip&&!reachable.has(p.dataset.child)));
 });
 document.getElementById('graph-zoom').addEventListener('input',ev=>{
  const scale=Number(ev.target.value)/100,v=graph.viewBox.baseVal;
  graph.setAttribute('width',v.width*scale);graph.setAttribute('height',v.height*scale);
 });
}
'''
