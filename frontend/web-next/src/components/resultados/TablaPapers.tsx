'use client';

import { useApp } from '@/context/AppContext';
import { cadenasDe, doiCorto, doiUrl, motoresDe, nombreMotor, paginaOrigen } from '@/lib/formato';
import type { Paper } from '@/lib/tipos';
import css from './TablaPapers.module.css';

interface Props {
  filas: Paper[];
  panelId: string | null;
  abrir: (id: string) => void;
  vacio: string;
}

export function TablaPapers({ filas, panelId, abrir, vacio }: Props) {
  const { proyecto, alternarSeleccion } = useApp();
  if (!proyecto) return null;
  const marcados = new Set(proyecto.seleccion);

  return (
    <div className={css.contenedor}>
      <table className={`table ${css.tabla}`}>
        <thead>
          <tr>
            <th style={{ width: 44, paddingLeft: 18 }} />
            <th style={{ padding: '14px 8px' }}>Título / fuente</th>
            <th>Año</th>
            <th style={{ textAlign: 'right' }}>Citas</th>
            <th>OA</th>
            <th>DOI</th>
            <th title="Motor de búsqueda que encontró el paper">Encontrado en</th>
            <th title="Dominio de la página donde está el texto del paper">Página de origen</th>
            <th>Cadena</th>
            <th>Abstract</th>
          </tr>
        </thead>
        <tbody>
          {filas.map((p) => {
            const origen = paginaOrigen(p);
            const cadenas = cadenasDe(p, proyecto.queries);
            const marcado = marcados.has(p.id);
            return (
              <tr key={p.id} className={`${css.fila} ${panelId === p.id ? css.abierta : ''}`} onClick={() => abrir(p.id)}>
                <td style={{ paddingLeft: 18 }}>
                  <button className={`${css.estrella} ${marcado ? css.marcada : ''}`} title="Selección"
                    aria-label={marcado ? 'Quitar de la selección' : 'Añadir a la selección'} aria-pressed={marcado}
                    onClick={(e) => { e.stopPropagation(); alternarSeleccion(p.id); }}>★</button>
                </td>
                <td className={css.titulo}>
                  <strong>{p.title || '(sin título)'}</strong>
                  <div className={css.fuente}>{p.source}</div>
                </td>
                <td>{p.year}</td>
                <td className={css.citas}>{p.cited_by_count ?? 0}</td>
                <td>{p.is_oa ? <span className="tag tag-accent-2" style={{ background: 'var(--color-accent-2-200)' }}>OA</span> : <span className={css.sin}>—</span>}</td>
                <td>
                  {p.doi
                    ? <a className={css.doi} href={doiUrl(p.doi)} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}>{doiCorto(p.doi)}</a>
                    : <span className={css.sin}>—</span>}
                </td>
                <td><div className={css.motores}>{motoresDe(p).map((m) => <span key={m} className="tag tag-neutral">{nombreMotor(m)}</span>)}</div></td>
                <td className={css.origen} title={p.pdf_url || p.oa_url || ''}>{origen || <span className={css.sin}>—</span>}</td>
                <td>
                  {cadenas.length
                    ? <div className={css.cadenas}>{cadenas.map((n) => <span key={n} className={css.cadena}>C{n}</span>)}</div>
                    : <span className={css.sin} title={p.matched_query}>—</span>}
                </td>
                <td className={css.abstract}><div>{p.abstract}</div></td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {filas.length === 0 && <div className={css.vacio}>{vacio}</div>}
    </div>
  );
}
