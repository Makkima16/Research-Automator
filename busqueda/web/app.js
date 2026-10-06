// Página del Buscador: habla con servidor.py (API en /api/proyectos).

const S = {
  projects: [],      // resúmenes (sin papers) para la barra lateral
  proj: null,        // proyecto activo, completo
  filterText: '',
  onlyOA: false,
  onlyPicked: false, // ver solo los papers de la selección
  selId: null,       // paper abierto en el panel
  panelOpen: false,
  busy: false,       // generando cadenas
  renaming: false,   // editando el título en la barra superior
  error: null,
};
// Borrador del formulario cuando todavía no existe ningún proyecto
const DRAFT = { prompt: '', num: 5, idioma: 'es' };
let pollTimer = null;

const $ = (sel) => document.querySelector(sel);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const doiCorto = (doi) => String(doi || '').replace(/^https?:\/\/(dx\.)?doi\.org\//i, '');
const form = () => S.proj || DRAFT;

const MOTORES = { openalex: 'OpenAlex', semantic_scholar: 'Semantic Scholar', scopus: 'Scopus', scihub: 'Sci-Hub' };
const motor = (m) => MOTORES[m] || m;
// motor_busqueda trae uno o varios motores separados por "; "
// Página web de donde sale el texto del paper (los motores solo lo indexan):
// el dominio del enlace, p. ej. "mdpi.com". '' si el paper no trae enlace
function paginaOrigen(r) {
  try {
    return new URL(r.pdf_url || r.oa_url).hostname.replace(/^www\./, '');
  } catch (e) {
    return '';
  }
}
const motores = (r) => String(r.motor_busqueda || '').split('; ').filter(Boolean);

async function api(method, path, body) {
  const resp = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.error || `Error ${resp.status}`);
  return data;
}

// Envuelve una acción: muestra el error en la página en vez de perderlo
async function run(fn) {
  S.error = null;
  try {
    await fn();
  } catch (e) {
    S.error = e instanceof TypeError ? 'No hay conexión con el servidor (¿sigue corriendo python servidor.py?).' : e.message;
    render();
  }
}

// ---------- render ----------

function render() {
  renderSide();
  renderTop();
  renderContent();
  renderPanel();
}

function renderSide() {
  $('#side-list').innerHTML = S.projects.length
    ? S.projects.map((p) => `
        <div class="proj-item ${S.proj && p.id === S.proj.id ? 'active' : ''}">
          <button class="proj-name" data-action="select-project" data-id="${esc(p.id)}" title="${esc(p.name)}"><span>${esc(p.name)}</span></button>
          <button class="proj-rm" data-action="delete-project" data-id="${esc(p.id)}" title="Eliminar proyecto" aria-label="Eliminar el proyecto ${esc(p.name)}">✕</button>
        </div>`).join('')
    : '<div class="empty-list">Sin proyectos todavía</div>';
}

function renderTop() {
  const p = S.proj;
  $('#topbar').innerHTML = `
    <span class="crumb">Proyecto</span>
    ${!p ? '<h1></h1>' : S.renaming
      ? `<input class="title-input" id="title-input" data-input="title" value="${esc(p.name)}" maxlength="80" aria-label="Título del proyecto">`
      : `<h1><button class="title-btn" data-action="rename" title="Cambiar el título">${esc(p.name)}<span class="pencil" aria-hidden="true">✎</span></button></h1>`}
    <div class="spacer"></div>
    ${p && p.stage !== 'empty' && p.stage !== 'loading' ? '<button class="btn btn-ghost" data-action="reset">Reiniciar</button>' : ''}`;
}

function notice() {
  const text = S.error || (S.proj && S.proj.aviso);
  return text ? `<div class="notice" role="status">${esc(text)}</div>` : '';
}

function renderContent() {
  const stage = S.proj ? S.proj.stage : 'empty';
  const view = { empty: viewPrompt, queries: viewQueries, loading: viewLoading, results: viewResults }[stage];
  $('#content').innerHTML = view();
  if (stage === 'results') renderRows();
}

function viewPrompt() {
  const f = form();
  const lang = (value, label) => `<label class="seg-opt"><input type="radio" name="lang" value="${value}" ${f.idioma === value ? 'checked' : ''}><span>${label}</span></label>`;
  return `
    <div class="prompt-wrap">
      <div class="kicker">Nuevo proyecto</div>
      <h2>¿Qué quieres investigar?</h2>
      <p class="lead">Describe el tema en lenguaje natural. Generaremos varias cadenas de búsqueda que podrás revisar antes de lanzar la consulta.</p>

      <div class="field">
        <label for="prompt">Prompt</label>
        <textarea class="input" id="prompt" rows="4" data-input="prompt" placeholder="ej. Efectos del microbioma intestinal en trastornos del espectro autista en población pediátrica, estudios de los últimos 5 años">${esc(f.prompt)}</textarea>
      </div>

      <div class="row-inline">
        <div class="field num-field">
          <label for="num">Cadenas a generar</label>
          <input class="input" id="num" type="number" min="1" max="12" value="${esc(f.num)}" data-input="num">
        </div>
        <div class="field">
          <label>Idioma del tema</label>
          <div class="seg">${lang('es', 'Español')}${lang('en', 'Inglés')}${lang('ambos', 'Ambos')}</div>
        </div>
        <button class="btn btn-primary" data-action="generate" ${S.busy ? 'disabled' : ''}>${S.busy ? 'Generando…' : 'Generar cadenas →'}</button>
      </div>
      ${notice()}
    </div>`;
}

function viewQueries() {
  const qs = S.proj.queries;
  return `
    <div>
      <div class="kicker">Paso 2 de 3</div>
      <h2 style="margin:0 0 8px">Cadenas de búsqueda</h2>
      <p class="lead" style="margin:0 0 8px; max-width:620px">Edita, elimina o añade cadenas antes de ejecutar el servicio. Cada cadena se consultará contra OpenAlex, Semantic Scholar y Scopus; los papers mejor rankeados sin PDF abierto se buscan además en Sci-Hub por su DOI.</p>
      ${notice()}

      <div class="queries-head">
        <div class="meta">${qs.length} cadenas · generadas a partir del prompt</div>
      </div>

      <div class="query-list">
        ${qs.map((text, i) => `
          <div class="query-row">
            <span class="idx">${String(i + 1).padStart(2, '0')}</span>
            <input value="${esc(text)}" data-input="query" data-idx="${i}" aria-label="Cadena ${i + 1}" spellcheck="false">
            <button class="rm" data-action="remove-query" data-idx="${i}" title="Eliminar" aria-label="Eliminar cadena ${i + 1}">✕</button>
          </div>`).join('')}
        <button class="add-row" data-action="add-query">+ añadir cadena</button>
      </div>

      <div class="row-inline params">
        <div class="field num-field">
          <label for="min-year">Año mínimo</label>
          <input class="input" id="min-year" type="number" min="1900" max="2100" placeholder="sin límite" value="${esc(S.proj.min_year)}" data-input="min_year">
        </div>
        <div class="field num-field">
          <label for="max-res">Resultados por cadena</label>
          <input class="input" id="max-res" type="number" min="1" max="500" value="${esc(S.proj.max_resultados)}" data-input="max_resultados">
        </div>
        <p class="hint">El tope de resultados aplica a cada cadena en cada plataforma; con más resultados la búsqueda tarda más.</p>
      </div>

      <div class="actions-bar">
        <button class="btn btn-ghost" data-action="back-to-prompt">← Volver al prompt</button>
        <div style="display:flex; gap:16px; align-items:center">
          ${S.proj.papers.length ? `<button class="btn btn-ghost" data-action="back-to-results">Ver resultados anteriores (${S.proj.papers.length})</button>` : ''}
          <button class="btn btn-primary" data-action="run-search">Iniciar búsqueda →</button>
        </div>
      </div>
    </div>`;
}

function viewLoading() {
  return `
    <div class="loading-wrap">
      <div class="kicker">Ejecutando</div>
      <h2 style="margin:0 0 8px">Buscando papers</h2>
      <p class="lead">Consultando ${S.proj.queries.length} cadenas en varias fuentes. Esto puede tardar unos minutos.</p>

      <div class="load-steps">
        ${S.proj.progreso.map((s) => `<div class="load-step ${s.estado === 'pending' ? '' : esc(s.estado)}"><span class="ic"></span>${esc(s.texto)}</div>`).join('')}
      </div>
      <div class="load-bar"><div></div></div>
      <div style="margin-top:24px"><button class="btn btn-secondary" data-action="cancel-search">Cancelar búsqueda</button></div>
    </div>`;
}

function viewResults() {
  return `
    <div>
      <div class="results-head">
        <div>
          <div class="kicker">Resultados</div>
          <h2 style="margin:0">Papers encontrados</h2>
        </div>
        <div style="display:flex; gap:8px">
          <a class="btn btn-secondary" id="export" href="#" download>Exportar CSV</a>
          <button class="btn btn-ghost" data-action="back-to-queries">Editar cadenas</button>
        </div>
      </div>
      ${notice()}

      <div class="stat-row">
        <div class="stat"><span class="n" id="stat-total"></span><span class="l">Papers únicos</span></div>
        <div class="stat"><span class="n" id="stat-oa"></span><span class="l">Open access</span></div>
        <div class="stat"><span class="n">${esc(S.proj.cadenas_usadas)}</span><span class="l">Cadenas usadas</span></div>
        <div class="stat"><span class="n">${esc(S.proj.fuentes)}</span><span class="l">Fuentes</span></div>
      </div>

      <div class="filter-bar">
        <input class="input" placeholder="Filtrar por título, fuente, DOI…" value="${esc(S.filterText)}" data-input="filter" aria-label="Filtrar resultados">
        <div class="seg">
          <label class="seg-opt"><input type="radio" name="oaf" value="all" ${S.onlyOA ? '' : 'checked'}><span>Todos</span></label>
          <label class="seg-opt"><input type="radio" name="oaf" value="oa" ${S.onlyOA ? 'checked' : ''}><span>Solo OA</span></label>
        </div>
        <div class="seg">
          <label class="seg-opt"><input type="checkbox" name="pickf" ${S.onlyPicked ? 'checked' : ''}><span>★ Selección (<span id="pick-count"></span>)</span></label>
        </div>
      </div>

      <div class="results-table-wrap">
        <table class="r-table">
          <colgroup>
            <col style="width:28%"><col style="width:60px"><col style="width:72px"><col style="width:68px">
            <col style="width:16%"><col style="width:150px"><col style="width:150px"><col style="width:12%"><col style="width:auto">
          </colgroup>
          <thead>
            <tr><th>Título / fuente</th><th>Año</th><th>Citas</th><th>OA</th><th>DOI</th><th title="Motor de búsqueda que encontró el paper">Encontrado en</th><th title="Página web donde está el texto del paper (dominio del enlace que dio el motor)">Página de origen</th><th>Cadena</th><th>Abstract</th></tr>
          </thead>
          <tbody id="rows"></tbody>
        </table>
      </div>
    </div>`;
}

function filteredPapers() {
  const q = S.filterText.trim().toLowerCase();
  const picked = new Set(S.proj.seleccion);
  return S.proj.papers.filter((r) => {
    if (S.onlyOA && !r.is_oa) return false;
    if (S.onlyPicked && !picked.has(r.id)) return false;
    if (!q) return true;
    return [r.title, r.doi, r.source].some((v) => String(v || '').toLowerCase().includes(q));
  });
}

// Solo el cuerpo de la tabla y los contadores: así el campo de filtro no pierde el foco
function renderRows() {
  const rows = filteredPapers();
  const picked = new Set(S.proj.seleccion);
  $('#stat-total').textContent = rows.length;
  $('#stat-oa').textContent = rows.filter((r) => r.is_oa).length;
  $('#pick-count').textContent = S.proj.seleccion.length;
  // Con "Selección" activa, el CSV trae solo los papers seleccionados
  const exportar = $('#export');
  exportar.href = `/api/proyectos/${S.proj.id}/papers.csv${S.onlyPicked ? '?seleccion=1' : ''}`;
  exportar.textContent = S.onlyPicked ? 'Exportar selección' : 'Exportar CSV';
  $('#rows').innerHTML = rows.length ? rows.map((r) => `
    <tr class="${r.id === S.selId && S.panelOpen ? 'sel' : ''} ${picked.has(r.id) ? 'picked' : ''}" data-action="open-paper" data-id="${esc(r.id)}">
      <td class="c-title">
        <div class="r-title">${esc(r.title || '(sin título)')}</div>
        <div class="r-src">${esc(r.source)}</div>
      </td>
      <td class="r-mono">${esc(r.year)}</td>
      <td class="r-mono cite">${esc(r.cited_by_count)}</td>
      <td>${r.is_oa ? '<span class="oa-chip oa-yes">OA</span>' : '<span class="oa-chip oa-no">—</span>'}</td>
      <td class="r-doi">${esc(doiCorto(r.doi))}</td>
      <td><div class="chips">${motores(r).map((m) => `<span class="match-chip">${esc(motor(m))}</span>`).join('')}</div></td>
      <td>${paginaOrigen(r) ? `<span class="match-chip" title="${esc(r.pdf_url || r.oa_url)}">${esc(paginaOrigen(r))}</span>` : '<span class="oa-chip oa-no">—</span>'}</td>
      <td><span class="match-chip" title="${esc(r.matched_query)}">${esc(r.matched_query)}</span></td>
      <td><div class="trunc">${esc(r.abstract)}</div></td>
    </tr>`).join('')
    : `<tr><td class="none" colspan="9">${S.onlyPicked && !S.proj.seleccion.length
      ? 'Todavía no hay papers en la selección. Abre un paper y pulsa «Añadir a selección».'
      : 'Ningún paper coincide con el filtro.'}</td></tr>`;
}

function selectedPaper() {
  return S.proj && S.selId ? S.proj.papers.find((r) => r.id === S.selId) : null;
}

function paperUrl(r) {
  return r.doi || r.oa_url || r.openalex_id || '';
}

function renderPanel() {
  const panel = $('#panel');
  const r = selectedPaper();
  panel.classList.toggle('open', Boolean(S.panelOpen && r));
  if (!r) { panel.innerHTML = ''; return; }
  const picked = S.proj.seleccion.includes(r.id);
  const url = paperUrl(r);
  panel.innerHTML = `
    <div class="sp-head">
      <div class="kicker">Detalle del paper</div>
      <button class="sp-close" data-action="close-panel" aria-label="Cerrar">✕</button>
    </div>
    <div class="sp-body">
      <h3 class="sp-title">${esc(r.title || '(sin título)')}</h3>
      <div class="sp-meta">
        <span><strong>${esc(r.year)}</strong>${r.source ? ' · ' + esc(r.source) : ''}</span>
        <span>${esc(r.cited_by_count)} citas</span>
        ${r.is_oa ? '<span style="color:var(--color-accent)">Open Access</span>' : ''}
      </div>

      <div class="sp-section-label">Abstract</div>
      <p class="sp-abstract">${r.abstract ? esc(r.abstract) : '<span class="lead">Esta fuente no entregó el abstract.</span>'}</p>

      <div class="sp-section-label">Identificadores</div>
      <div class="sp-ids">
        <div><span class="k">DOI:</span> <span class="r-doi">${esc(doiCorto(r.doi) || '—')}</span></div>
        ${r.openalex_id ? `<div><span class="k">OpenAlex:</span> <span class="r-doi">${esc(String(r.openalex_id).replace('https://openalex.org/', ''))}</span></div>` : ''}
        <div><span class="k">OA URL:</span> <span class="r-doi">${esc(r.oa_url || '—')}</span></div>
        ${r.motor_pdf === 'scihub' ? `<div><span class="k">PDF (Sci-Hub):</span> <span class="r-doi">${esc(r.pdf_url)}</span></div>` : ''}
        <div><span class="k">Encontrado en:</span> <span class="r-doi">${esc(motores(r).map(motor).join(', ') || '—')}</span></div>
        <div><span class="k">Página de origen:</span> <span class="r-doi">${esc(paginaOrigen(r) || '—')}${paginaOrigen(r) && r.motor_pdf && r.motor_pdf !== 'ninguno' ? ` (enlace dado por ${esc(motor(r.motor_pdf))})` : ''}</span></div>
      </div>

      <div class="sp-section-label">Cadena coincidente</div>
      <span class="match-chip">${esc(r.matched_query)}</span>

      <div class="sp-actions">
        ${/^https?:\/\//.test(url) ? `<a class="btn btn-primary" href="${esc(url)}" target="_blank" rel="noopener noreferrer">Abrir original</a>` : '<button class="btn btn-primary" disabled>Abrir original</button>'}
        <button class="btn btn-secondary" data-action="toggle-pick">${picked ? '★ En la selección' : 'Añadir a selección'}</button>
      </div>
    </div>`;
}

// ---------- datos ----------

async function loadList() {
  S.projects = await api('GET', '/api/proyectos');
}

function setProject(p) {
  S.proj = p;
  const item = S.projects.find((x) => x.id === p.id);
  if (item) { item.name = p.name; item.stage = p.stage; }
  clearInterval(pollTimer);
  pollTimer = null;
  if (p.stage === 'loading') pollTimer = setInterval(poll, 1000);
}

async function selectProject(id) {
  const p = await api('GET', `/api/proyectos/${id}`);
  S.filterText = '';
  S.onlyOA = false;
  S.onlyPicked = false;
  S.selId = null;
  S.panelOpen = false;
  S.renaming = false;
  S.error = null;
  setProject(p);
  try { localStorage.setItem('buscador.activo', id); } catch (e) { /* almacenamiento bloqueado */ }
  render();
}

async function poll() {
  const id = S.proj && S.proj.id;
  if (!id) return;
  let p;
  try { p = await api('GET', `/api/proyectos/${id}`); } catch (e) { return; }  // se reintenta en el siguiente tick
  if (!S.proj || S.proj.id !== id) return;
  const sameSteps = p.stage === 'loading' && JSON.stringify(p.progreso) === JSON.stringify(S.proj.progreso);
  setProject(p);
  if (!sameSteps) render();  // sin cambios no se repinta: reiniciaría las animaciones
}

async function createProject() {
  const p = await api('POST', '/api/proyectos');
  S.projects.push({ id: p.id, name: p.name, stage: p.stage });
  return p;
}

const save = (fields) => api('PUT', `/api/proyectos/${S.proj.id}`, fields);

const actions = {
  'new-project': async () => {
    const p = await createProject();
    await selectProject(p.id);
    const prompt = $('#prompt');
    if (prompt) prompt.focus();
  },
  'select-project': (el) => selectProject(el.dataset.id),
  rename: () => {
    S.renaming = true;
    renderTop();
    const input = $('#title-input');
    input.focus();
    input.select();
  },
  'delete-project': async (el) => {
    const id = el.dataset.id;
    const p = S.projects.find((x) => x.id === id);
    if (!confirm(`¿Eliminar el proyecto «${p.name}»? Se borran sus cadenas y resultados; no se puede deshacer.`)) return;
    await api('DELETE', `/api/proyectos/${id}`);
    S.projects = S.projects.filter((x) => x.id !== id);
    if (S.proj && S.proj.id === id) {
      clearInterval(pollTimer);
      pollTimer = null;
      S.proj = null;
      S.selId = null;
      S.panelOpen = false;
      S.renaming = false;
      const next = S.projects[S.projects.length - 1];
      if (next) return selectProject(next.id);
    }
    render();
  },
  reset: async () => {
    if (S.proj.papers.length && !confirm('¿Reiniciar el proyecto? Se borran sus cadenas y resultados.')) return;
    setProject(await save({ reiniciar: true }));
    S.selId = null;
    S.panelOpen = false;
    render();
  },
  generate: async () => {
    const f = form();
    if (!String(f.prompt).trim()) throw new Error('Escribe primero el tema que quieres investigar.');
    if (!S.proj) setProject({ ...(await createProject()), ...DRAFT });
    S.busy = true;
    render();
    try {
      setProject(await api('POST', `/api/proyectos/${S.proj.id}/cadenas`, {
        prompt: S.proj.prompt, num: S.proj.num, idioma: S.proj.idioma,
      }));
    } finally {
      S.busy = false;
      render();
    }
  },
  'add-query': async () => {
    S.proj.queries.push('');
    renderContent();
    const inputs = document.querySelectorAll('.query-row input');
    inputs[inputs.length - 1].focus();
    await save({ queries: S.proj.queries });
  },
  'remove-query': async (el) => {
    S.proj.queries.splice(Number(el.dataset.idx), 1);
    renderContent();
    await save({ queries: S.proj.queries });
  },
  'back-to-prompt': async () => { setProject(await save({ queries: S.proj.queries, stage: 'empty' })); render(); },
  'back-to-queries': async () => {
    setProject(await save({ stage: 'queries' }));
    S.panelOpen = false;
    render();
  },
  'back-to-results': async () => {
    setProject(await save({ queries: S.proj.queries, stage: 'results' }));
    render();
  },
  'run-search': async () => {
    if (S.proj.papers.length && !confirm('Una búsqueda nueva reemplaza los resultados y la selección actuales. ¿Continuar?')) return;
    setProject(await api('POST', `/api/proyectos/${S.proj.id}/buscar`, {
      queries: S.proj.queries, min_year: S.proj.min_year, max_resultados: S.proj.max_resultados,
    }));
    S.selId = null;
    S.panelOpen = false;
    S.filterText = '';
    S.onlyOA = false;
    S.onlyPicked = false;
    render();
  },
  'cancel-search': async () => {
    setProject(await api('POST', `/api/proyectos/${S.proj.id}/cancelar`));
    render();
  },
  'open-paper': (el) => {
    S.selId = el.dataset.id;
    S.panelOpen = true;
    renderRows();
    renderPanel();
  },
  'close-panel': () => {
    S.panelOpen = false;
    renderRows();
    renderPanel();
  },
  'toggle-pick': async () => {
    const list = S.proj.seleccion;
    const i = list.indexOf(S.selId);
    if (i === -1) list.push(S.selId); else list.splice(i, 1);
    renderRows();
    renderPanel();
    await save({ seleccion: list });
  },
};

document.addEventListener('click', (e) => {
  const el = e.target.closest('[data-action]');
  if (!el || el.disabled) return;
  run(() => actions[el.dataset.action](el));
});

document.addEventListener('input', (e) => {
  const t = e.target;
  if (t.dataset.input === 'prompt') form().prompt = t.value;
  else if (t.dataset.input === 'num') form().num = t.value;
  else if (t.dataset.input === 'query') S.proj.queries[Number(t.dataset.idx)] = t.value;
  else if (t.dataset.input === 'min_year' || t.dataset.input === 'max_resultados') S.proj[t.dataset.input] = t.value;
  else if (t.dataset.input === 'filter') { S.filterText = t.value; renderRows(); }
});

// "change" llega al salir del campo (o al elegir una opción): ahí se guarda en el servidor
document.addEventListener('change', (e) => {
  const t = e.target;
  if (t.name === 'oaf') { S.onlyOA = t.value === 'oa'; renderRows(); return; }
  if (t.name === 'pickf') { S.onlyPicked = t.checked; renderRows(); return; }
  if (t.name === 'lang') form().idioma = t.value;
  if (!S.proj || S.busy) return;
  if (t.name === 'lang') run(() => save({ idioma: t.value }));
  else if (t.dataset.input === 'prompt') run(() => save({ prompt: t.value }));
  else if (t.dataset.input === 'num') run(() => save({ num: t.value }));
  else if (t.dataset.input === 'query') run(() => save({ queries: S.proj.queries }));
  else if (t.dataset.input === 'min_year' || t.dataset.input === 'max_resultados') {
    // El servidor ajusta el valor a sus límites: se toma el que quedó guardado
    run(async () => {
      const p = await save({ [t.dataset.input]: t.value });
      S.proj[t.dataset.input] = p[t.dataset.input];
      t.value = p[t.dataset.input] ?? '';
    });
  }
});

// El título se guarda al salir del campo o con Enter; Escape cancela
function commitTitle(input) {
  if (!S.renaming) return;
  S.renaming = false;
  const name = input.value.trim();
  if (!name || name === S.proj.name) { renderTop(); return; }
  run(async () => {
    setProject(await save({ name }));
    renderSide();
    renderTop();
  });
}

document.addEventListener('focusout', (e) => {
  if (e.target.dataset && e.target.dataset.input === 'title') commitTitle(e.target);
});

document.addEventListener('keydown', (e) => {
  if (e.target.dataset && e.target.dataset.input === 'title') {
    if (e.key === 'Enter') commitTitle(e.target);
    if (e.key === 'Escape') { S.renaming = false; renderTop(); }
    return;
  }
  if (e.key === 'Escape' && S.panelOpen) actions['close-panel']();
  if (e.key === 'Enter' && e.target.dataset && e.target.dataset.input === 'query') e.target.blur();
});

run(async () => {
  render();
  await loadList();
  let last = null;
  try { last = localStorage.getItem('buscador.activo'); } catch (e) { /* almacenamiento bloqueado */ }
  const first = S.projects.find((p) => p.id === last) || S.projects[S.projects.length - 1];
  if (first) await selectProject(first.id); else render();
});
