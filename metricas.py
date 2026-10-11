"""Funciones compartidas para apuntar métricas de YouTube en el Google Sheet.

Las usan la página (bot_web.py) y la tarea semanal automática (actualizar_metricas.py).
"""
from datetime import date, datetime, timedelta, timezone

import requests

COLUMNAS_METRICAS = ["Semana", "Canal", "Plataforma", "Seguidores", "Visualizaciones",
                     "Mejor vídeo", "Notas"]
API = "https://www.googleapis.com/youtube/v3"


def lista_canales(texto: str) -> list[str]:
    """Convierte '@curiobet, @otrocanal' en ['@curiobet', '@otrocanal']."""
    return [c.strip() for c in (texto or "").split(",") if c.strip()]


def _get(endpoint: str, api_key: str, **params) -> dict:
    r = requests.get(f"{API}/{endpoint}", params={**params, "key": api_key}, timeout=20)
    if r.status_code != 200:
        try:
            mensaje = r.json()["error"]["message"]
        except Exception:
            mensaje = r.text[:200]
        raise RuntimeError(f"YouTube API ({r.status_code}): {mensaje}")
    return r.json()


def _mejor_video_semana(playlist_subidas: str, api_key: str) -> str:
    """Devuelve el vídeo con más visualizaciones de los publicados en los últimos 7 días."""
    try:
        items = _get("playlistItems", api_key, part="contentDetails",
                     playlistId=playlist_subidas, maxResults=50).get("items", [])
    except RuntimeError:
        return "Sin vídeos todavía"
    if not items:
        return "Sin vídeos todavía"

    ids = ",".join(i["contentDetails"]["videoId"] for i in items)
    videos = _get("videos", api_key, part="snippet,statistics", id=ids).get("items", [])
    if not videos:
        return "Sin vídeos todavía"

    hace_7_dias = datetime.now(timezone.utc) - timedelta(days=7)

    def publicado(v):
        return datetime.fromisoformat(v["snippet"]["publishedAt"].replace("Z", "+00:00"))

    def vistas(v):
        return int(v["statistics"].get("viewCount", 0))

    recientes = [v for v in videos if publicado(v) >= hace_7_dias]
    if recientes:
        top = max(recientes, key=vistas)
        return f'{top["snippet"]["title"]} ({vistas(top)} visualizaciones)'
    top = max(videos, key=vistas)
    return f'Sin vídeos nuevos esta semana. Más visto: {top["snippet"]["title"]} ({vistas(top)})'


def datos_canal(handle: str, api_key: str) -> dict:
    """Consulta los datos públicos de un canal a partir de su @usuario."""
    handle = handle.strip()
    if not handle.startswith("@"):
        handle = "@" + handle
    datos = _get("channels", api_key, part="snippet,statistics,contentDetails", forHandle=handle)
    if not datos.get("items"):
        raise RuntimeError(f"No encuentro el canal {handle}")

    canal = datos["items"][0]
    stats = canal["statistics"]
    return {
        "nombre": canal["snippet"]["title"],
        "seguidores": "Oculto" if stats.get("hiddenSubscriberCount")
        else int(stats.get("subscriberCount", 0)),
        "visualizaciones": int(stats.get("viewCount", 0)),
        "videos": int(stats.get("videoCount", 0)),
        "mejor": _mejor_video_semana(canal["contentDetails"]["relatedPlaylists"]["uploads"], api_key),
    }


def pestana_metricas(libro):
    """Devuelve la pestaña Métricas, creándola si no existe."""
    for hoja in libro.worksheets():
        if hoja.title.strip().lower() in ("métricas", "metricas"):
            return hoja
    hoja = libro.add_worksheet(title="Métricas", rows=1000, cols=10)
    hoja.append_row(COLUMNAS_METRICAS)
    hoja.format("1:1", {"textFormat": {"bold": True}})
    hoja.freeze(rows=1)
    return hoja


def actualizar_youtube(libro, api_key: str, canales: list[str]) -> str:
    """Apunta una fila en Métricas por cada canal y devuelve un resumen de texto."""
    hoja = pestana_metricas(libro)
    resumen = []
    for handle in canales:
        try:
            d = datos_canal(handle, api_key)
            hoja.append_row(
                [date.today().isoformat(), d["nombre"], "YouTube", d["seguidores"],
                 d["visualizaciones"], d["mejor"], f'Automático · {d["videos"]} vídeos'],
                value_input_option="RAW",
            )
            resumen.append(f'{d["nombre"]}: {d["seguidores"]} suscriptores, '
                           f'{d["visualizaciones"]} visualizaciones. Mejor vídeo: {d["mejor"]}')
        except Exception as e:
            resumen.append(f"{handle}: error, {e}")
    return "\n".join(resumen) if resumen else "No hay canales configurados."
