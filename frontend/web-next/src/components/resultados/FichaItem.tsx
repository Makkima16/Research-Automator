'use client';

import { ChevronDown } from 'lucide-react';
import { doiCorto, doiUrl, fuenteFicha } from '@/lib/formato';
import type { Ficha } from '@/lib/tipos';
import css from './FichaItem.module.css';

interface Props {
  ficha: Ficha;
  abierta: boolean;
  alternar: () => void;
}

export function FichaItem({ ficha: f, abierta, alternar }: Props) {
  const parcial = f.cobertura === 'parcial';
  const noRelevante = f.estado === 'no_relevante';
  const hayIntro = !!(f.intro_penultimo || f.intro_ultimo);

  return (
    <article className={css.ficha}>
      <button className={css.cabecera} onClick={alternar} aria-expanded={abierta}>
        <div style={{ minWidth: 0 }}>
          <div className={`${css.titulo} ${noRelevante ? css.apagado : ''}`}>{f.title || '(sin título)'}</div>
          <div className={css.meta}>
            {f.year && <span>{f.year}</span>}
            {f.year && f.doi && <span>·</span>}
            {f.doi && (
              <a href={doiUrl(f.doi)} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}>doi:{doiCorto(f.doi)}</a>
            )}
            {parcial
              ? <span className="tag tag-accent" style={{ background: 'var(--color-accent-200)', marginLeft: 6 }}
                  title="No se pudo leer el PDF: la ficha sale solo del abstract">solo abstract</span>
              : <span className="tag tag-accent-2" style={{ marginLeft: 6 }}>{fuenteFicha(f)}</span>}
            {noRelevante && <span className="tag tag-neutral" style={{ background: 'var(--color-neutral-300)' }}>no relevante</span>}
          </div>
          <div className={css.resumen}>{f.resumen || 'Sin resumen.'}</div>
        </div>
        <span className={`${css.caret} ${abierta ? css.girado : ''}`}><ChevronDown size={16} strokeWidth={2.75} /></span>
      </button>

      {abierta && (
        <div className={css.cuerpo}>
          {f.objetivo && (
            <div className={`${css.ancho} ${css.objetivo}`}>
              <div className={css.rotulo}>Objetivo</div>
              <p>{f.objetivo}</p>
            </div>
          )}
          {f.abstract && (
            <div className={css.ancho}>
              <div className={css.rotulo}>Abstract</div>
              <p className={css.texto}>{f.abstract}</p>
            </div>
          )}
          {hayIntro && (
            <div className={css.ancho}>
              <div className={css.rotulo}>Introducción</div>
              <div className={css.bloques}>
                {f.intro_penultimo && <div className={css.bloque}><small>Penúltimo párrafo</small><div>{f.intro_penultimo}</div></div>}
                {f.intro_ultimo && <div className={css.bloque}><small>Último párrafo</small><div>{f.intro_ultimo}</div></div>}
              </div>
            </div>
          )}
          {(f.conclusion_texto || f.conclusiones.length > 0) && (
            <div>
              <div className={css.rotulo} style={{ marginBottom: 8 }}>Conclusiones</div>
              {f.conclusion_texto && <div className={css.bloque}><small>Texto del paper</small><div>{f.conclusion_texto}</div></div>}
              {f.conclusiones.length > 0 && (
                <>
                  <div className={css.sub}>Resumidas</div>
                  <ul className={css.puntos}>{f.conclusiones.map((c, i) => <li key={i}>{c}</li>)}</ul>
                </>
              )}
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
          {f.tablas.length > 0 && (
            <div className={css.ancho}>
              <div className={css.rotulo}>Tablas ({f.tablas.length})</div>
              <div className={css.tablas}>
                {f.tablas.map((t, i) => (
                  <div className={css.tabla} key={i}>
                    <strong>{t.nombre}</strong>
                    {t.atributos.length > 0 && <div className={css.atributos}>{t.atributos.map((a) => <span className="tag tag-neutral" key={a}>{a}</span>)}</div>}
                    {t.que_aporta && <p>{t.que_aporta}</p>}
                  </div>
                ))}
              </div>
            </div>
          )}
          {parcial && (
            <p className={`${css.ancho} ${css.nota}`}>
              Ficha parcial: no hubo PDF accesible, así que solo tiene el abstract (sin introducción, conclusiones ni tablas).
            </p>
          )}
        </div>
      )}
    </article>
  );
}
