'use client';

import { useEffect } from 'react';
import { ExternalLink, X } from 'lucide-react';
import { useApp } from '@/context/AppContext';
import { cadenasDe, doiCorto, motoresDe, nombreMotor, paginaOrigen, urlOriginal } from '@/lib/formato';
import css from './PanelPaper.module.css';

interface Props {
  id: string | null;
  cerrar: () => void;
}

// Detalle de un paper en un panel lateral; Escape lo cierra
export function PanelPaper({ id, cerrar }: Props) {
  const { proyecto, alternarSeleccion } = useApp();
  const paper = proyecto?.papers.find((p) => p.id === id);

  useEffect(() => {
    if (!paper) return;
    const alTeclear = (e: KeyboardEvent) => { if (e.key === 'Escape') cerrar(); };
    window.addEventListener('keydown', alTeclear);
    return () => window.removeEventListener('keydown', alTeclear);
  }, [paper, cerrar]);

  if (!proyecto || !paper) return null;
  const marcado = proyecto.seleccion.includes(paper.id);
  const url = urlOriginal(paper);
  const origen = paginaOrigen(paper);
  const coincidentes = cadenasDe(paper, proyecto.queries);
  const motorPdf = paper.motor_pdf && paper.motor_pdf !== 'ninguno' ? nombreMotor(paper.motor_pdf) : '—';

  return (
    <>
      <div className={css.velo} onClick={cerrar} />
      <aside className={css.panel} aria-label="Detalle del paper">
        <div className={css.cabecera}>
          {paper.source && <span className="tag tag-accent">{paper.source}</span>}
          <div className={css.espacio} />
          <button className="btn btn-secondary btn-icon" onClick={cerrar} title="Cerrar (Esc)" aria-label="Cerrar">
            <X size={15} strokeWidth={2.75} />
          </button>
        </div>

        <div className={css.cuerpo}>
          <h3 className={css.titulo}>{paper.title || '(sin título)'}</h3>
          <div className={css.datos}>
            <div className={css.dato}><span>Año</span><strong>{paper.year ?? '—'}</strong></div>
            <div className={css.dato}><span>Citas</span><strong>{paper.cited_by_count ?? 0}</strong></div>
            <div className={css.dato}><span>Open access</span><strong>{paper.is_oa ? 'Sí' : 'No'}</strong></div>
            <div className={css.dato}><span>Score</span><strong>{paper.score != null ? paper.score.toFixed(2) : '—'}</strong></div>
          </div>

          <div className={css.seccion}>Abstract</div>
          <p className={css.abstract}>{paper.abstract || 'Esta fuente no entregó el abstract.'}</p>

          <div className={css.seccion}>Identificadores</div>
          <dl className={css.ids}>
            <dt>DOI</dt>
            <dd>{paper.doi ? <a href={url} target="_blank" rel="noopener noreferrer">{doiCorto(paper.doi)}</a> : '—'}</dd>
            <dt>OpenAlex</dt>
            <dd className={css.codigo}>{paper.openalex_id ? String(paper.openalex_id).replace('https://openalex.org/', '') : '—'}</dd>
            <dt>Motor de búsqueda</dt>
            <dd>{motoresDe(paper).map(nombreMotor).join(', ') || '—'}</dd>
            <dt>Motor PDF</dt>
            <dd>{motorPdf}</dd>
            <dt>Página de origen</dt>
            <dd>{origen || '—'}</dd>
          </dl>

          <div className={css.seccion}>Cadena coincidente{coincidentes.length ? ` · ${coincidentes.map((n) => `C${n}`).join(', ')}` : ''}</div>
          <div className={css.cadenas}>
            {coincidentes.length
              ? coincidentes.map((n) => <div className={css.cadena} key={n}>{proyecto.queries[n - 1]}</div>)
              : <div className={css.cadena}>{paper.matched_query || '—'}</div>}
          </div>
        </div>

        <div className={css.pie}>
          {url
            ? <a className={`btn btn-primary ${css.abrir}`} href={url} target="_blank" rel="noopener noreferrer">
                <ExternalLink size={15} strokeWidth={2.75} />Abrir original
              </a>
            : <button className="btn btn-primary" disabled><ExternalLink size={15} strokeWidth={2.75} />Abrir original</button>}
          <button className="btn btn-secondary" onClick={() => alternarSeleccion(paper.id)}>
            {marcado ? '★ Quitar de selección' : '☆ Añadir a selección'}
          </button>
        </div>
      </aside>
    </>
  );
}
