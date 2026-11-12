'use client';

import { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { doiCorto, doiUrl, ETIQUETA_RELEVANCIA, fuenteFicha } from '@/lib/formato';
import type { Ficha } from '@/lib/tipos';
import css from './FichaItem.module.css';

interface Props {
  ficha: Ficha;
  abierta: boolean;
  alternar: () => void;
}

type Seccion = 'esencial' | 'metodo' | 'original';

// Cerrada, la ficha muestra solo lo necesario para decidir si interesa: título,
// relevancia con su motivo y una frase. Abierta, el detalle se reparte en
// solapas para no mostrar todo a la vez; el texto original va al final.
export function FichaItem({ ficha: f, abierta, alternar }: Props) {
  const [seccion, setSeccion] = useState<Seccion>('esencial');
  const parcial = f.cobertura === 'parcial';
  const apagada = f.relevancia === 'nula';
  const m = f.metodo ?? { tipo_estudio: null, poblacion: null, contexto: null };
  const hayMetodo = !!(m.tipo_estudio || m.poblacion || m.contexto);
  const hayIntro = !!(f.intro_penultimo || f.intro_ultimo);

  const secciones: { clave: Seccion; etiqueta: string; hay: boolean }[] = [
    { clave: 'esencial', etiqueta: 'Lo esencial', hay: !!(f.aporte_al_tema || f.objetivo || f.hallazgos_clave.length) },
    { clave: 'metodo', etiqueta: 'Método y conclusiones',
      hay: hayMetodo || f.conclusiones.length > 0 || f.limitaciones.length > 0 || f.tablas.length > 0 },
    { clave: 'original', etiqueta: 'Texto original', hay: !!(f.abstract || hayIntro || f.conclusion_texto) },
  ];
  const disponibles = secciones.filter((s) => s.hay);
  const activa = disponibles.some((s) => s.clave === seccion) ? seccion : disponibles[0]?.clave;

  return (
    <article className={`${css.ficha} ${apagada ? css.fichaApagada : ''}`}>
      <button className={css.cabecera} onClick={alternar} aria-expanded={abierta}>
        <div style={{ minWidth: 0 }}>
          <div className={css.meta}>
            <span className={`${css.relevancia} ${css[`rel_${f.relevancia}`]}`}>{ETIQUETA_RELEVANCIA[f.relevancia]}</span>
            {f.year && <span>{f.year}</span>}
            {parcial && <span title="No se pudo leer el PDF: la ficha sale solo del abstract">· solo abstract</span>}
          </div>
          <div className={`${css.titulo} ${apagada ? css.apagado : ''}`}>{f.title || '(sin título)'}</div>
          <div className={css.frase}>{f.en_una_frase || 'Sin resumen.'}</div>
          {f.motivo_relevancia && <div className={css.motivo}><b>Por qué:</b> {f.motivo_relevancia}</div>}
        </div>
        <span className={`${css.caret} ${abierta ? css.girado : ''}`}><ChevronDown size={16} strokeWidth={2.75} /></span>
      </button>

      {abierta && (
        <div className={css.cuerpo}>
          <div className={css.solapas} role="tablist">
            {disponibles.map((s) => (
              <button key={s.clave} role="tab" aria-selected={activa === s.clave}
                className={`${css.solapa} ${activa === s.clave ? css.solapaActiva : ''}`} onClick={() => setSeccion(s.clave)}>
                {s.etiqueta}
              </button>
            ))}
            <span className={css.espacio} />
            {f.doi && <a className={css.enlace} href={doiUrl(f.doi)} target="_blank" rel="noopener noreferrer">doi:{doiCorto(f.doi)}</a>}
          </div>

          {activa === 'esencial' && (
            <div className={css.panel}>
              {f.aporte_al_tema && (
                <div className={css.aporte}>
                  <div className={css.rotulo}>Qué aporta a tu tema</div>
                  <p>{f.aporte_al_tema}</p>
                </div>
              )}
              {f.objetivo && (
                <div>
                  <div className={css.rotulo}>Objetivo del estudio</div>
                  <p className={css.texto}>{f.objetivo}</p>
                </div>
              )}
              {f.hallazgos_clave.length > 0 && (
                <div>
                  <div className={css.rotulo}>Hallazgos clave</div>
                  <div className={css.hallazgos}>
                    {f.hallazgos_clave.map((h, i) => (
                      <div className={css.hallazgo} key={i}><b>{i + 1}</b><span>{h}</span></div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {activa === 'metodo' && (
            <div className={css.panel}>
              {hayMetodo && (
                <dl className={css.metodo}>
                  {m.tipo_estudio && <><dt>Tipo de estudio</dt><dd>{m.tipo_estudio}</dd></>}
                  {m.poblacion && <><dt>Muestra o datos</dt><dd>{m.poblacion}</dd></>}
                  {m.contexto && <><dt>Contexto</dt><dd>{m.contexto}</dd></>}
                </dl>
              )}
              {f.conclusiones.length > 0 && (
                <div>
                  <div className={css.rotulo}>Conclusiones de los autores</div>
                  <ul className={css.puntos}>{f.conclusiones.map((c, i) => <li key={i}>{c}</li>)}</ul>
                </div>
              )}
              {f.limitaciones.length > 0 && (
                <div>
                  <div className={css.rotulo}>Limitaciones declaradas</div>
                  <ul className={css.puntos}>{f.limitaciones.map((c, i) => <li key={i}>{c}</li>)}</ul>
                </div>
              )}
              {f.tablas.length > 0 && (
                <details className={css.desplegable}>
                  <summary>Tablas del paper ({f.tablas.length})</summary>
                  <div className={css.tablas}>
                    {f.tablas.map((t, i) => (
                      <div className={css.tabla} key={i}>
                        <strong>{t.nombre}</strong>
                        {t.que_aporta && <p>{t.que_aporta}</p>}
                        {t.atributos.length > 0 && (
                          <div className={css.atributos}>{t.atributos.map((a, j) => <span className="tag tag-neutral" key={j}>{a}</span>)}</div>
                        )}
                      </div>
                    ))}
                  </div>
                </details>
              )}
            </div>
          )}

          {activa === 'original' && (
            <div className={css.panel}>
              <p className={css.nota}>
                Fragmentos tal como aparecen en el paper{parcial ? '' : ` (leído con ${fuenteFicha(f)})`}, sin pasar por el modelo.
              </p>
              {f.abstract && (
                <details className={css.desplegable} open>
                  <summary>Abstract</summary>
                  <p className={css.texto}>{f.abstract}</p>
                </details>
              )}
              {hayIntro && (
                <details className={css.desplegable}>
                  <summary>Final de la introducción</summary>
                  {f.intro_penultimo && <p className={css.texto}>{f.intro_penultimo}</p>}
                  {f.intro_ultimo && <p className={css.texto}>{f.intro_ultimo}</p>}
                </details>
              )}
              {f.conclusion_texto && (
                <details className={css.desplegable}>
                  <summary>Conclusiones</summary>
                  <p className={css.texto}>{f.conclusion_texto}</p>
                </details>
              )}
            </div>
          )}

          {parcial && (
            <p className={css.nota}>
              Ficha parcial: no hubo PDF accesible, así que se armó solo con el abstract (sin introducción, conclusiones ni tablas).
            </p>
          )}
        </div>
      )}
    </article>
  );
}
