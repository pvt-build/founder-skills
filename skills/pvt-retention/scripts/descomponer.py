#!/usr/bin/env python3
"""Descompone un reel en escenas, texto en pantalla y voz por tramo."""

from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Optional, Union
import unicodedata
from urllib.parse import unquote, urlparse


SCRIPT_DIR = Path(__file__).resolve().parent


def avisar(mensaje: str) -> None:
    print(f"Aviso: {mensaje}", file=sys.stderr)


def ejecutar(comando: list[str], *, verificar: bool = False) -> subprocess.CompletedProcess[str]:
    resultado = subprocess.run(comando, text=True, capture_output=True)
    if verificar and resultado.returncode:
        detalle = (resultado.stderr or resultado.stdout).strip()[-1200:]
        raise RuntimeError(f"falló {' '.join(comando[:2])}: {detalle}")
    return resultado


def es_url(valor: str) -> bool:
    return urlparse(valor).scheme.lower() in {"http", "https"}


def nombre_entrada(valor: str) -> str:
    if es_url(valor):
        partes = [p for p in urlparse(valor).path.split("/") if p]
        base = partes[-1] if partes else urlparse(valor).netloc
    else:
        base = Path(valor).stem
    limpio = re.sub(r"[^A-Za-z0-9._-]+", "-", unquote(base)).strip("-._")
    return limpio or "reel"


def comprobar_dependencias() -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("falta la dependencia requerida ffmpeg en PATH")


def descargar_url(url: str, temporal: Path) -> Path:
    ejecutable = shutil.which("yt-dlp")
    if not ejecutable:
        if "instagram.com" in urlparse(url).netloc.lower():
            raise RuntimeError("descarga el reel y pásame el .mp4")
        raise RuntimeError("la entrada es una URL y yt-dlp no está disponible en PATH")

    plantilla = temporal / "entrada.%(ext)s"
    resultado = ejecutar([
        ejecutable,
        "--no-playlist",
        "-f", "bv*+ba/b",
        "--merge-output-format", "mp4",
        "-o", str(plantilla),
        url,
    ])
    candidatos = sorted(temporal.glob("entrada.*"))
    videos = [p for p in candidatos if p.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}]
    if resultado.returncode or not videos:
        if "instagram.com" in urlparse(url).netloc.lower():
            raise RuntimeError("descarga el reel y pásame el .mp4")
        detalle = (resultado.stderr or resultado.stdout).strip()[-1000:]
        raise RuntimeError(f"yt-dlp no pudo descargar la URL: {detalle}")
    return videos[0]


def preparar_entrada(valor: str, temporal: Path) -> Path:
    if es_url(valor):
        return descargar_url(valor, temporal)
    ruta = Path(valor).expanduser().resolve()
    if not ruta.is_file():
        raise FileNotFoundError(f"no existe el video: {ruta}")
    return ruta


def sondeo(video: Path) -> tuple[float, Union[float, int], int, int]:
    if shutil.which("ffprobe"):
        resultado = ejecutar([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,avg_frame_rate:format=duration",
            "-of", "json", str(video),
        ], verificar=True)
        datos = json.loads(resultado.stdout)
        flujo = datos["streams"][0]
        duracion = float(datos["format"]["duration"])
        numerador, denominador = flujo.get("avg_frame_rate", "0/1").split("/", 1)
        fps_float = float(numerador) / float(denominador) if float(denominador) else 0.0
        ancho, alto = int(flujo["width"]), int(flujo["height"])
    else:
        resultado = ejecutar(["ffmpeg", "-hide_banner", "-i", str(video)])
        detalle = resultado.stderr
        marca = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", detalle)
        linea_video = next((linea for linea in detalle.splitlines() if "Video:" in linea), "")
        geometria = re.search(r"(?<!\d)(\d{2,5})x(\d{2,5})(?!\d)", linea_video)
        tasa = re.search(r"(\d+(?:\.\d+)?)\s+fps", linea_video)
        if not (marca and geometria and tasa):
            raise RuntimeError("ffmpeg no pudo obtener duración, geometría o FPS")
        duracion = int(marca.group(1)) * 3600 + int(marca.group(2)) * 60 + float(marca.group(3))
        fps_float = float(tasa.group(1))
        ancho, alto = int(geometria.group(1)), int(geometria.group(2))
    fps: Union[float, int] = int(fps_float) if fps_float.is_integer() else round(fps_float, 3)
    if duracion <= 0 or not fps_float:
        raise RuntimeError("no se pudo obtener duración o FPS válidos")
    return duracion, fps, ancho, alto


def detectar_cortes(video: Path, umbral: float, duracion: float) -> list[float]:
    filtro = f"select='gt(scene,{umbral})',showinfo"
    resultado = ejecutar([
        "ffmpeg", "-hide_banner", "-i", str(video), "-vf", filtro,
        "-an", "-f", "null", os.devnull,
    ])
    if resultado.returncode:
        raise RuntimeError(f"ffmpeg no pudo detectar escenas: {resultado.stderr[-800:]}")
    cortes = [float(valor) for valor in re.findall(r"pts_time:([0-9.]+)", resultado.stderr)]
    return sorted({round(t, 3) for t in cortes if 0.05 < t < duracion - 0.05})


def inicios_escena(cortes: list[float], duracion: float, paso: float) -> list[float]:
    inicios = [0.0]
    anterior = 0.0
    for limite in [*cortes, duracion]:
        tramo = limite - anterior
        partes = max(1, math.ceil(tramo / paso))
        for parte in range(1, partes):
            inicios.append(round(anterior + tramo * parte / partes, 3))
        if limite < duracion:
            inicios.append(round(limite, 3))
        anterior = limite
    return sorted(set(inicios))


def extraer_fotogramas(
    video: Path, salida: Path, inicios: list[float], duracion: float
) -> list[tuple[Path, float, float, float]]:
    for anterior in salida.glob("escena_*.jpg"):
        anterior.unlink()
    escenas: list[tuple[Path, float, float, float]] = []
    for indice, inicio in enumerate(inicios, 1):
        fin = inicios[indice] if indice < len(inicios) else duracion
        centro = inicio + (fin - inicio) / 2
        imagen = salida / f"escena_{indice:03d}_{centro:07.3f}s.jpg"
        resultado = ejecutar([
            "ffmpeg", "-y", "-loglevel", "error", "-ss", f"{centro:.3f}",
            "-i", str(video), "-frames:v", "1", "-q:v", "2", str(imagen),
        ])
        if resultado.returncode or not imagen.exists():
            raise RuntimeError(f"no se pudo extraer la escena {indice}: {resultado.stderr[-800:]}")
        escenas.append((imagen, inicio, fin, centro))
    return escenas


def extraer_audio(video: Path, destino: Path) -> None:
    ejecutar([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
        "-vn", "-ac", "1", "-ar", "16000", str(destino),
    ], verificar=True)


def normalizar_segmentos(segmentos: object) -> list[dict[str, object]]:
    salida: list[dict[str, object]] = []
    for segmento in segmentos or []:
        if isinstance(segmento, dict):
            inicio = float(segmento.get("start", segmento.get("t", 0)))
            fin = segmento.get("end")
            texto = str(segmento.get("text", "")).strip()
        else:
            inicio = float(segmento.start)
            fin = getattr(segmento, "end", None)
            texto = str(segmento.text).strip()
        if texto:
            salida.append({"start": inicio, "end": float(fin) if fin is not None else None, "text": texto})
    return salida


def transcribir_con_motor(nombre: str, audio: Path, destino: Path) -> None:
    if nombre == "mlx_whisper":
        import mlx_whisper
        resultado = mlx_whisper.transcribe(
            str(audio), path_or_hf_repo="mlx-community/whisper-large-v3-turbo",
            word_timestamps=False,
        )
        segmentos = resultado.get("segments", [])
    elif nombre == "faster_whisper":
        from faster_whisper import WhisperModel
        segmentos, _ = WhisperModel("small", device="auto", compute_type="int8").transcribe(str(audio))
        segmentos = list(segmentos)
    elif nombre == "openai-whisper":
        import whisper
        segmentos = whisper.load_model("base").transcribe(str(audio)).get("segments", [])
    else:
        raise ValueError(f"motor Whisper desconocido: {nombre}")
    destino.write_text(
        json.dumps(normalizar_segmentos(segmentos), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def transcribir(audio: Path) -> tuple[list[dict[str, object]], Optional[str]]:
    intentos: list[str] = []
    if importlib.util.find_spec("mlx_whisper"):
        intentos.append("mlx_whisper")
    if importlib.util.find_spec("faster_whisper"):
        intentos.append("faster_whisper")
    if importlib.util.find_spec("whisper"):
        intentos.append("openai-whisper")

    if not intentos:
        avisar("no hay un motor Whisper disponible; la disección seguirá sin voz")
        return [], None

    for nombre in intentos:
        destino = audio.parent / f"transcripcion-{nombre}.json"
        resultado = ejecutar([
            sys.executable, str(Path(__file__).resolve()), "--motor-whisper",
            nombre, str(audio), str(destino),
        ])
        if resultado.returncode == 0 and destino.is_file():
            return json.loads(destino.read_text(encoding="utf-8")), nombre
        detalle = (resultado.stderr or resultado.stdout).strip().splitlines()
        causa = detalle[-1] if detalle else f"código {resultado.returncode}"
        avisar(f"{nombre} falló ({causa}); se intentará otra opción")
    avisar("ningún motor Whisper pudo transcribir; la disección seguirá sin voz")
    return [], None


def voz_en_tramo(
    segmentos: list[dict[str, object]], inicio: float, fin: float, duracion: float
) -> str:
    textos: list[str] = []
    for indice, segmento in enumerate(segmentos):
        seg_inicio = float(segmento["start"])
        seg_fin_valor = segmento.get("end")
        if seg_fin_valor is None:
            seg_fin = float(segmentos[indice + 1]["start"]) if indice + 1 < len(segmentos) else duracion
        else:
            seg_fin = float(seg_fin_valor)
        if seg_inicio < fin and seg_fin > inicio:
            textos.append(str(segmento["text"]))
    return " ".join(textos)


def ejecutar_ocr(escenas: list[tuple[Path, float, float, float]]) -> dict[str, str]:
    vacio = {str(imagen.resolve()): "" for imagen, *_ in escenas}
    if sys.platform != "darwin":
        avisar("OCR Vision solo está disponible en macOS; la disección seguirá sin OCR")
        return vacio
    osascript = shutil.which("osascript")
    script = SCRIPT_DIR / "ocr.js"
    if not osascript or not script.is_file():
        avisar("OCR Vision no está disponible; la disección seguirá sin OCR")
        return vacio
    resultado = ejecutar([
        osascript, "-l", "JavaScript", str(script), "--accurate",
        *[str(imagen.resolve()) for imagen, *_ in escenas],
    ])
    encontrados: dict[str, str] = {}
    for linea in (resultado.stdout + "\n" + resultado.stderr).splitlines():
        inicio = linea.find('{"f"')
        if inicio < 0:
            continue
        try:
            dato = json.loads(linea[inicio:])
            encontrados[str(Path(dato["f"]).resolve())] = str(dato.get("t") or "").strip()
        except (json.JSONDecodeError, KeyError):
            continue
    if resultado.returncode and not encontrados:
        avisar("OCR Vision falló; la disección seguirá sin OCR")
        return vacio
    if not any(encontrados.values()):
        avisar("OCR Vision no devolvió texto; la disección seguirá sin OCR")
    return {ruta: encontrados.get(ruta, "") for ruta in vacio}


def linea_normalizada(linea: str) -> str:
    linea = unicodedata.normalize("NFKC", linea).casefold()
    return re.sub(r"[^\w]+", " ", linea, flags=re.UNICODE).strip()


def texto_persistente(textos: list[str], proporcion: float = 0.60) -> list[str]:
    conteo: collections.Counter[str] = collections.Counter()
    formas: dict[str, collections.Counter[str]] = {}
    for texto in textos:
        vistos: set[str] = set()
        for linea in texto.splitlines():
            linea = " ".join(linea.split()).strip()
            normal = linea_normalizada(linea)
            if not normal or normal in vistos:
                continue
            vistos.add(normal)
            conteo[normal] += 1
            formas.setdefault(normal, collections.Counter())[linea] += 1
    minimo = math.ceil(len(textos) * proporcion)
    ganadores = [normal for normal, cantidad in conteo.items() if cantidad >= minimo]
    ganadores.sort(key=lambda normal: (-conteo[normal], normal))
    return [formas[normal].most_common(1)[0][0] for normal in ganadores]


def crear_hoja(escenas: list[tuple[Path, float, float, float]], destino: Path) -> bool:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        avisar("Pillow no está disponible; se omite hoja.jpg")
        return False

    abiertas = []
    try:
        abiertas = [Image.open(str(imagen)).convert("RGB") for imagen, *_ in escenas]
        ancho = 270
        miniaturas = [
            imagen.resize((ancho, round(imagen.height * ancho / imagen.width)), Image.Resampling.LANCZOS)
            for imagen in abiertas
        ]
        alto = max(imagen.height for imagen in miniaturas)
        columnas = min(4, max(1, math.ceil(math.sqrt(len(miniaturas)))))
        filas = math.ceil(len(miniaturas) / columnas)
        hoja = Image.new("RGB", (columnas * ancho, filas * alto), "black")
        dibujo = ImageDraw.Draw(hoja)
        fuente = ImageFont.load_default(size=18)
        for indice, (miniatura, escena) in enumerate(zip(miniaturas, escenas)):
            x, y = (indice % columnas) * ancho, (indice // columnas) * alto
            hoja.paste(miniatura, (x, y))
            etiqueta = f"{indice + 1:02d}  {escena[1]:05.2f}s"
            caja = dibujo.textbbox((0, 0), etiqueta, font=fuente)
            dibujo.rectangle((x + 7, y + 7, x + 19 + caja[2], y + 17 + caja[3]), fill="black")
            dibujo.text((x + 13, y + 12), etiqueta, fill="white", font=fuente)
        hoja.save(destino, quality=90)
        return True
    except Exception as error:
        avisar(f"no se pudo crear hoja.jpg ({error}); se omite")
        return False
    finally:
        for imagen in abiertas:
            imagen.close()


def descomponer(entrada: str, salida: Path, paso: float, umbral: float) -> Path:
    comprobar_dependencias()
    salida.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pvt-retention-") as temporal_crudo:
        temporal = Path(temporal_crudo)
        video = preparar_entrada(entrada, temporal)
        duracion, fps, ancho, alto = sondeo(video)
        cortes = detectar_cortes(video, umbral, duracion)
        inicios = inicios_escena(cortes, duracion, paso)
        escenas_base = extraer_fotogramas(video, salida, inicios, duracion)

        segmentos: list[dict[str, object]] = []
        motor: Optional[str] = None
        audio = temporal / "audio.wav"
        try:
            extraer_audio(video, audio)
            segmentos, motor = transcribir(audio)
        except Exception as error:
            avisar(f"no se pudo preparar la transcripción ({error}); la disección seguirá sin voz")

        ocr = ejecutar_ocr(escenas_base)
        escenas = []
        for imagen, inicio, fin, centro in escenas_base:
            escenas.append({
                "t": round(centro, 3),
                "img": imagen.name,
                "ocr": ocr.get(str(imagen.resolve()), ""),
                "voz": voz_en_tramo(segmentos, inicio, fin, duracion),
            })

        hoja = salida / "hoja.jpg"
        if hoja.exists():
            hoja.unlink()
        crear_hoja(escenas_base, hoja)
        datos = {
            "dur": round(duracion, 3),
            "fps": fps,
            "w": ancho,
            "h": alto,
            "n_escenas": len(escenas),
            "cortes_por_segundo": round(len(cortes) / duracion, 3),
            "escenas": escenas,
            "texto_persistente": texto_persistente([escena["ocr"] for escena in escenas]),
        }
        destino = salida / "diseccion.json"
        destino.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        motor_texto = motor or "sin voz"
        print(f"Listo: {len(escenas)} escenas, {len(cortes)} cortes, {motor_texto} → {destino}")
        return destino


def argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("entrada", help="URL o ruta local de video")
    parser.add_argument("--out", type=Path, help="carpeta de salida")
    parser.add_argument("--paso", type=float, default=0.8, help="separación máxima entre escenas")
    parser.add_argument("--umbral", type=float, default=0.3, help="umbral de cambio de escena, entre 0 y 1")
    return parser.parse_args()


def main() -> int:
    if len(sys.argv) == 5 and sys.argv[1] == "--motor-whisper":
        try:
            transcribir_con_motor(sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4]))
            return 0
        except Exception as error:
            print(f"Error: {error}", file=sys.stderr)
            return 1
    opciones = argumentos()
    if opciones.paso <= 0:
        print("Error: --paso debe ser mayor que 0", file=sys.stderr)
        return 2
    if not 0 <= opciones.umbral <= 1:
        print("Error: --umbral debe estar entre 0 y 1", file=sys.stderr)
        return 2
    salida = opciones.out or Path.cwd() / "descomposicion" / nombre_entrada(opciones.entrada)
    try:
        descomponer(opciones.entrada, salida.resolve(), opciones.paso, opciones.umbral)
        return 0
    except (FileNotFoundError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
