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
  tab: 'busqueda',   // pestaña de los resultados: 'busqueda' | 'procesamiento'
};
// Estado de la pestaña "Resultados de procesamiento" del proyecto activo
const proc = {
  fichas: [],          // fichas de los papers (GET /fichas), con su índice en _i
  q: '', filtro: 'relevantes',   // relevantes | parcial | no_relevante | todas
  open: new Set(),     // fichas expandidas (por _i)
  alcance: null,       // 'sel' | 'todos'; null = según haya o no selección
  configurando: false, // eligiendo el alcance de una nueva corrida sobre un proyecto ya procesado
};
// Ronda de aclaración del tema (Nemotron pregunta cuando el prompt es muy general)
const ACL = { fase: null, preguntas: [], respuestas: [], historial: [], ronda: 0, tema: '', custom: [], vistas: [] };
const resetAcl = () => Object.assign(ACL, { fase: null, preguntas: [], respuestas: [], historial: [], ronda: 0, tema: '', custom: [], vistas: [] });
// Borrador del formulario cuando todavía no existe ningún proyecto
const DRAFT = { prompt: '', num: 5, idioma: 'en' };
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
  if (stage === 'results' && S.tab === 'busqueda') renderRows();
}

function aclaracionHTML() {
  const qs = ACL.preguntas.map((q, i) => `
    <div class="field acl-q">
      <label for="acl-${i}">${esc(q.pregunta)}</label>
      <input class="input" id="acl-${i}" data-input="acl" data-idx="${i}" value="${esc(ACL.respuestas[i])}" placeholder="Tu respuesta (puedes dejarla vacía)">
      ${(q.ejemplos || []).length ? `<div class="chips acl-ej">${q.ejemplos.map((ej) => `<button type="button" class="match-chip" data-action="acl-ejemplo" data-idx="${i}" data-ej="${esc(ej)}">${esc(ej)}</button>`).join('')}</div>` : ''}
    </div>`).join('');
  const customs = (ACL.custom || []).map((c, i) => `
    <div class="field acl-q">
      <label for="acl-custom-${i}">Pregunta propia</label>
      <input class="input" id="acl-custom-${i}" data-input="acl-custom-preg" data-idx="${i}" value="${esc(c.pregunta)}" placeholder="Escribe tu propia pregunta...">
      <label for="acl-custom-res-${i}" style="margin-top:6px">Respuesta</label>
      <input class="input" id="acl-custom-res-${i}" data-input="acl-custom-res" data-idx="${i}" value="${esc(c.respuesta)}" placeholder="Tu respuesta (puedes dejarla vacía)">
      <button class="btn btn-ghost" style="margin-top:4px;align-self:flex-start" data-action="acl-custom-remove" data-idx="${i}">Eliminar pregunta propia</button>
    </div>`).join('');
  return `
    <div class="acl-card">
      <div class="kicker">Afinemos el tema · ronda ${ACL.ronda} de 2</div>
      <p class="lead acl-lead">El tema es bastante general. Responde lo que sepas para que las cadenas busquen justo lo que necesitas.</p>
      ${qs}
      ${customs}
      <button class="btn btn-ghost" data-action="acl-custom-add" style="align-self:flex-start">+ Añadir pregunta y respuesta propia</button>
      <div class="row-inline">
        <button class="btn btn-primary" data-action="acl-responder" ${S.busy ? 'disabled' : ''}>${S.busy ? 'Evaluando…' : 'Continuar →'}</button>
        <button class="btn btn-ghost" data-action="acl-omitir" ${S.busy ? 'disabled' : ''}>Omitir y generar cadenas</button>
        <button class="btn btn-ghost" data-action="acl-cancelar" ${S.busy ? 'disabled' : ''}>Editar el prompt</button>
      </div>
    </div>`;
}

// Prompt ya usado para generar cadenas: se muestra bloqueado con sus preguntas y respuestas
function bloqueadoHTML() {
  const qa = S.proj.aclaraciones || [];
  const intencion = (S.proj.intencion_cadenas || {}).intencion_consolidada || S.proj.intencion_busqueda || '';
  const items = qa.map((a) => `
    <div class="field acl-q">
      <label>${esc(a.pregunta)}</label>
      <div class="acl-resp">${a.respuesta ? esc(a.respuesta) : '<em>Sin respuesta</em>'}</div>
    </div>`).join('');
  return `
    <div class="acl-card">
      <div class="kicker">Preguntas y respuestas de este prompt</div>
      ${items || '<p class="lead acl-lead">Este prompt no necesitó preguntas de aclaración.</p>'}
      ${intencion ? `<div class="notice"><strong>Intención detectada:</strong> ${esc(intencion)}</div>` : ''}
      <div class="row-inline">
        <button class="btn btn-primary" data-action="back-to-queries">Ver cadenas →</button>
        <button class="btn btn-ghost" data-action="rehacer-prompt">Rehacer prompt</button>
      </div>
    </div>`;
}

function viewPrompt() {
  const f = form();
  const preguntando = ACL.fase === 'preguntando';
  const bloqueado = !preguntando && !!(S.proj && S.proj.tema_refinado);
  const lang = (value, label) => `<label class="seg-opt"><input type="radio" name="lang" value="${value}" ${f.idioma === value ? 'checked' : ''} ${bloqueado ? 'disabled' : ''}><span>${label}</span></label>`;
  return `
    <div class="prompt-wrap">
      <div class="kicker">Nuevo proyecto</div>
      <h2>¿Qué quieres investigar?</h2>
      <p class="lead">Describe el tema en lenguaje natural. Generaremos varias cadenas de búsqueda que podrás revisar antes de lanzar la consulta.</p>

      <div class="field">
        <label for="prompt">Prompt</label>
        <textarea class="input" id="prompt" rows="4" data-input="prompt" ${preguntando || bloqueado ? 'disabled' : ''} placeholder="ej. Efectos del microbioma intestinal en trastornos del espectro autista en población pediátrica, estudios de los últimos 5 años">${esc(f.prompt)}</textarea>
      </div>

      <div class="row-inline">
        <div class="field num-field">
          <label for="num">Cadenas a generar</label>
          <input class="input" id="num" type="number" min="1" max="12" value="${esc(f.num)}" data-input="num" ${bloqueado ? 'disabled' : ''}>
        </div>
        <div class="field">
          <label>Idioma de las cadenas</label>
          <div class="seg">${lang('en', 'Inglés')}${lang('ambos', 'Ambos')}${lang('es', 'Español')}</div>
        </div>
        ${preguntando || bloqueado ? '' : `<button class="btn btn-primary" data-action="generate" ${S.busy ? 'disabled' : ''}>${S.busy ? 'Revisando el tema…' : 'Generar cadenas →'}</button>`}
      </div>
      ${preguntando ? aclaracionHTML() : ''}
      ${bloqueado ? bloqueadoHTML() : ''}
      <p class="prompt-hint">Puedes escribir el tema en español: las cadenas se traducen. Casi toda la literatura indexada está en inglés; «Ambos» añade los términos en español y «Español» solo encuentra una fracción pequeña de los papers.</p>
      ${notice()}
    </div>`;
}

function viewQueries() {
  const qs = S.proj.queries || [];
  const intencion = S.proj.intencion_cadenas || {};
  const intencionTexto = intencion.intencion_consolidada || S.proj.intencion_busqueda || '';
  const detalles = intencion.detalles || [];
  return `
    <div>
      <div class="kicker">Paso 2 de 3</div>
      <h2 style="margin:0 0 8px">Cadenas de búsqueda</h2>
      <p class="lead" style="margin:0 0 8px; max-width:620px">Edita, elimina o añade cadenas antes de ejecutar el servicio. Cada cadena se consultará contra OpenAlex, Semantic Scholar y Scopus; los papers mejor rankeados sin PDF abierto se buscan además en Sci-Hub por su DOI.</p>
      ${intencionTexto ? `<div class="notice" style="max-width:720px"><strong>Intención de búsqueda:</strong> ${esc(intencionTexto)}</div>` : ''}
      ${notice()}

      <div class="queries-head">
        <div class="meta">${qs.length} cadenas · generadas a partir del prompt</div>
      </div>

      <div class="query-list">
        ${qs.map((text, i) => {
          const det = detalles.find(d => d && d.cadena === text) || detalles[i] || {};
          const hasInfo = !!det.intencion;
          return `
          <div class="query-block ${hasInfo ? 'has-info' : ''}" data-qblock="${i}">
            <div class="query-row">
              <span class="idx">${String(i + 1).padStart(2, '0')}</span>
              <input value="${esc(text)}" data-input="query" data-idx="${i}" aria-label="Cadena ${i + 1}" spellcheck="false">
              ${hasInfo ? `<button class="qinfo" data-action="toggle-query-info" data-idx="${i}" title="Ver intención de esta cadena">ℹ️</button>` : '<span class="qinfo-spacer"></span>'}
              <button class="rm" data-action="remove-query" data-idx="${i}" title="Eliminar" aria-label="Eliminar cadena ${i + 1}">✕</button>
            </div>
            ${hasInfo ? `<div class="query-detail"><div class="query-detail-inner"><strong>Intención para esta cadena:</strong> ${esc(det.intencion)}${det.alcance ? `<br><strong>Alcance:</strong> ${esc(det.alcance)}` : ''}</div></div>` : ''}
          </div>`;
        }).join('')}
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
  return `${tabsHTML()}${S.tab === 'procesamiento' ? viewProcesamiento() : viewBusqueda()}`;
}

function viewBusqueda() {
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

// ---------- resultados de procesamiento ----------

const ESTADOS_PAPER = ['ok', 'no_relevante', 'sin_abstract', 'error', 'pendiente'];
const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;
const FUENTES = { nemotron_parse: 'Nemotron Parse', 'local+nemotron_parse': 'Lectura local + Nemotron Parse',
  local: 'Lectura local', europepmc: 'Europe PMC' };

function tabsHTML() {
  const p = S.proj.procesamiento;
  const badge = p.activo ? '<span class="ptab-live">en curso</span>'
    : p.estado === 'error' ? '<span class="state-chip" data-k="error">error</span>'
    : proc.fichas.length ? `<span class="ptab-count">${proc.fichas.length}</span>` : '';
  const tab = (key, label, extra) => `<button class="ptab" role="tab" data-action="tab" data-tab="${key}" aria-selected="${S.tab === key}">${label}${extra}</button>`;
  return `
    <div class="ptabs" role="tablist">
      ${tab('busqueda', 'Resultados de búsqueda', `<span class="ptab-count">${S.proj.papers.length}</span>`)}
      ${tab('procesamiento', 'Resultados de procesamiento', badge)}
    </div>`;
}

// Cuántos papers entran en cada alcance (el servidor procesa como mucho `tope` por corrida)
function alcances() {
  const tope = S.proj.procesamiento.tope || Infinity;
  const ids = new Set(S.proj.papers.map((r) => r.id));
  const nSel = S.proj.seleccion.filter((id) => ids.has(id)).length;
  const modo = (proc.alcance === 'sel' && nSel) || (proc.alcance === null && nSel) ? 'sel' : 'todos';
  return { modo, tope, nSel, nTodos: S.proj.papers.length };
}

function resumenCorrida(p) {
  const partes = [];
  const ini = p.inicio ? new Date(p.inicio) : null;
  const fin = p.fin ? new Date(p.fin) : null;
  const hora = (d) => d.toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' });
  if (ini && !isNaN(ini)) {
    partes.push(ini.toLocaleDateString('es', { day: 'numeric', month: 'short', year: 'numeric' }));
    if (fin && !isNaN(fin)) {
      const seg = Math.max(0, Math.round((fin - ini) / 1000));
      partes.push(`${hora(ini)} → ${hora(fin)}`, seg >= 60 ? `${Math.floor(seg / 60)} min ${seg % 60} s` : `${seg} s`);
    } else partes.push(hora(ini));
  }
  if (p.total) partes.push(`${plural(p.total, 'paper', 'papers')} ${p.alcance === 'sel' ? 'de la selección' : 'del proyecto'}`);
  return partes.join(' · ');
}

function alcanceCardHTML(p) {
  const a = alcances();
  const pedidos = a.modo === 'sel' ? a.nSel : a.nTodos;
  const n = Math.min(pedidos, a.tope);
  const texto = (a.modo === 'sel'
    ? `Se procesarán los ${plural(n, 'paper marcado', 'papers marcados')} en Resultados de búsqueda.`
    : `Se procesarán los ${plural(n, 'paper', 'papers')} del proyecto.`)
    + (pedidos > a.tope ? ` Son ${pedidos}, pero cada corrida procesa como máximo ${a.tope}.` : '')
    + ' Solo los de acceso abierto se leen completos (PDF o Europe PMC); del resto se resume el abstract y la ficha queda como parcial.'
    + (p.estado ? ' Los papers que ya tienen ficha no se vuelven a leer ni a enviar al modelo.' : '');
  return `
    <div class="run-card is-empty">
      <div>
        <div class="run-empty-title">Procesar PDFs</div>
        <div class="run-empty-lead">Nemotron Parse lee el PDF de cada paper y extrae las piezas del paper: el abstract, el penúltimo y el último párrafo de la introducción, las conclusiones y las tablas (nombre y atributos). Nemotron resume solo eso en una ficha: objetivo, conclusiones, hallazgos clave y qué aporta cada tabla.</div>
      </div>
      <div class="run-field">
        <span class="run-label">Alcance</span>
        <div class="seg">
          <label class="seg-opt"><input type="radio" name="obs-alcance" value="sel" ${a.modo === 'sel' ? 'checked' : ''} ${a.nSel ? '' : 'disabled'}>Selección<span class="n">${a.nSel}</span></label>
          <label class="seg-opt"><input type="radio" name="obs-alcance" value="todos" ${a.modo === 'todos' ? 'checked' : ''}>Todos<span class="n">${a.nTodos}</span></label>
        </div>
      </div>
      <div class="run-scope">${esc(texto)}</div>
      <div class="run-go">
        <button class="btn btn-primary" data-action="procesar" data-alcance="${a.modo}" ${n ? '' : 'disabled'}>Procesar ${plural(n, 'paper', 'papers')}</button>
        ${p.estado ? '<button class="btn btn-ghost" data-action="obs-configurar">Volver</button>' : ''}
        <span class="run-note">Puede tardar varios minutos. El proceso sigue en el servidor si sales de la página.</span>
      </div>
    </div>`;
}

function runCardHTML(p) {
  if (p.activo) {
    const pct = p.total ? Math.round((p.hechos / p.total) * 100) : 0;
    return `
    <div class="run-card">
      <div class="run-head">
        <div>
          <div class="run-title">Procesando <span class="run-frac">${esc(p.hechos)} / ${esc(p.total)}</span></div>
          <div class="run-meta run-now">Ahora: ${esc(p.actual || '—')}</div>
        </div>
        <button class="btn btn-secondary" data-action="cancelar-procesar">Cancelar</button>
      </div>
      <div class="run-progress"><i style="width:${pct}%"></i></div>
      <div class="run-log">${p.mensajes.slice(-8).map((l) => `<div>${esc(l)}</div>`).join('')}</div>
      <div class="run-note">Se actualiza solo. Puedes cambiar de pestaña; las fichas aparecen aquí al terminar.</div>
    </div>`;
  }
  if (!p.estado || proc.configurando) return alcanceCardHTML(p);

  const conteos = p.conteos || {};
  const claves = [...ESTADOS_PAPER.filter((k) => conteos[k]), ...Object.keys(conteos).filter((k) => !ESTADOS_PAPER.includes(k))];
  const chips = claves.map((k) => `<span class="state-chip" data-k="${esc(k)}">${esc(k)} ${esc(conteos[k])}</span>`).join('');
  const completas = proc.fichas.filter((f) => f.cobertura === 'completa').length;
  const parciales = proc.fichas.filter((f) => f.cobertura === 'parcial').length;
  const aviso = p.estado === 'error' ? `
    <div class="notice-error">
      <div class="notice-error-body"><h4>El procesamiento se detuvo</h4><code>${esc(p.error || 'Error desconocido')}</code></div>
      <button class="btn btn-primary" data-action="procesar" data-alcance="${esc(p.alcance || 'todos')}">Reintentar</button>
    </div>` : '';
  return `${aviso}
    <div class="run-card">
      <div class="run-head">
        <div>
          <div class="run-title">${p.estado === 'error' ? 'Resultados parciales' : 'Procesamiento completado'}</div>
          <div class="run-meta">${esc(resumenCorrida(p))}</div>
        </div>
        <div class="run-actions">
          <button class="btn btn-secondary" data-action="obs-csv" ${proc.fichas.length ? '' : 'disabled'}>Exportar CSV</button>
          <button class="btn btn-primary" data-action="obs-configurar">Volver a procesar</button>
        </div>
      </div>
      <div class="stat-row">
        <div class="stat"><span class="n">${proc.fichas.length}${p.total ? `<small> / ${esc(p.total)}</small>` : ''}</span><span class="l">Fichas</span></div>
        <div class="stat"><span class="n">${completas}</span><span class="l">Con PDF leído</span></div>
        <div class="stat"><span class="n">${parciales}</span><span class="l">Solo abstract</span></div>
        ${chips ? `<div class="state-chips"><span class="run-note">Estado por paper</span>${chips}</div>` : ''}
      </div>
    </div>`;
}

const doiUrl = (doi) => `https://doi.org/${encodeURI(doiCorto(doi))}`;

function fichasFiltradas() {
  const q = proc.q.trim().toLowerCase();
  const porTexto = proc.fichas.filter((f) => !q || [f.title, f.resumen, f.objetivo, f.abstract, f.intro_penultimo, f.intro_ultimo, f.conclusion_texto, ...f.conclusiones,
    ...f.hallazgos_clave, ...f.tablas.map((t) => t.nombre)].join(' ').toLowerCase().includes(q));
  const pasa = {
    relevantes: (f) => f.estado === 'ok',
    parcial: (f) => f.estado === 'ok' && f.cobertura === 'parcial',
    no_relevante: (f) => f.estado === 'no_relevante',
    todas: () => true,
  }[proc.filtro];
  return { porTexto, filas: porTexto.filter(pasa) };
}

const lista = (items) => (items.length ? `<ul>${items.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : '');

function fichaHTML(f) {
  const open = proc.open.has(f._i);
  const parcial = f.cobertura === 'parcial';
  const chips = [
    f.estado === 'no_relevante' ? '<span class="state-chip" data-k="no_relevante">no relevante</span>' : '',
    parcial ? '<span class="state-chip" data-k="sin_abstract" title="No se pudo leer el PDF: la ficha sale solo del abstract">solo abstract</span>'
      : `<span class="match-chip">${esc(FUENTES[f.fuente] || f.fuente || 'PDF')}</span>`,
  ].join('');
  const tablas = f.tablas.map((t) => `
    <div class="ficha-tabla">
      <div class="ficha-tabla-nombre">${esc(t.nombre)}</div>
      ${t.atributos.length ? `<div class="chips">${t.atributos.map((a) => `<span class="obs-var">${esc(a)}</span>`).join('')}</div>` : ''}
      ${t.que_aporta ? `<div class="ficha-nota">${esc(t.que_aporta)}</div>` : ''}
    </div>`).join('');
  const seccion = (titulo, cuerpo) => (cuerpo ? `<div class="ficha-sec"><div class="sp-section-label">${titulo}</div>${cuerpo}</div>` : '');
  return `
    <div class="ficha ${open ? 'is-open' : ''}">
      <div class="ficha-head" role="button" tabindex="0" data-action="ficha-toggle" data-i="${f._i}" aria-expanded="${open}">
        <span class="caret">${open ? '▾' : '▸'}</span>
        <div class="ficha-main">
          <div class="ficha-title">${esc(f.title || '(sin título)')}</div>
          <div class="ficha-sub">${esc(f.year || '')}${f.doi ? ` · <a class="doi" href="${esc(doiUrl(f.doi))}" target="_blank" rel="noopener noreferrer">doi:${esc(doiCorto(f.doi))} ↗</a>` : ''}</div>
          <div class="ficha-resumen">${esc(f.resumen || 'Sin resumen.')}</div>
        </div>
        <div class="ficha-badges">${chips}</div>
      </div>
      ${open ? `<div class="ficha-body">
        ${seccion('Objetivo', f.objetivo ? `<p>${esc(f.objetivo)}</p>` : '')}
        ${seccion('Abstract', f.abstract ? `<p>${esc(f.abstract)}</p>` : '')}
        ${seccion('Introducción — penúltimo párrafo', f.intro_penultimo ? `<p>${esc(f.intro_penultimo)}</p>` : '')}
        ${seccion('Introducción — último párrafo', f.intro_ultimo ? `<p>${esc(f.intro_ultimo)}</p>` : '')}
        ${seccion('Conclusiones (texto del paper)', f.conclusion_texto ? `<p>${esc(f.conclusion_texto)}</p>` : '')}
        ${seccion('Conclusiones (resumidas)', lista(f.conclusiones))}
        ${seccion('Hallazgos clave', lista(f.hallazgos_clave))}
        ${seccion(`Tablas (${f.tablas.length})`, tablas)}
        ${parcial ? '<div class="ficha-nota">Ficha parcial: no hubo PDF accesible, así que solo tiene el abstract (sin introducción, conclusiones ni tablas).</div>' : ''}
      </div>` : ''}
    </div>`;
}

function fichasListaHTML() {
  const { porTexto, filas } = fichasFiltradas();
  const cuenta = (fn) => porTexto.filter(fn).length;
  const segs = [['relevantes', 'Relevantes', cuenta((f) => f.estado === 'ok')],
    ['parcial', 'Solo abstract', cuenta((f) => f.estado === 'ok' && f.cobertura === 'parcial')],
    ['no_relevante', 'No relevantes', cuenta((f) => f.estado === 'no_relevante')],
    ['todas', 'Todas', porTexto.length]]
    .map(([k, l, n]) => `<label class="seg-opt"><input type="radio" name="ficha-filtro" value="${k}" ${proc.filtro === k ? 'checked' : ''}>${l}<span class="n">${n}</span></label>`).join('');
  return `
    <div class="obs-toolbar">
      <input class="input" data-input="obs-q" placeholder="Buscar en título, resumen, introducción, conclusiones, tablas…" value="${esc(proc.q)}" aria-label="Filtrar fichas">
      <div class="seg">${segs}</div>
    </div>
    <div>
      <div class="obs-count"><span>${plural(filas.length, 'ficha', 'fichas')}</span>
        ${filas.length ? `<span class="obs-count-actions">
          <button class="btn btn-ghost" data-action="obs-expandir">Expandir todo</button>
          <button class="btn btn-ghost" data-action="obs-colapsar">Colapsar todo</button></span>` : ''}
      </div>
      ${filas.length ? filas.map(fichaHTML).join('') : '<div class="obs-empty">Ninguna ficha coincide con los filtros. <button class="btn btn-ghost" data-action="obs-limpiar">Limpiar filtros</button></div>'}
    </div>`;
}

function viewProcesamiento() {
  const p = S.proj.procesamiento;
  return `
    <div class="proc-view">
      ${notice()}
      ${runCardHTML(p)}
      ${!p.activo && proc.fichas.length ? `<div class="obs-table" id="obs-tabla">${fichasListaHTML()}</div>` : ''}
    </div>`;
}

// Solo la lista: así el campo de búsqueda no pierde el foco ni el cursor
function renderObsTabla() {
  const tabla = $('#obs-tabla');
  if (!tabla) return;
  const activo = document.activeElement;
  const cursor = activo && activo.dataset.input === 'obs-q' ? activo.selectionStart : null;
  tabla.innerHTML = fichasListaHTML();
  if (cursor !== null) {
    const campo = tabla.querySelector('[data-input="obs-q"]');
    campo.focus();
    campo.setSelectionRange(cursor, cursor);
  }
}

function exportarFichasCSV() {
  const cols = ['title', 'year', 'doi', 'estado', 'cobertura', 'fuente', 'resumen', 'objetivo', 'abstract',
    'intro_penultimo', 'intro_ultimo', 'conclusion_texto', 'conclusiones', 'hallazgos_clave', 'tablas'];
  const plano = (f) => ({
    ...f,
    conclusiones: f.conclusiones.join(' | '),
    hallazgos_clave: f.hallazgos_clave.join(' | '),
    tablas: f.tablas.map((t) => `${t.nombre} [${t.atributos.join('; ')}]`).join(' | '),
  });
  const celda = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const csv = [cols.join(','), ...proc.fichas.map((f) => cols.map((c) => celda(plano(f)[c])).join(','))].join('\n');
  const enlace = document.createElement('a');
  enlace.href = URL.createObjectURL(new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' }));
  enlace.download = `${S.proj.archivo.replace(/\.db$/, '')}_fichas.csv`;
  enlace.click();
  URL.revokeObjectURL(enlace.href);
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
  if (!$('#rows')) return;  // la tabla de papers solo existe en la pestaña de búsqueda
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

async function cargarFichas() {
  const id = S.proj && S.proj.id;
  let fichas = [];
  if (id && S.proj.stage === 'results') {
    try { fichas = await api('GET', `/api/proyectos/${id}/fichas`); } catch (e) { /* se queda vacía */ }
  }
  if ((S.proj && S.proj.id) !== id) return;  // cambió de proyecto mientras cargaba
  proc.fichas = fichas.map((f, i) => ({ ...f, _i: i }));
  proc.open.clear();
}

function setProject(p) {
  S.proj = p;
  const item = S.projects.find((x) => x.id === p.id);
  if (item) { item.name = p.name; item.stage = p.stage; }
  clearInterval(pollTimer);
  pollTimer = null;
  if (p.stage === 'loading' || (p.procesamiento && p.procesamiento.activo)) pollTimer = setInterval(poll, 1000);
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
  S.tab = 'busqueda';
  Object.assign(proc, { fichas: [], q: '', filtro: 'relevantes', alcance: null, configurando: false });
  proc.open.clear();
  resetAcl();
  setProject(p);
  await cargarFichas();  // si ya se procesó antes, lo extraído se ve de entrada
  try { localStorage.setItem('buscador.activo', id); } catch (e) { /* almacenamiento bloqueado */ }
  render();
}

async function poll() {
  const id = S.proj && S.proj.id;
  if (!id) return;
  let p;
  try { p = await api('GET', `/api/proyectos/${id}`); } catch (e) { return; }  // se reintenta en el siguiente tick
  if (!S.proj || S.proj.id !== id) return;
  // Sin cambios no se repinta: reiniciaría las animaciones de progreso
  const cambio = p.stage !== S.proj.stage
    || (p.stage === 'loading' && JSON.stringify(p.progreso) !== JSON.stringify(S.proj.progreso))
    || JSON.stringify(p.procesamiento) !== JSON.stringify(S.proj.procesamiento);
  // Al terminar un procesamiento o una búsqueda (que reemplaza los papers) se recarga lo extraído
  const recargar = (S.proj.procesamiento.activo && !p.procesamiento.activo) || p.stage !== S.proj.stage;
  setProject(p);
  if (recargar) await cargarFichas();
  if (cambio) render();
}

async function createProject() {
  const p = await api('POST', '/api/proyectos');
  S.projects.push({ id: p.id, name: p.name, stage: p.stage });
  return p;
}

// Pregunta a Nemotron si el tema es lo bastante concreto: si no, muestra sus
// preguntas; si sí, genera las cadenas con el tema refinado
async function evaluarTema() {
  const r = await api('POST', `/api/proyectos/${S.proj.id}/aclarar`, { prompt: S.proj.prompt, historial: ACL.historial });
  if (!r.suficiente) {
    Object.assign(ACL, { fase: 'preguntando', preguntas: r.preguntas, respuestas: r.preguntas.map(() => ''),
      ronda: ACL.ronda + 1, tema: r.tema_refinado });
    return;
  }
  await crearCadenas(r.tema_refinado);
}

async function crearCadenas(refinado) {
  // Consolidar intención con historial + respuestas propias
  const partes = [`Tema original: ${S.proj.prompt}`];
  (ACL.historial || []).forEach(h => {
    if (h.pregunta) {
      if (h.respuesta && String(h.respuesta).trim()) {
        partes.push(`Pregunta: ${h.pregunta} Respuesta: ${String(h.respuesta).trim()}`);
      } else {
        partes.push(`Pregunta: ${h.pregunta}`);
      }
    }
  });
  const intencion = partes.join(' | ');
  setProject(await api('POST', `/api/proyectos/${S.proj.id}/cadenas`, {
    prompt: S.proj.prompt, num: S.proj.num, idioma: S.proj.idioma, tema_refinado: refinado,
    historial: ACL.historial, aclaraciones: ACL.vistas, intencion: intencion, intencion_busqueda: intencion
  }));
  resetAcl();
}

// Guarda todas las preguntas mostradas (también las sin respuesta) para poder revisarlas luego
function registrarVistas() {
  ACL.preguntas.forEach((q, i) => ACL.vistas.push({ pregunta: q.pregunta, respuesta: String(ACL.respuestas[i] || '').trim() }));
  (ACL.custom || []).forEach((c) => {
    if (String(c.pregunta || '').trim()) ACL.vistas.push({ pregunta: c.pregunta.trim(), respuesta: String(c.respuesta || '').trim() });
  });
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
    resetAcl();
    S.busy = true;
    render();
    try {
      await evaluarTema();
    } finally {
      S.busy = false;
      render();
    }
  },
  'acl-ejemplo': (el) => {
    const i = Number(el.dataset.idx);
    ACL.respuestas[i] = ACL.respuestas[i] ? `${ACL.respuestas[i]}, ${el.dataset.ej}` : el.dataset.ej;
    renderContent();
  },
  'acl-responder': async () => {
    registrarVistas();
    ACL.preguntas.forEach((q, i) => {
      if (String(ACL.respuestas[i] || '').trim()) {
        ACL.historial.push({ pregunta: q.pregunta, respuesta: ACL.respuestas[i].trim(), ronda: ACL.ronda });
      }
    });
    (ACL.custom || []).forEach((c) => {
      if (String(c.pregunta || '').trim()) {
        ACL.historial.push({ pregunta: c.pregunta.trim(), respuesta: String(c.respuesta || '').trim(), ronda: ACL.ronda, custom: true });
      }
    });
    S.busy = true;
    render();
    try {
      await evaluarTema();
    } finally {
      S.busy = false;
      render();
    }
  },
  'acl-omitir': async () => {
    registrarVistas();
    (ACL.custom || []).forEach((c) => {
      if (String(c.pregunta || '').trim()) {
        ACL.historial.push({ pregunta: c.pregunta.trim(), respuesta: String(c.respuesta || '').trim(), ronda: ACL.ronda, custom: true });
      }
    });
    S.busy = true;
    render();
    try {
      await crearCadenas(ACL.tema);
    } finally {
      S.busy = false;
      render();
    }
  },
  'acl-cancelar': () => { resetAcl(); render(); },
  'acl-custom-add': () => {
    if (!ACL.custom) ACL.custom = [];
    ACL.custom.push({ pregunta: '', respuesta: '' });
    renderContent();
  },
  'acl-custom-remove': (el) => {
    if (!ACL.custom) return;
    ACL.custom.splice(Number(el.dataset.idx), 1);
    renderContent();
  },
  'toggle-query-info': (el) => {
    const i = Number(el.dataset.idx);
    const block = document.querySelector(`.query-block[data-qblock="${i}"]`);
    if (block) {
      block.classList.toggle('open');
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
  'rehacer-prompt': async () => {
    if (!confirm('¿Rehacer el prompt? Se borran las preguntas y respuestas generadas, la intención detectada, las cadenas y los papers buscados (con su selección y procesamiento). Las preguntas se volverán a generar.')) return;
    setProject(await save({ rehacer_prompt: true }));
    resetAcl();
    render();
    const prompt = $('#prompt');
    if (prompt) prompt.focus();
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
    S.tab = 'busqueda';
    render();
  },
  'cancel-search': async () => {
    setProject(await api('POST', `/api/proyectos/${S.proj.id}/cancelar`));
    render();
  },
  tab: (el) => {
    S.tab = el.dataset.tab;
    S.panelOpen = false;
    S.error = null;
    render();
  },
  procesar: async (el) => {
    setProject(await api('POST', `/api/proyectos/${S.proj.id}/procesar`, { alcance: el.dataset.alcance }));
    proc.configurando = false;
    render();
  },
  'cancelar-procesar': async () => {
    setProject(await api('POST', `/api/proyectos/${S.proj.id}/cancelar-procesar`));
    await cargarFichas();
    render();
  },
  'obs-configurar': () => { proc.configurando = !proc.configurando; renderContent(); },
  'obs-csv': exportarFichasCSV,
  'obs-limpiar': () => { proc.q = ''; proc.filtro = 'todas'; renderObsTabla(); },
  'obs-expandir': () => { fichasFiltradas().filas.forEach((f) => proc.open.add(f._i)); renderObsTabla(); },
  'obs-colapsar': () => { proc.open.clear(); renderObsTabla(); },
  'ficha-toggle': (el) => {
    const i = Number(el.dataset.i);
    if (!proc.open.delete(i)) proc.open.add(i);
    renderObsTabla();
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
  if (e.target.closest('a')) return;  // un enlace dentro de una fila solo abre su destino
  const el = e.target.closest('[data-action]');
  if (!el || el.disabled) return;
  run(() => actions[el.dataset.action](el, e));
});

document.addEventListener('input', (e) => {
  const t = e.target;
  if (t.dataset.input === 'prompt') form().prompt = t.value;
  else if (t.dataset.input === 'num') form().num = t.value;
  else if (t.dataset.input === 'query') S.proj.queries[Number(t.dataset.idx)] = t.value;
  else if (t.dataset.input === 'min_year' || t.dataset.input === 'max_resultados') S.proj[t.dataset.input] = t.value;
  else if (t.dataset.input === 'filter') { S.filterText = t.value; renderRows(); }
  else if (t.dataset.input === 'acl') ACL.respuestas[Number(t.dataset.idx)] = t.value;
  else if (t.dataset.input === 'acl-custom-preg') { if (!ACL.custom) ACL.custom = []; if (!ACL.custom[Number(t.dataset.idx)]) ACL.custom[Number(t.dataset.idx)] = { pregunta: '', respuesta: '' }; ACL.custom[Number(t.dataset.idx)].pregunta = t.value; }
  else if (t.dataset.input === 'acl-custom-res') { if (!ACL.custom) ACL.custom = []; if (!ACL.custom[Number(t.dataset.idx)]) ACL.custom[Number(t.dataset.idx)] = { pregunta: '', respuesta: '' }; ACL.custom[Number(t.dataset.idx)].respuesta = t.value; }
  else if (t.dataset.input === 'obs-q') { proc.q = t.value; renderObsTabla(); }
});

// "change" llega al salir del campo (o al elegir una opción): ahí se guarda en el servidor
document.addEventListener('change', (e) => {
  const t = e.target;
  if (t.name === 'oaf') { S.onlyOA = t.value === 'oa'; renderRows(); return; }
  if (t.name === 'pickf') { S.onlyPicked = t.checked; renderRows(); return; }
  if (t.name === 'ficha-filtro') { proc.filtro = t.value; renderObsTabla(); return; }
  if (t.name === 'obs-alcance') { proc.alcance = t.value; renderContent(); return; }
  if (t.dataset.input === 'obs-q') return;
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
  if ((e.key === 'Enter' || e.key === ' ') && e.target.classList && e.target.classList.contains('ficha-head')) {
    e.preventDefault();
    e.target.click();
  }
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
