'use client';

import { useApp } from '@/context/AppContext';
import css from './TarjetaEnCurso.module.css';

export function TarjetaEnCurso() {
  const { proyecto, cancelarProcesamiento } = useApp();
  if (!proyecto) return null;
  const p = proyecto.procesamiento;
  const pct = p.total ? Math.round((p.hechos / p.total) * 100) : 0;

  return (
    <div className={css.tarjeta}>
      <div className={css.titulo}>
        <h3>Leyendo papers</h3>
        <span className={css.fraccion}>{p.hechos} / {p.total}</span>
      </div>
      <div className={css.barra} role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <div className={css.relleno} style={{ width: `${pct}%` }} />
      </div>
      <div className={css.ahora}><span>Ahora</span><span>{p.actual || '—'}</span></div>
      <div className={css.registro}>
        {p.mensajes.slice(-6).map((m, i) => <div key={`${p.mensajes.length}-${i}`}>{m}</div>)}
      </div>
      <div className={css.pie}>
        <button className="btn btn-secondary" onClick={cancelarProcesamiento}>Cancelar</button>
        <span className={css.nota}>Lo ya extraído queda guardado. Puedes cambiar de pestaña: se actualiza solo.</span>
      </div>
    </div>
  );
}
