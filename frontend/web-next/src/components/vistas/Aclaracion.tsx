'use client';

import { X } from 'lucide-react';
import { useApp } from '@/context/AppContext';
import css from './Aclaracion.module.css';

// Ronda de preguntas de Nemotron cuando el tema es muy general
export function Aclaracion() {
  const { proyecto, campos, aclaracion, responderAclaracion, omitirAclaracion, ocupado } = useApp();
  const { acl, responder, agregarEjemplo, agregarPropia, editarPropia, quitarPropia, reiniciar } = aclaracion;

  return (
    <section className={`${css.seccion} fade-in`}>
      <div className="kicker">Paso 1 · Tema</div>
      <div className={css.cita}>
        <span className={css.comilla}>“</span>
        <p>{proyecto?.prompt ?? campos.prompt}</p>
      </div>

      <div className={css.tarjeta}>
        <div className={css.titulo}>
          <h3>Afinemos el tema</h3>
          <span className={`tag ${css.ronda}`}>ronda {acl.ronda} de 2</span>
        </div>
        <p className={css.ayuda}>El tema es amplio. Responde lo que puedas; las respuestas vacías se ignoran.</p>

        <div className={css.preguntas}>
          {acl.preguntas.map((q, i) => (
            <div className={css.pregunta} key={i}>
              <span className={css.numero}>{i + 1}</span>
              <div>
                <label className={css.enunciado} htmlFor={`acl-${i}`} style={{ display: 'block' }}>{q.pregunta}</label>
                <input id={`acl-${i}`} className={`input ${css.campo}`} value={acl.respuestas[i] ?? ''}
                  placeholder="Tu respuesta (puedes dejarla vacía)" onChange={(e) => responder(i, e.target.value)} />
                {!!q.ejemplos?.length && (
                  <div className={css.chips}>
                    {q.ejemplos.map((ej) => (
                      <button key={ej} type="button" onClick={() => agregarEjemplo(i, ej)}
                        className={`${css.chip} ${(acl.respuestas[i] ?? '').split(', ').includes(ej) ? css.chipOn : ''}`}>{ej}</button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}

          {acl.custom.map((c, i) => (
            <div className={css.propia} key={`propia-${i}`}>
              <span className={css.mas}>+</span>
              <input className={`input ${css.campo}`} value={c.pregunta} placeholder="Tu pregunta" aria-label="Pregunta propia"
                onChange={(e) => editarPropia(i, 'pregunta', e.target.value)} />
              <input className={`input ${css.campo}`} value={c.respuesta} placeholder="Tu respuesta" aria-label="Respuesta a la pregunta propia"
                onChange={(e) => editarPropia(i, 'respuesta', e.target.value)} />
              <button className={`btn btn-icon ${css.quitar}`} aria-label="Quitar pregunta propia" onClick={() => quitarPropia(i)}>
                <X size={14} strokeWidth={2.75} />
              </button>
            </div>
          ))}

          <button className={`btn btn-ghost ${css.fantasma} ${css.agregar}`} onClick={agregarPropia}>+ Añadir pregunta propia</button>
        </div>

        <div className={css.acciones}>
          <button className={`btn btn-primary ${css.continuar}`} onClick={responderAclaracion} disabled={ocupado}>
            {ocupado ? 'Evaluando…' : 'Continuar →'}
          </button>
          <button className={`btn btn-secondary ${css.omitir}`} onClick={omitirAclaracion} disabled={ocupado}>Omitir</button>
          <div className={css.espacio} />
          <button className={`btn btn-ghost ${css.fantasma}`} onClick={reiniciar} disabled={ocupado}>Editar prompt</button>
        </div>
      </div>
    </section>
  );
}
