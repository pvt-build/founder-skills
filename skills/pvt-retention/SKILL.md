---
name: pvt-retention
description: >-
  Mejora la retención de reels: descompone piezas virales, revisa guiones antes
  de grabar y convierte resultados propios en reglas. Úsala cuando el usuario
  diga «retención», «viral», «descompón este reel», «revisa mi guion»,
  «open loop» o «rehook».
---

# Retención de reels

## Para qué sirve

Hace tres cosas: descubre la mecánica de retención de un reel ajeno, decide si
un guion está listo para grabarse y aprende de la retención real del usuario.
No produce, publica ni promete viralidad.

## Fuente de criterio

Lee [references/estructura.md](references/estructura.md) antes de trabajar. Esa
es la ley vigente para elegir esqueleto, evaluar beats y proponer correcciones.

## Modo 1 · Descomponer

Actívalo cuando el usuario entregue un reel ajeno, una URL o un video local.

1. Ejecuta:
   `python3 scripts/descomponer.py <url|ruta.mp4> [--out carpeta] [--paso 0.8] [--umbral 0.3]`.
2. Lee `diseccion.json` y, si existe, observa `hoja.jpg`.
3. Mapea cada tramo al esqueleto A o B con su segundo de entrada.
4. Devuelve: mecanismo central, beats, cortes por segundo, progreso visual,
   rehooks literales, CTA y qué conviene adaptar sin copiar el tema.
5. Separa observación de inferencia. Likes y comentarios solo se citan si el
   usuario los entrega o se verifican en una fuente pública.

El script requiere Python 3, `ffmpeg` y `ffprobe` en `PATH`. Puede usar
`yt-dlp`, motores Whisper, Pillow y OCR de macOS si están disponibles. Si una
capacidad opcional falla, analiza el resto y declara el faltante.

## Modo 2 · Revisión de guion

Actívalo antes de grabar.

- Elige A si explica una idea; elige B si entrega una lista de N elementos.
- Presenta una tabla: beat, segundo previsto, frase o recurso, estado y arreglo.
- A puntúa /8 y pasa con 7 o más. B puntúa /5 y solo pasa con 5/5.
- Si no pasa, entrega la corrección beat por beat, incluidas las frases de
  rehook listas para decir. No declares que está listo mientras falle el gate.

## Modo 3 · Aprender

Registra una línea JSON por reel en `references/registro.jsonl`. Usa únicamente
métricas verificadas; deja `null` cuando falte un dato.

Esquema:

```json
{"fecha":"AAAA-MM-DD","tipo":"reel_propio","url":null,"esqueleto":"A","puntaje_gate":8,"beats_fallidos":[],"cambio_probado":"descripción breve","vistas":null,"ret_3s":null,"ret_10s":null,"prom_visto_s":null,"comentarios":null,"likes":null,"aprendizaje":"descripción breve"}
```

Un cambio pasa de hipótesis a ley solo cuando tres reels propios que lo usan
superan la mediana de retención a 10 segundos de los últimos diez reels del
usuario. Entonces actualiza `estructura.md`, incrementa su versión y anota el
cambio en el changelog. Antes de reunir esa evidencia, conserva la hipótesis
solo en el registro.

## Límites

- No inventes métricas, causalidad ni resultados.
- No confundas descomposición con permiso para copiar una pieza.
- No uses una referencia ajena como prueba de que una regla funciona para el
  usuario: su propio registro decide qué entra en la ley.
