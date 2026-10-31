"""
Prueba mínima de conexión con NVIDIA: una llamada corta al LLM (NVIDIA_API_KEY) y
una a Nemotron Parse con una imagen de prueba (NVIDIA_PARSE_API_KEY), para
confirmar que las dos keys del .env funcionan antes de correr extract_ficha.py.

    python probar_nvidia.py
"""

import config_proc as config
import lectura_pdf
import llm_nvidia


def probar_llm():
    if not llm_nvidia.configurado():
        print("LLM: falta NVIDIA_API_KEY en el archivo .env.")
        return
    try:
        texto = llm_nvidia.chat_json('Responde solo con el JSON {"respuesta": "ok"}', "Prueba", timeout=60)
        print(f"LLM ({config.NVIDIA_MODELO}): OK -> {texto}")
    except Exception as exc:
        print(f"LLM: ERROR {type(exc).__name__}: {exc}")


def probar_parse():
    if not lectura_pdf.configurado():
        print("Parse: falta NVIDIA_PARSE_API_KEY en el archivo .env.")
        return
    import pymupdf
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 100), "Abstract. Prueba de conexion con Nemotron Parse.", fontsize=14)
    png = doc[0].get_pixmap(dpi=100).tobytes("png")
    doc.close()
    try:
        contenido = lectura_pdf._parse_pagina(png)
        print(f"Parse: OK -> {' '.join(contenido.split())[:120]!r}")
    except lectura_pdf.ErrorLecturaPDF as exc:
        print(f"Parse: ERROR {exc}")


if __name__ == "__main__":
    probar_llm()
    probar_parse()
