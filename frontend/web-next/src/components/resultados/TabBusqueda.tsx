'use client';

import { useMemo, useState } from 'react';
import { Download, Search } from 'lucide-react';
import { useApp } from '@/context/AppContext';
import { urlCsvPapers } from '@/lib/api';
import { TablaPapers } from './TablaPapers';
import css from './TabBusqueda.module.css';

interface Props {
  panelId: string | null;
  abrir: (id: string) => void;
}

export function TabBusqueda({ panelId, abrir }: Props) {
  const { proyecto } = useApp();
  const [texto, setTexto] = useState('');
  const [soloOa, setSoloOa] = useState(false);
  const [soloSel, setSoloSel] = useState(false);

  const papers = proyecto?.papers;
  const seleccion = proyecto?.seleccion;
  const filas = useMemo(() => {
    const q = texto.trim().toLowerCase();
    const marcados = new Set(seleccion);
    return (papers ?? []).filter((p) => {
      if (soloOa && !p.is_oa) return false;
      if (soloSel && !marcados.has(p.id)) return false;
      if (!q) return true;
      return [p.title, p.doi, p.source, p.abstract].some((v) => String(v || '').toLowerCase().includes(q));
    });
  }, [papers, seleccion, texto, soloOa, soloSel]);

  if (!proyecto) return null;
  const total = proyecto.papers.length;
  const abiertos = proyecto.papers.filter((p) => p.is_oa).length;
  const sinSeleccion = soloSel && proyecto.seleccion.length === 0;

  return (
    <div>
      <div className={css.stats}>
        <div className={`${css.stat} ${css.principal}`}><strong>{total}</strong><span>papers únicos</span></div>
        <div className={`${css.stat} ${css.verde}`}><strong>{abiertos}</strong><span>open access</span></div>
        <div className={css.stat}><strong>{proyecto.cadenas_usadas}</strong><span>cadenas usadas</span></div>
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
        <div className={css.espacio} />
        <span className={css.cuenta}>{filas.length} de {total}</span>
        <a className="btn btn-secondary" href={urlCsvPapers(proyecto.id, soloSel)} download>
          <Download size={15} strokeWidth={2.75} />{soloSel ? 'Exportar selección' : 'Exportar CSV'}
        </a>
      </div>

      <TablaPapers filas={filas} panelId={panelId} abrir={abrir}
        vacio={sinSeleccion
          ? 'Todavía no hay papers en la selección. Abre un paper y pulsa «Añadir a selección».'
          : 'Ningún paper coincide con el filtro.'} />
    </div>
  );
}
