'use client';

import { useEffect } from 'react';
import { X } from 'lucide-react';
import { useApp } from '@/context/AppContext';
import { plural } from '@/lib/formato';
import css from './DialogoCadenas.module.css';

interface Props {
  conteos: number[];                 // papers encontrados por cada cadena (mismo orden que queries)
  cerrar: () => void;
  filtrar: (indice: number) => void; // 1-based: muestra en la tabla solo los papers de esa cadena
}

// Ventana sobre la pestaña de búsqueda (con el fondo difuminado) con las cadenas
// que se usaron, la intención de cada una y cuántos papers trajo.
export function DialogoCadenas({ conteos, cerrar, filtrar }: Props) {
  const { proyecto } = useApp();

  useEffect(() => {
    const alPulsar = (e: KeyboardEvent) => { if (e.key === 'Escape') cerrar(); };
    window.addEventListener('keydown', alPulsar);
    return () => window.removeEventListener('keydown', alPulsar);
  }, [cerrar]);

  if (!proyecto) return null;
  const intencion = proyecto.intencion_cadenas ?? {};
  const general = intencion.intencion_consolidada || proyecto.intencion_busqueda || '';
  const detalles = intencion.detalles ?? [];
  const obligatorios = proyecto.obligatorios ?? [];

  return (
    <div className={css.fondo} onClick={cerrar}>
      <div className={css.ventana} role="dialog" aria-modal="true" aria-labelledby="cadenas-titulo" onClick={(e) => e.stopPropagation()}>
        <div className={css.cabecera}>
          <h3 id="cadenas-titulo">Cadenas de esta búsqueda</h3>
          <button className="btn btn-icon" aria-label="Cerrar" autoFocus onClick={cerrar}><X size={16} strokeWidth={2.75} /></button>
        </div>

        {general && <p className={css.general}><strong>Intención de búsqueda:</strong> {general}</p>}
        {obligatorios.length > 0 && (
          <div className={css.obligatorios}>
            <strong>Términos obligatorios:</strong>
            {obligatorios.map((o) => <span key={o.termino} title={o.alternativas.join(' OR ')}>{o.termino}</span>)}
          </div>
        )}

        <ol className={css.lista}>
          {proyecto.queries.map((cadena, i) => {
            const det = detalles.find((d) => d && d.cadena === cadena) ?? detalles[i];
            const n = conteos[i] ?? 0;
            return (
              <li className={css.cadena} key={i}>
                <div className={css.fila}>
                  <span className={css.numero}>{i + 1}</span>
                  <code className={css.texto}>{cadena}</code>
                </div>
                {det?.intencion && <p className={css.intencion}>{det.intencion}</p>}
                {det?.alcance && <p className={css.alcance}><strong>Enfoque:</strong> {det.alcance}</p>}
                <div className={css.pie}>
                  <span>{plural(n, 'paper encontrado', 'papers encontrados')}</span>
                  <button className="btn btn-ghost" disabled={!n} onClick={() => { filtrar(i + 1); cerrar(); }}>Ver sus papers →</button>
                </div>
              </li>
            );
          })}
        </ol>
        <p className={css.nota}>Un paper puede haber salido en varias cadenas: por eso la suma puede superar el total.</p>
      </div>
    </div>
  );
}
