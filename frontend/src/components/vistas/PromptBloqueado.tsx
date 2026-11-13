'use client';

import { useApp } from '@/context/AppContext';
import { EntradaTerminos } from '../ui/EntradaTerminos';
import css from './PromptBloqueado.module.css';

// Prompt ya usado para generar cadenas: se muestra de solo lectura con sus preguntas y respuestas
export function PromptBloqueado() {
  const { proyecto, volverACadenas, rehacerPrompt, regenerarCadenas, editarPrompt, guardarCampos, ocupado } = useApp();
  if (!proyecto) return null;
  const aclaraciones = proyecto.aclaraciones ?? [];
  const intencion = proyecto.intencion_cadenas?.intencion_consolidada || proyecto.intencion_busqueda || proyecto.tema_refinado || '';

  return (
    <section className={`${css.seccion} fade-in`}>
      <div className={css.cabecera}>
        <span className="kicker">Paso 1 · Tema</span>
        <span className={`tag tag-neutral ${css.solo}`}>Prompt usado · solo lectura</span>
      </div>
      <div className={css.prompt}><p>{proyecto.prompt}</p></div>

      <div className={css.rejilla}>
        <div className={css.caja}>
          <h4>Aclaraciones</h4>
          {aclaraciones.length ? (
            <div className={css.lista}>
              {aclaraciones.map((a, i) => (
                <div key={i}>
                  <div className={css.pregunta}>{a.pregunta}</div>
                  <div className={`${css.respuesta} ${a.respuesta ? '' : css.sinRespuesta}`}>{a.respuesta || 'Sin respuesta'}</div>
                </div>
              ))}
            </div>
          ) : (
            <p className={css.vacio}>Este prompt no necesitó preguntas de aclaración.</p>
          )}
        </div>
        {intencion && (
          <div className={`${css.caja} ${css.cajaVerde}`}>
            <h4>Intención detectada</h4>
            <p>{intencion}</p>
          </div>
        )}
      </div>

      <div className={css.caja} style={{ marginTop: 14 }}>
        <h4>Términos obligatorios</h4>
        <EntradaTerminos valores={proyecto.terminos_clave ?? []} maximo={5} etiqueta="Términos obligatorios"
          placeholder="Ej.: mujeres · Enter para añadir"
          cambiar={(terminos_clave) => { editarPrompt({ terminos_clave }); guardarCampos({ terminos_clave }); }} />
        <p className={css.vacio} style={{ marginTop: 8 }}>
          Aparecen en todas las cadenas. Si los cambias, pulsa «Regenerar cadenas» para aplicarlos.
        </p>
      </div>

      <div className={css.acciones}>
        <button className={`btn btn-primary ${css.ver}`} onClick={volverACadenas}>Ver cadenas →</button>
        <button className="btn btn-secondary" onClick={regenerarCadenas} disabled={ocupado}>
          {ocupado ? 'Generando…' : 'Regenerar cadenas'}
        </button>
        <button className="btn btn-secondary" onClick={rehacerPrompt}>Rehacer prompt</button>
      </div>
    </section>
  );
}
