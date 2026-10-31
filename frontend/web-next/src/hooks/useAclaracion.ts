// Ronda de aclaración del tema: Nemotron pregunta cuando el prompt es muy general.
// El estado vive en una ref además de en React para que los flujos async lean
// siempre el valor más reciente.
import { useCallback, useRef, useState } from 'react';
import type { Aclaracion, EntradaHistorial, PreguntaAclaracion } from '@/lib/tipos';

export interface EstadoAclaracion {
  fase: null | 'preguntando';
  preguntas: PreguntaAclaracion[];
  respuestas: string[];
  historial: EntradaHistorial[];  // lo que se le manda a Nemotron en la ronda siguiente
  ronda: number;
  tema: string;                   // tema refinado que propone Nemotron
  custom: Aclaracion[];           // preguntas propias del usuario
  vistas: Aclaracion[];           // todas las preguntas mostradas (con o sin respuesta), para revisarlas luego
}

const INICIAL: EstadoAclaracion = {
  fase: null, preguntas: [], respuestas: [], historial: [], ronda: 0, tema: '', custom: [], vistas: [],
};

const limpio = (v: string | undefined) => String(v ?? '').trim();

export function useAclaracion() {
  const ref = useRef<EstadoAclaracion>(INICIAL);
  const [acl, setEstado] = useState<EstadoAclaracion>(INICIAL);

  const actualizar = useCallback((cambio: (a: EstadoAclaracion) => EstadoAclaracion) => {
    ref.current = cambio(ref.current);
    setEstado(ref.current);
  }, []);

  const reiniciar = useCallback(() => actualizar(() => INICIAL), [actualizar]);

  const mostrarPreguntas = useCallback((preguntas: PreguntaAclaracion[], tema: string) => actualizar((a) => ({
    ...a, fase: 'preguntando', preguntas, respuestas: preguntas.map(() => ''), ronda: a.ronda + 1, tema,
  })), [actualizar]);

  const responder = useCallback((i: number, valor: string) => actualizar((a) => ({
    ...a, respuestas: a.respuestas.map((r, j) => (j === i ? valor : r)),
  })), [actualizar]);

  // Un ejemplo clicable se suma a lo que ya hubiera escrito
  const agregarEjemplo = useCallback((i: number, ejemplo: string) => actualizar((a) => ({
    ...a, respuestas: a.respuestas.map((r, j) => (j === i ? (r ? `${r}, ${ejemplo}` : ejemplo) : r)),
  })), [actualizar]);

  const agregarPropia = useCallback(() => actualizar((a) => ({
    ...a, custom: [...a.custom, { pregunta: '', respuesta: '' }],
  })), [actualizar]);

  const editarPropia = useCallback((i: number, campo: keyof Aclaracion, valor: string) => actualizar((a) => ({
    ...a, custom: a.custom.map((c, j) => (j === i ? { ...c, [campo]: valor } : c)),
  })), [actualizar]);

  const quitarPropia = useCallback((i: number) => actualizar((a) => ({
    ...a, custom: a.custom.filter((_, j) => j !== i),
  })), [actualizar]);

  // Cierra la ronda actual: guarda todas las preguntas mostradas y, si se pide,
  // pasa las respondidas al historial. Las propias siempre entran.
  const cerrarRonda = useCallback((conRespuestas: boolean) => actualizar((a) => {
    const vistas = [
      ...a.vistas,
      ...a.preguntas.map((q, i) => ({ pregunta: q.pregunta, respuesta: limpio(a.respuestas[i]) })),
      ...a.custom.filter((c) => limpio(c.pregunta)).map((c) => ({ pregunta: limpio(c.pregunta), respuesta: limpio(c.respuesta) })),
    ];
    const historial = [...a.historial];
    if (conRespuestas) {
      a.preguntas.forEach((q, i) => {
        if (limpio(a.respuestas[i])) historial.push({ pregunta: q.pregunta, respuesta: limpio(a.respuestas[i]), ronda: a.ronda });
      });
    }
    a.custom.forEach((c) => {
      if (limpio(c.pregunta)) historial.push({ pregunta: limpio(c.pregunta), respuesta: limpio(c.respuesta), ronda: a.ronda, custom: true });
    });
    return { ...a, vistas, historial, custom: [] };
  }), [actualizar]);

  return { acl, ref, reiniciar, mostrarPreguntas, responder, agregarEjemplo, agregarPropia, editarPropia, quitarPropia, cerrarRonda };
}

export type Aclaraciones = ReturnType<typeof useAclaracion>;
