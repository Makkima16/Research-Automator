'use client';

import { Check } from 'lucide-react';
import { useApp } from '@/context/AppContext';
import css from './VistaBusqueda.module.css';

// El servidor manda cada paso como "Fuente — detalle"; la vista separa las dos partes
function partir(texto: string): [string, string] {
  const i = texto.indexOf(' — ');
  return i === -1 ? [texto, ''] : [texto.slice(0, i), texto.slice(i + 3)];
}

export function VistaBusqueda() {
  const { proyecto, cancelarBusqueda } = useApp();
  if (!proyecto) return null;

  const pasos = proyecto.progreso;
  const hechos = pasos.filter((p) => p.estado === 'done').length;
  const activos = pasos.filter((p) => p.estado === 'active').length;
  const pct = pasos.length ? Math.round(((hechos + activos * 0.5) / pasos.length) * 100) : 0;

  return (
    <section className={`${css.seccion} fade-in`}>
      <div className="kicker">Paso 3 · Búsqueda</div>
      <h2 className={css.titulo}>Buscando en las bases…</h2>
      <p className="lead" style={{ marginTop: -10 }}>
        Consultando {proyecto.queries.length} {proyecto.queries.length === 1 ? 'cadena' : 'cadenas'} en varias fuentes. Esto puede tardar unos minutos.
      </p>

      <div className={css.tarjeta}>
        <div>
          {pasos.map((paso, i) => {
            const [etiqueta, detalle] = partir(paso.texto);
            const hecho = paso.estado === 'done';
            const activo = paso.estado === 'active';
            const anteriorHecho = i === 0 || pasos[i - 1].estado === 'done';
            return (
              <div className={css.paso} key={i}>
                <div className={css.riel}>
                  {i > 0 && <span className={`${css.linea} ${css.arriba}`}
                    style={{ background: anteriorHecho ? 'var(--color-accent-2-400)' : 'var(--color-neutral-300)' }} />}
                  {i < pasos.length - 1 && <span className={`${css.linea} ${css.abajo}`}
                    style={{ background: hecho ? 'var(--color-accent-2-400)' : 'var(--color-neutral-300)' }} />}
                  {hecho && <span className={css.hecho}><Check size={13} strokeWidth={3.2} /></span>}
                  {activo && <span className={css.activo} />}
                  {!hecho && !activo && <span className={css.pendiente} />}
                </div>
                <span className={css.etiqueta} style={{ color: hecho || activo ? 'var(--color-text)' : 'var(--color-neutral-600)' }}>{etiqueta}</span>
                <span className={css.detalle}>{activo && !detalle ? 'en curso…' : detalle}</span>
              </div>
            );
          })}
        </div>
        <div className={css.barraFila}>
          <div className={css.barra}><div className={css.relleno} style={{ width: `${pct}%` }} /></div>
          <span className={css.porcentaje}>{pct}%</span>
        </div>
      </div>

      <button className={`btn btn-secondary ${css.cancelar}`} onClick={cancelarBusqueda}>Cancelar búsqueda</button>
    </section>
  );
}
