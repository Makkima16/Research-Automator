'use client';

// Une el estado del servidor (useProyectos), la ronda de aclaración y los
// diálogos, y expone las acciones del flujo completo a las vistas.
import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode,
} from 'react';
import * as api from '@/lib/api';
import { useAclaracion, type Aclaraciones } from '@/hooks/useAclaracion';
import { useProyectos } from '@/hooks/useProyectos';
import type { Alcance, Ficha, Idioma, Proyecto, ProyectoResumen } from '@/lib/tipos';

export type Pestana = 'busqueda' | 'procesamiento';

export interface DatosConfirmacion {
  titulo: string;
  cuerpo: string;
  etiqueta: string;
}

interface Confirmacion extends DatosConfirmacion {
  resolver: (acepta: boolean) => void;
}

// Campos del formulario de prompt; si todavía no hay proyecto viven en un borrador
export interface CamposPrompt {
  prompt: string;
  num: number;
  idioma: Idioma;
}

const BORRADOR: CamposPrompt = { prompt: '', num: 5, idioma: 'en' };

interface Contexto {
  proyectos: ProyectoResumen[];
  proyecto: Proyecto | null;
  fichas: Ficha[];
  cargando: boolean;
  ocupado: boolean;
  campos: CamposPrompt;
  aclaracion: Aclaraciones;
  pestana: Pestana;
  setPestana: (p: Pestana) => void;

  error: string | null;
  limpiarError: () => void;
  confirmacion: Confirmacion | null;
  confirmar: (datos: DatosConfirmacion) => Promise<boolean>;
  toast: string | null;
  avisar: (mensaje: string) => void;

  seleccionarProyecto: (id: string) => Promise<void>;
  nuevoProyecto: () => Promise<void>;
  eliminarProyecto: (id: string) => Promise<void>;
  renombrar: (nombre: string) => Promise<void>;
  reiniciar: () => Promise<void>;

  editarPrompt: (parche: Partial<CamposPrompt>) => void;
  guardarCampos: (campos: api.CamposProyecto) => Promise<void>;
  editarCadenas: (queries: string[]) => void;
  guardarCadenas: (queries: string[]) => Promise<void>;
  editarParametro: (clave: 'min_year' | 'max_resultados', valor: string) => void;
  guardarParametro: (clave: 'min_year' | 'max_resultados') => Promise<void>;

  generar: () => Promise<void>;
  responderAclaracion: () => Promise<void>;
  omitirAclaracion: () => Promise<void>;
  rehacerPrompt: () => Promise<void>;
  volverAlPrompt: () => Promise<void>;
  volverACadenas: () => Promise<void>;
  volverAResultados: () => Promise<void>;

  buscar: () => Promise<void>;
  cancelarBusqueda: () => Promise<void>;
  procesar: (alcance: Alcance, tope?: number) => Promise<void>;
  cancelarProcesamiento: () => Promise<void>;
  alternarSeleccion: (id: string) => Promise<void>;
}

const AppContext = createContext<Contexto | null>(null);

export function useApp(): Contexto {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useApp debe usarse dentro de <AppProvider>');
  return ctx;
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [error, setError] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [borrador, setBorrador] = useState<CamposPrompt>(BORRADOR);
  const [pestana, setPestana] = useState<Pestana>('busqueda');
  const [confirmacion, setConfirmacion] = useState<Confirmacion | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const temporizadorToast = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const alFallar = useCallback((e: unknown) => setError(e instanceof Error ? e.message : String(e)), []);
  const { proyectos, setProyectos, proyecto, proyectoRef, setProyecto, fichas, cargando, seleccionar } = useProyectos(alFallar);
  const aclaracion = useAclaracion();

  // Ejecuta una acción mostrando su error en la página en vez de perderlo
  const ejecutar = useCallback(async (accion: () => Promise<void>) => {
    setError(null);
    try { await accion(); } catch (e) { alFallar(e); }
  }, [alFallar]);

  // ---------- diálogos ----------

  const confirmar = useCallback((datos: DatosConfirmacion) => new Promise<boolean>((resolver) => {
    // Toda salida (botones, clic afuera o Escape) cierra el diálogo y resuelve la promesa
    setConfirmacion({ ...datos, resolver: (acepta: boolean) => { setConfirmacion(null); resolver(acepta); } });
  }), []);

  useEffect(() => {
    if (!confirmacion) return;
    const alTeclear = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      e.stopPropagation();
      confirmacion.resolver(false);
    };
    window.addEventListener('keydown', alTeclear, true);
    return () => window.removeEventListener('keydown', alTeclear, true);
  }, [confirmacion]);

  const avisar = useCallback((mensaje: string) => {
    clearTimeout(temporizadorToast.current);
    setToast(mensaje);
    temporizadorToast.current = setTimeout(() => setToast(null), 2200);
  }, []);

  // ---------- proyectos ----------

  const actual = () => {
    const p = proyectoRef.current;
    if (!p) throw new Error('No hay un proyecto abierto.');
    return p;
  };

  const seleccionarProyecto = useCallback((id: string) => ejecutar(async () => {
    aclaracion.reiniciar();
    setPestana('busqueda');
    await seleccionar(id);
  }), [ejecutar, aclaracion, seleccionar]);

  // Crea el proyecto en el servidor y lo deja como activo
  const crearYActivar = useCallback(async () => {
    const p = await api.crearProyecto();
    setProyectos((lista) => [...lista, p]);
    aclaracion.reiniciar();
    setPestana('busqueda');
    setProyecto(p);
    return p;
  }, [aclaracion, setProyecto, setProyectos]);

  const nuevoProyecto = useCallback(() => ejecutar(async () => {
    await crearYActivar();
    setBorrador(BORRADOR);
  }), [ejecutar, crearYActivar]);

  const eliminarProyecto = useCallback((id: string) => ejecutar(async () => {
    const objetivo = proyectos.find((p) => p.id === id);
    const acepta = await confirmar({
      titulo: '¿Eliminar proyecto?',
      cuerpo: `Se borrará «${objetivo?.name ?? 'este proyecto'}» con sus cadenas, resultados y fichas. No se puede deshacer.`,
      etiqueta: 'Eliminar',
    });
    if (!acepta) return;
    await api.borrarProyecto(id);
    const resto = proyectos.filter((p) => p.id !== id);
    setProyectos(resto);
    if (proyectoRef.current?.id === id) {
      setProyecto(null);
      aclaracion.reiniciar();
      if (resto.length) await seleccionar(resto[resto.length - 1].id);
    }
    avisar('Proyecto eliminado');
  }), [ejecutar, proyectos, confirmar, setProyectos, proyectoRef, setProyecto, aclaracion, seleccionar, avisar]);

  const renombrar = useCallback((nombre: string) => ejecutar(async () => {
    const p = actual();
    const limpio = nombre.trim();
    if (!limpio || limpio === p.name) return;
    setProyecto(await api.actualizarProyecto(p.id, { name: limpio }));
  }), [ejecutar, setProyecto]);

  const reiniciar = useCallback(() => ejecutar(async () => {
    const p = actual();
    const acepta = await confirmar({
      titulo: '¿Reiniciar el proyecto?',
      cuerpo: 'Se borrarán el prompt, las cadenas y los resultados. El nombre del proyecto se conserva.',
      etiqueta: 'Reiniciar',
    });
    if (!acepta) return;
    setProyecto(await api.actualizarProyecto(p.id, { reiniciar: true }));
    aclaracion.reiniciar();
  }), [ejecutar, confirmar, setProyecto, aclaracion]);

  // ---------- campos del prompt y de las cadenas ----------

  const campos: CamposPrompt = proyecto
    ? { prompt: proyecto.prompt, num: proyecto.num, idioma: proyecto.idioma }
    : borrador;

  const editarPrompt = useCallback((parche: Partial<CamposPrompt>) => {
    if (proyectoRef.current) setProyecto((p) => (p ? { ...p, ...parche } : p));
    else setBorrador((b) => ({ ...b, ...parche }));
  }, [proyectoRef, setProyecto]);

  // Guarda en el servidor sin reemplazar el proyecto: solo se toman de la respuesta
  // los campos enviados (el servidor los ajusta a sus límites)
  const guardarCampos = useCallback((cambios: api.CamposProyecto) => ejecutar(async () => {
    const p = proyectoRef.current;
    if (!p) return;
    const guardado = await api.actualizarProyecto(p.id, cambios);
    const claves = Object.keys(cambios).filter((k) => k in guardado) as (keyof Proyecto)[];
    setProyecto((vigente) => {
      if (!vigente || vigente.id !== p.id) return vigente;
      const parche: Record<string, unknown> = {};
      claves.forEach((k) => { parche[k] = guardado[k]; });
      return { ...vigente, ...parche };
    });
  }), [ejecutar, proyectoRef, setProyecto]);

  const editarCadenas = useCallback((queries: string[]) => {
    setProyecto((p) => (p ? { ...p, queries } : p));
  }, [setProyecto]);

  const guardarCadenas = useCallback((queries: string[]) => guardarCampos({ queries }), [guardarCampos]);

  // Año mínimo y tope por cadena se editan como texto; el servidor devuelve el valor ya acotado
  const editarParametro = useCallback((clave: 'min_year' | 'max_resultados', valor: string) => {
    setProyecto((p) => (p ? { ...p, [clave]: valor === '' ? null : Number(valor) } : p));
  }, [setProyecto]);

  const guardarParametro = useCallback(async (clave: 'min_year' | 'max_resultados') => {
    const valor = proyectoRef.current?.[clave];
    await guardarCampos({ [clave]: valor ?? '' });
  }, [guardarCampos, proyectoRef]);

  // ---------- aclaración y generación de cadenas ----------

  const crearCadenas = useCallback(async (p: Proyecto, refinado: string) => {
    const historial = aclaracion.ref.current.historial;
    const partes = [`Tema original: ${p.prompt}`];
    historial.forEach((h) => {
      if (h.pregunta) partes.push(h.respuesta.trim() ? `Pregunta: ${h.pregunta} Respuesta: ${h.respuesta.trim()}` : `Pregunta: ${h.pregunta}`);
    });
    const intencion = partes.join(' | ');
    const nuevo = await api.generarCadenas(p.id, {
      prompt: p.prompt, num: p.num, idioma: p.idioma, tema_refinado: refinado, historial,
      aclaraciones: aclaracion.ref.current.vistas, intencion, intencion_busqueda: intencion,
    });
    setProyecto(nuevo);
    aclaracion.reiniciar();
  }, [aclaracion, setProyecto]);

  // Pregunta a Nemotron si el tema es lo bastante concreto: si no, muestra sus
  // preguntas; si sí, genera las cadenas con el tema refinado
  const evaluarTema = useCallback(async (p: Proyecto) => {
    const r = await api.aclarar(p.id, p.prompt, aclaracion.ref.current.historial);
    if (!r.suficiente) aclaracion.mostrarPreguntas(r.preguntas, r.tema_refinado);
    else await crearCadenas(p, r.tema_refinado);
  }, [aclaracion, crearCadenas]);

  const conOcupado = useCallback(async (accion: () => Promise<void>) => {
    setOcupado(true);
    try { await accion(); } finally { setOcupado(false); }
  }, []);

  const generar = useCallback(() => ejecutar(async () => {
    if (!campos.prompt.trim()) throw new Error('Escribe primero el tema que quieres investigar.');
    let p = proyectoRef.current;
    if (!p) {
      const creado = await crearYActivar();
      p = { ...creado, ...borrador };
      setProyecto(p);
    }
    aclaracion.reiniciar();
    await conOcupado(() => evaluarTema(p));
  }), [ejecutar, campos.prompt, proyectoRef, crearYActivar, borrador, setProyecto, aclaracion, conOcupado, evaluarTema]);

  const responderAclaracion = useCallback(() => ejecutar(async () => {
    const p = actual();
    aclaracion.cerrarRonda(true);
    await conOcupado(() => evaluarTema(p));
  }), [ejecutar, aclaracion, conOcupado, evaluarTema]);

  const omitirAclaracion = useCallback(() => ejecutar(async () => {
    const p = actual();
    aclaracion.cerrarRonda(false);
    await conOcupado(() => crearCadenas(p, aclaracion.ref.current.tema));
  }), [ejecutar, aclaracion, conOcupado, crearCadenas]);

  const rehacerPrompt = useCallback(() => ejecutar(async () => {
    const p = actual();
    const acepta = await confirmar({
      titulo: '¿Rehacer el prompt?',
      cuerpo: 'Se borran las preguntas y respuestas generadas, la intención detectada, las cadenas y los papers buscados (con su selección y procesamiento). Las preguntas se volverán a generar.',
      etiqueta: 'Rehacer prompt',
    });
    if (!acepta) return;
    setProyecto(await api.actualizarProyecto(p.id, { rehacer_prompt: true }));
    aclaracion.reiniciar();
  }), [ejecutar, confirmar, setProyecto, aclaracion]);

  const cambiarEtapa = useCallback((etapa: 'empty' | 'queries' | 'results') => ejecutar(async () => {
    const p = actual();
    const conCadenas = etapa === 'queries' ? {} : { queries: p.queries };
    setProyecto(await api.actualizarProyecto(p.id, { ...conCadenas, stage: etapa }));
  }), [ejecutar, setProyecto]);

  const volverAlPrompt = useCallback(() => cambiarEtapa('empty'), [cambiarEtapa]);
  const volverACadenas = useCallback(() => cambiarEtapa('queries'), [cambiarEtapa]);
  const volverAResultados = useCallback(() => cambiarEtapa('results'), [cambiarEtapa]);

  // ---------- búsqueda y procesamiento ----------

  const buscar = useCallback(() => ejecutar(async () => {
    const p = actual();
    if (p.papers.length) {
      const acepta = await confirmar({
        titulo: '¿Buscar de nuevo?',
        cuerpo: 'Este proyecto ya tiene resultados. Una nueva búsqueda los reemplazará, incluida tu selección.',
        etiqueta: 'Buscar de nuevo',
      });
      if (!acepta) return;
    }
    setProyecto(await api.iniciarBusqueda(p.id, p.queries, p.min_year, p.max_resultados));
    setPestana('busqueda');
  }), [ejecutar, confirmar, setProyecto]);

  const cancelarBusqueda = useCallback(() => ejecutar(async () => {
    setProyecto(await api.cancelarBusqueda(actual().id));
  }), [ejecutar, setProyecto]);

  const procesar = useCallback((alcance: Alcance, tope?: number) => ejecutar(async () => {
    setProyecto(await api.iniciarProcesamiento(actual().id, alcance, tope));
  }), [ejecutar, setProyecto]);

  const cancelarProcesamiento = useCallback(() => ejecutar(async () => {
    setProyecto(await api.cancelarProcesamiento(actual().id));
    avisar('Procesamiento detenido · lo extraído quedó guardado');
  }), [ejecutar, setProyecto, avisar]);

  const alternarSeleccion = useCallback(async (id: string) => {
    const p = proyectoRef.current;
    if (!p) return;
    const seleccion = p.seleccion.includes(id) ? p.seleccion.filter((x) => x !== id) : [...p.seleccion, id];
    setProyecto({ ...p, seleccion });
    await guardarCampos({ seleccion });
  }, [proyectoRef, setProyecto, guardarCampos]);

  const valor = useMemo<Contexto>(() => ({
    proyectos, proyecto, fichas, cargando, ocupado, campos, aclaracion, pestana, setPestana,
    error, limpiarError: () => setError(null), confirmacion, confirmar, toast, avisar,
    seleccionarProyecto, nuevoProyecto, eliminarProyecto, renombrar, reiniciar,
    editarPrompt, guardarCampos, editarCadenas, guardarCadenas, editarParametro, guardarParametro,
    generar, responderAclaracion, omitirAclaracion, rehacerPrompt, volverAlPrompt, volverACadenas, volverAResultados,
    buscar, cancelarBusqueda, procesar, cancelarProcesamiento, alternarSeleccion,
  }), [proyectos, proyecto, fichas, cargando, ocupado, campos, aclaracion, pestana, error, confirmacion, confirmar, toast, avisar,
    seleccionarProyecto, nuevoProyecto, eliminarProyecto, renombrar, reiniciar, editarPrompt, guardarCampos, editarCadenas,
    guardarCadenas, editarParametro, guardarParametro, generar, responderAclaracion, omitirAclaracion, rehacerPrompt,
    volverAlPrompt, volverACadenas, volverAResultados, buscar, cancelarBusqueda, procesar, cancelarProcesamiento, alternarSeleccion]);

  return <AppContext.Provider value={valor}>{children}</AppContext.Provider>;
}
