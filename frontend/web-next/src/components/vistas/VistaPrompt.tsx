'use client';

import { useApp } from '@/context/AppContext';
import type { Idioma } from '@/lib/tipos';
import { Aclaracion } from './Aclaracion';
import { PromptBloqueado } from './PromptBloqueado';
import css from './VistaPrompt.module.css';

const IDIOMAS: { valor: Idioma; etiqueta: string }[] = [
  { valor: 'en', etiqueta: 'Inglés' }, { valor: 'ambos', etiqueta: 'Ambos' }, { valor: 'es', etiqueta: 'Español' },
];
const MAX_CADENAS = 12;

export function VistaPrompt() {
  const { proyecto, campos, editarPrompt, guardarCampos, generar, ocupado, aclaracion } = useApp();

  if (aclaracion.acl.fase === 'preguntando') return <Aclaracion />;
  if (proyecto?.tema_refinado) return <PromptBloqueado />;

  const cambiarNum = (n: number) => {
    const num = Math.max(1, Math.min(MAX_CADENAS, n));
    editarPrompt({ num });
    guardarCampos({ num });
  };

  return (
    <section className={`${css.seccion} fade-in`}>
      <div className={css.circulo1} />
      <div className={css.circulo2} />
      <div className={css.contenido}>
        <div className="kicker">Paso 1 · Tema</div>
        <h2 className={css.titulo}>¿Qué quieres investigar?</h2>
        <p className={css.intro}>
          Descríbelo con tus palabras. Nemotron revisará si el tema es lo bastante concreto y, si hace falta,
          te hará hasta dos rondas de preguntas.
        </p>
        <textarea className={`input ${css.texto}`} aria-label="Tema a investigar" autoFocus value={campos.prompt}
          placeholder="Ej.: modelos de aprendizaje automático para predecir la deserción universitaria…"
          onChange={(e) => editarPrompt({ prompt: e.target.value })}
          onBlur={(e) => guardarCampos({ prompt: e.target.value })} />

        <div className={css.controles}>
          <div className="field">
            <label>Nº de cadenas</label>
            <div className={css.contador}>
              <button className="btn btn-icon" aria-label="Menos cadenas" onClick={() => cambiarNum(campos.num - 1)}>−</button>
              <span>{campos.num}</span>
              <button className="btn btn-icon" aria-label="Más cadenas" onClick={() => cambiarNum(campos.num + 1)}>+</button>
            </div>
          </div>
          <div className="field">
            <label>Idioma de las cadenas</label>
            <div className={`seg ${css.segmento}`}>
              {IDIOMAS.map(({ valor, etiqueta }) => (
                <label className="seg-opt" key={valor}>
                  <input type="radio" name="idioma" checked={campos.idioma === valor}
                    onChange={() => { editarPrompt({ idioma: valor }); guardarCampos({ idioma: valor }); }} />
                  {etiqueta}
                </label>
              ))}
            </div>
          </div>
          <div className={css.espacio} />
          <button className={`btn btn-primary ${css.generar}`} onClick={generar} disabled={ocupado}>
            {ocupado ? 'Evaluando el tema…' : 'Generar cadenas →'}
          </button>
        </div>

        <p className={css.nota}>
          Puedes escribir el tema en español: las cadenas se traducen. Casi toda la literatura indexada está en inglés;
          «Ambos» añade los términos en español y «Español» solo encuentra una fracción pequeña de los papers.
        </p>
      </div>
    </section>
  );
}
