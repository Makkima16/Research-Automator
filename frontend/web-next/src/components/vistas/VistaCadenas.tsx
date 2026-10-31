'use client';

import { useState } from 'react';
import { ChevronDown, Trash2 } from 'lucide-react';
import { useApp } from '@/context/AppContext';
import css from './VistaCadenas.module.css';

export function VistaCadenas() {
  const {
    proyecto, editarCadenas, guardarCadenas, editarParametro, guardarParametro,
    volverAlPrompt, volverAResultados, buscar,
  } = useApp();
  const [abiertas, setAbiertas] = useState<Set<number>>(new Set());
  if (!proyecto) return null;

  const { queries } = proyecto;
  const intencion = proyecto.intencion_cadenas ?? {};
  const intencionTexto = intencion.intencion_consolidada || proyecto.intencion_busqueda || '';
  const detalles = intencion.detalles ?? [];

  const alternar = (i: number) => setAbiertas((s) => {
    const nuevo = new Set(s);
    if (!nuevo.delete(i)) nuevo.add(i);
    return nuevo;
  });

  const cambiarTexto = (i: number, texto: string) => editarCadenas(queries.map((q, j) => (j === i ? texto : q)));

  const quitar = (i: number) => {
    const resto = queries.filter((_, j) => j !== i);
    editarCadenas(resto);
    setAbiertas(new Set());
    guardarCadenas(resto);
  };

  const agregar = () => {
    const nuevas = [...queries, ''];
    editarCadenas(nuevas);
    guardarCadenas(nuevas);
    requestAnimationFrame(() => {
      const campos = document.querySelectorAll<HTMLInputElement>('[data-cadena]');
      campos[campos.length - 1]?.focus();
    });
  };

  return (
    <section className={`${css.seccion} fade-in`}>
      <div className="kicker">Paso 2 · Cadenas booleanas</div>
      <h2 className={css.titulo}>Revisa y ajusta las cadenas</h2>
      <p className={`lead ${css.intro}`}>
        Cada cadena se envía tal cual a OpenAlex, Semantic Scholar y Scopus. Puedes editarlas, quitarlas o añadir las tuyas.
      </p>
      {intencionTexto && <p className={css.intencion}><strong>Intención de búsqueda:</strong> {intencionTexto}</p>}

      <div className={css.lista}>
        {queries.map((texto, i) => {
          const det = detalles.find((d) => d && d.cadena === texto) ?? detalles[i];
          const hayIntencion = !!det?.intencion;
          const abierta = abiertas.has(i);
          return (
            <div className={css.cadena} key={i}>
              <div className={css.fila}>
                <span className={css.numero}>{i + 1}</span>
                <input className={`input ${css.texto}`} data-cadena value={texto} spellCheck={false} aria-label={`Cadena ${i + 1}`}
                  onChange={(e) => cambiarTexto(i, e.target.value)}
                  onBlur={() => guardarCadenas(queries)}
                  onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur(); }} />
                {hayIntencion ? (
                  <button className={`btn btn-secondary ${css.intencionBtn} ${abierta ? css.abierto : ''}`} aria-expanded={abierta}
                    onClick={() => alternar(i)}>
                    Intención<ChevronDown size={14} strokeWidth={2.75} />
                  </button>
                ) : <span className={css.sinIntencion} />}
                <button className={`btn btn-icon ${css.borrar}`} title="Eliminar cadena" aria-label={`Eliminar cadena ${i + 1}`} onClick={() => quitar(i)}>
                  <Trash2 size={15} strokeWidth={2.75} />
                </button>
              </div>
              {hayIntencion && abierta && (
                <div className={css.detalle}>
                  {det?.intencion}
                  {det?.alcance && <><br /><strong>Alcance:</strong> {det.alcance}</>}
                </div>
              )}
            </div>
          );
        })}
        <button className={`btn btn-ghost ${css.agregar}`} onClick={agregar}>+ añadir cadena</button>
      </div>

      <div className={css.parametros}>
        <div className="field" style={{ width: 150 }}>
          <label htmlFor="min-year">Año mínimo</label>
          <input id="min-year" className="input" type="number" min={1900} max={2100} placeholder="sin límite"
            value={proyecto.min_year ?? ''} onChange={(e) => editarParametro('min_year', e.target.value)}
            onBlur={() => guardarParametro('min_year')} />
        </div>
        <div className="field" style={{ width: 170 }}>
          <label htmlFor="max-res">Resultados por cadena</label>
          <input id="max-res" className="input" type="number" min={1} max={500}
            value={proyecto.max_resultados ?? ''} onChange={(e) => editarParametro('max_resultados', e.target.value)}
            onBlur={() => guardarParametro('max_resultados')} />
        </div>
        <p className={css.nota}>
          El tope aplica a cada cadena en cada plataforma. Los papers sin PDF abierto se buscarán en Sci-Hub por DOI.
        </p>
      </div>

      <div className={css.acciones}>
        <button className="btn btn-secondary" onClick={volverAlPrompt}>← Volver al prompt</button>
        {proyecto.papers.length > 0 && (
          <button className="btn btn-ghost" onClick={volverAResultados}>Ver resultados anteriores ({proyecto.papers.length})</button>
        )}
        <div className={css.espacio} />
        <button className={`btn btn-primary ${css.iniciar}`} onClick={buscar}>Iniciar búsqueda →</button>
      </div>
    </section>
  );
}
