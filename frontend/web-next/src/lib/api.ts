// Cliente tipado de la API de servidor.py. El contrato HTTP no cambia.
import type {
  Alcance, Aclaracion, EntradaHistorial, Ficha, Proyecto, ProyectoResumen, RespuestaAclarar,
} from './tipos';

async function api<T>(metodo: string, ruta: string, cuerpo?: unknown): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(ruta, {
      method: metodo,
      headers: cuerpo ? { 'Content-Type': 'application/json' } : {},
      body: cuerpo ? JSON.stringify(cuerpo) : undefined,
      cache: 'no-store',
    });
  } catch {
    throw new Error('No hay conexión con el servidor (¿sigue corriendo python servidor.py?).');
  }
  const datos = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error((datos as { error?: string }).error || `Error ${resp.status}`);
  return datos as T;
}

const base = (id: string) => `/api/proyectos/${id}`;

export interface CamposProyecto {
  name?: string;
  prompt?: string;
  num?: number | string;
  idioma?: string;
  queries?: string[];
  seleccion?: string[];
  min_year?: number | string | null;
  max_resultados?: number | string;
  stage?: 'empty' | 'queries' | 'results';
  reiniciar?: boolean;
  rehacer_prompt?: boolean;
}

export interface DatosCadenas {
  prompt: string;
  num: number;
  idioma: string;
  tema_refinado: string;
  historial: EntradaHistorial[];
  aclaraciones: Aclaracion[];
  intencion: string;
  intencion_busqueda: string;
}

export const listarProyectos = () => api<ProyectoResumen[]>('GET', '/api/proyectos');
export const crearProyecto = () => api<Proyecto>('POST', '/api/proyectos');
export const obtenerProyecto = (id: string) => api<Proyecto>('GET', base(id));
export const actualizarProyecto = (id: string, campos: CamposProyecto) => api<Proyecto>('PUT', base(id), campos);
export const borrarProyecto = (id: string) => api<{ ok: boolean }>('DELETE', base(id));

export const aclarar = (id: string, prompt: string, historial: EntradaHistorial[]) =>
  api<RespuestaAclarar>('POST', `${base(id)}/aclarar`, { prompt, historial });
export const generarCadenas = (id: string, datos: DatosCadenas) => api<Proyecto>('POST', `${base(id)}/cadenas`, datos);

export const iniciarBusqueda = (id: string, queries: string[], min_year: number | string | null, max_resultados: number | string) =>
  api<Proyecto>('POST', `${base(id)}/buscar`, { queries, min_year, max_resultados });
export const cancelarBusqueda = (id: string) => api<Proyecto>('POST', `${base(id)}/cancelar`);

export const iniciarProcesamiento = (id: string, alcance: Alcance, tope?: number) =>
  api<Proyecto>('POST', `${base(id)}/procesar`, { alcance, ...(tope ? { tope } : {}) });
export const cancelarProcesamiento = (id: string) => api<Proyecto>('POST', `${base(id)}/cancelar-procesar`);
export const listarFichas = (id: string) => api<Ficha[]>('GET', `${base(id)}/fichas`);

export const urlCsvPapers = (id: string, soloSeleccion: boolean) =>
  `${base(id)}/papers.csv${soloSeleccion ? '?seleccion=1' : ''}`;
