'use client';

import { useMemo, useState } from 'react';
import { Download, ListTree, Search } from 'lucide-react';
import { useApp } from '@/context/AppContext';
import { urlCsvPapers } from '@/lib/api';
import { cadenasDe } from '@/lib/formato';
import { EntradaTerminos } from '../ui/EntradaTerminos';
import { DialogoCadenas } from './DialogoCadenas';
import { TablaPapers } from './TablaPapers';
import css from './TabBusqueda.module.css';

interface Props {
  panelId: string | null;
  abrir: (id: string) => void;
}

type Modo = 'todos' | 'alguno';

// Minúsculas y sin tildes, para que «inteligencia artificial» encuentre «Inteligéncia Artificial»
const normalizar = (texto: string) => texto.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();

export function TabBusqueda({ panelId, abrir }: Props) {
  const { proyecto } = useApp();
  const [texto, setTexto] = useState('');
  const [soloOa, setSoloOa] = useState(false);
  const [soloSel, setSoloSel] = useState(false);
  const [terminos, setTerminos] = useState<string[]>([]);
  const [modo, setModo] = useState<Modo>('todos');
  const [cadena, setCadena] = useState(0);            // 0 = todas; 1..N = solo los papers de esa cadena
  const [verCadenas, setVerCadenas] = useState(false);

  const papers = proyecto?.papers;
  const seleccion = proyecto?.seleccion;
  const queries = proyecto?.queries;

  // Cadenas (1..N) que encontraron cada paper: se calcula una vez por búsqueda
  const cadenasPorPaper = useMemo(
    () => new Map((papers ?? []).map((p) => [p.id, cadenasDe(p, queries ?? [])])), [papers, queries]);
  const conteos = useMemo(() => (queries ?? []).map((_, i) =>
    [...cadenasPorPaper.values()].filter((cs) => cs.includes(i + 1)).length), [queries, cadenasPorPaper]);

  const filas = useMemo(() => {
    const q = texto.trim().toLowerCase();
    const marcados = new Set(seleccion);
    const buscados = terminos.map(normalizar);
    return (papers ?? []).filter((p) => {
      if (soloOa && !p.is_oa) return false;
      if (soloSel && !marcados.has(p.id)) return false;
      if (cadena && !cadenasPorPaper.get(p.id)?.includes(cadena)) return false;
      if (buscados.length) {
        const contenido = normalizar(`${p.title || ''} ${p.abstract || ''}`);
        const pasa = modo === 'todos' ? buscados.every((t) => contenido.includes(t)) : buscados.some((t) => contenido.includes(t));
        if (!pasa) return false;
      }
      if (!q) return true;
      return [p.title, p.doi, p.source, p.abstract].some((v) => String(v || '').toLowerCase().includes(q));
    });
  }, [papers, seleccion, texto, soloOa, soloSel, terminos, modo, cadena, cadenasPorPaper]);

  if (!proyecto) return null;
  const total = proyecto.papers.length;
  const abiertos = proyecto.papers.filter((p) => p.is_oa).length;
  const sinSeleccion = soloSel && proyecto.seleccion.length === 0;
  const hayFiltros = !!(texto || soloOa || soloSel || terminos.length || cadena);

  const limpiar = () => { setTexto(''); setSoloOa(false); setSoloSel(false); setTerminos([]); setCadena(0); };

  return (
    <div>
      <div className={css.stats}>
        <div className={`${css.stat} ${css.principal}`}><strong>{total}</strong><span>papers únicos</span></div>
        <div className={`${css.stat} ${css.verde}`}><strong>{abiertos}</strong><span>open access</span></div>
        <button className={`${css.stat} ${css.statBoton}`} onClick={() => setVerCadenas(true)} title="Ver las cadenas y su intención">
          <strong>{proyecto.cadenas_usadas}</strong>
          <span><ListTree size={14} strokeWidth={2.75} /> cadenas usadas · ver</span>
        </button>
        <div className={css.stat}><strong>{proyecto.fuentes}</strong><span>{proyecto.fuentes === 1 ? 'fuente con resultados' : 'fuentes con resultados'}</span></div>
      </div>

      <div className={css.filtros}>
        <div className={css.buscador}>
          <Search size={15} strokeWidth={2.75} />
          <input className="input" value={texto} onChange={(e) => setTexto(e.target.value)}
            placeholder="Filtrar por título, fuente, DOI…" aria-label="Filtrar resultados" />
        </div>
        <button className={`${css.chip} ${soloOa ? css.chipOa : ''}`} aria-pressed={soloOa} onClick={() => setSoloOa(!soloOa)}>Solo OA</button>
        <button className={`${css.chip} ${soloSel ? css.chipSel : ''}`} aria-pressed={soloSel} onClick={() => setSoloSel(!soloSel)}>
          ★ Selección · {proyecto.seleccion.length}
        </button>
        <select className={`input ${css.selector}`} value={cadena} onChange={(e) => setCadena(Number(e.target.value))}
          aria-label="Filtrar por cadena">
          <option value={0}>Todas las cadenas</option>
          {proyecto.queries.map((_, i) => <option key={i} value={i + 1}>Cadena {i + 1} ({conteos[i] ?? 0})</option>)}
        </select>
        <div className={css.espacio} />
        <span className={css.cuenta}>{filas.length} de {total}</span>
        {hayFiltros && <button className="btn btn-ghost" onClick={limpiar}>Limpiar filtros</button>}
        <a className="btn btn-secondary" href={urlCsvPapers(proyecto.id, soloSel)} download>
          <Download size={15} strokeWidth={2.75} />{soloSel ? 'Exportar selección' : 'Exportar CSV'}
        </a>
      </div>

      <div className={css.terminos}>
        <div className={css.entradaTerminos}>
          <EntradaTerminos valores={terminos} cambiar={setTerminos} etiqueta="Filtrar por términos en título y abstract"
            placeholder="Términos en título o abstract (p. ej. artificial intelligence) · Enter" />
        </div>
        {terminos.length > 1 && (
          <div className={`seg ${css.modo}`} role="radiogroup" aria-label="Cómo combinar los términos">
            <label className="seg-opt" title="Solo los papers que tienen todos los términos">
              <input type="radio" name="modo-terminos" checked={modo === 'todos'} onChange={() => setModo('todos')} />Todos (AND)
            </label>
            <label className="seg-opt" title="Los papers que tienen al menos uno de los términos">
              <input type="radio" name="modo-terminos" checked={modo === 'alguno'} onChange={() => setModo('alguno')} />Alguno (OR)
            </label>
          </div>
        )}
      </div>

      <TablaPapers filas={filas} panelId={panelId} abrir={abrir}
        vacio={sinSeleccion
          ? 'Todavía no hay papers en la selección. Abre un paper y pulsa «Añadir a selección».'
          : 'Ningún paper coincide con los filtros.'} />

      {verCadenas && <DialogoCadenas conteos={conteos} cerrar={() => setVerCadenas(false)} filtrar={setCadena} />}
    </div>
  );
}
