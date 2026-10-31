// Tipos del contrato con la API de servidor.py (ver CONTEXTO_FRONTEND.md, sección 5).

export type Etapa = 'empty' | 'queries' | 'loading' | 'results';
export type Idioma = 'en' | 'ambos' | 'es';
export type Alcance = 'sel' | 'todos';

export interface PasoProgreso {
  texto: string;
  estado: 'pending' | 'active' | 'done';
}

export interface Aclaracion {
  pregunta: string;
  respuesta: string;
}

export interface DetalleCadena {
  cadena?: string;
  intencion?: string;
  alcance?: string;
}

export interface IntencionCadenas {
  intencion_consolidada?: string;
  detalles?: DetalleCadena[];
}

export interface Procesamiento {
  activo: boolean;
  estado: null | 'ok' | 'error';
  error: string | null;
  alcance: Alcance | null;
  hechos: number;
  total: number;
  actual: string | null;
  conteos: Record<string, number>;
  inicio: string | null;
  fin: string | null;
  mensajes: string[];
  tope: number;
}

export interface Paper {
  id: string;
  doi: string | null;
  openalex_id: string | null;
  title: string | null;
  year: number | null;
  cited_by_count: number | null;
  is_oa: boolean;
  oa_url: string | null;
  source: string | null;
  abstract: string | null;
  matched_query: string;
  motor_busqueda: string;
  motor_pdf: string | null;
  pdf_url: string | null;
  score: number | null;
}

export interface ProyectoResumen {
  id: string;
  archivo?: string;
  name: string;
  stage: Etapa;
  prompt: string;
  num: number;
  idioma: Idioma;
  queries: string[];
  min_year: number | null;
  max_resultados: number;
  aviso: string | null;
  progreso: PasoProgreso[];
  fuentes: number;
  cadenas_usadas: number;
  seleccion: string[];
  tema_refinado?: string;
  aclaraciones?: Aclaracion[];
  intencion_busqueda?: string;
  intencion_cadenas?: IntencionCadenas;
  procesamiento: Procesamiento;
}

export interface Proyecto extends ProyectoResumen {
  papers: Paper[];
}

export interface TablaFicha {
  nombre: string;
  atributos: string[];
  que_aporta: string;
}

export interface Ficha {
  paper_id: string;
  title: string | null;
  year: number | null;
  doi: string | null;
  estado: 'ok' | 'no_relevante';
  cobertura: 'completa' | 'parcial';
  fuente: string | null;
  fuente_url: string | null;
  abstract: string | null;
  intro_penultimo: string | null;
  intro_ultimo: string | null;
  conclusion_texto: string | null;
  resumen: string | null;
  objetivo: string | null;
  conclusiones: string[];
  hallazgos_clave: string[];
  tablas: TablaFicha[];
}

export interface PreguntaAclaracion {
  pregunta: string;
  ejemplos?: string[];
}

export interface RespuestaAclarar {
  suficiente: boolean;
  tema_refinado: string;
  preguntas: PreguntaAclaracion[];
}

export interface EntradaHistorial {
  pregunta: string;
  respuesta: string;
  ronda: number;
  custom?: boolean;
}
