import io
import json
import os
import time
from datetime import date

import gspread
import pandas as pd
import streamlit as st
from google import genai
from google.genai import types

MODELO = "gemini-flash-lite-latest"  # si da problemas, prueba "gemini-flash-latest"

# Pestañas que el bot crea automáticamente si no existen, con sus columnas
PLANTILLAS = {
    "Contenido": ["Fecha", "Canal", "Plataforma", "Idea / título", "Estado",
                  "Responsable", "Visualizaciones", "Enlace"],
    "Métricas": ["Semana", "Canal", "Plataforma", "Seguidores", "Visualizaciones",
                 "Mejor vídeo", "Notas"],
    "Finanzas": ["Fecha", "Tipo", "Concepto", "Importe (€)", "Pagado por", "Notas"],
    "Productos": ["Producto", "Enlace proveedor", "Coste (€)", "Precio venta (€)",
                  "Margen (€)", "Estado", "Notas"],
}


# ---------- Conexión con Google Sheets ----------

@st.cache_resource
def obtener_libro():
    """Conecta con el archivo de Google Sheets usando la cuenta de servicio."""
    credenciales = json.loads(st.secrets["GCP_JSON"])
    gc = gspread.service_account_from_dict(credenciales)
    return gc.open_by_url(st.secrets["SHEET_URL"])


@st.cache_resource
def preparar_plantillas():
    """Crea las pestañas de PLANTILLAS que falten, con encabezados en negrita."""
    libro = obtener_libro()
    existentes = [h.title for h in libro.worksheets()]
    for nombre, columnas in PLANTILLAS.items():
        if nombre in existentes:
            continue
        hoja = libro.add_worksheet(title=nombre, rows=1000, cols=max(len(columnas), 10))
        hoja.append_row(columnas)
        hoja.format("1:1", {"textFormat": {"bold": True}})
        hoja.freeze(rows=1)
    return True


def pestana(nombre: str):
    """Devuelve la pestaña por nombre, sin importar mayúsculas o tildes de más."""
    libro = obtener_libro()
    for hoja in libro.worksheets():
        if hoja.title.strip().lower() == nombre.strip().lower():
            return hoja
    raise ValueError(
        f"No existe la pestaña '{nombre}'. Pestañas disponibles: "
        + ", ".join(h.title for h in libro.worksheets())
    )


# ---------- Herramientas que la IA puede usar ----------

def listar_pestanas() -> str:
    """Devuelve los nombres de todas las pestañas del archivo y sus encabezados."""
    try:
        partes = []
        for hoja in obtener_libro().worksheets():
            encabezados = hoja.row_values(1)
            partes.append(f"{hoja.title}: {encabezados if encabezados else '(vacía)'}")
        return "\n".join(partes)
    except Exception as e:
        return f"Error: {e}"


def leer_pestana(nombre_pestana: str) -> str:
    """Devuelve todo el contenido de una pestaña, fila por fila (la fila 1 son los encabezados)."""
    try:
        filas = pestana(nombre_pestana).get_all_values()
        return str(filas) if filas else "La pestaña está vacía."
    except Exception as e:
        return f"Error: {e}"


def escribir_celda(nombre_pestana: str, celda: str, valor: str) -> str:
    """Escribe un valor o fórmula en una celda concreta de una pestaña, por ejemplo B3."""
    try:
        pestana(nombre_pestana).update(
            range_name=celda, values=[[valor]], value_input_option="USER_ENTERED"
        )
        return f"{nombre_pestana}!{celda} = {valor}"
    except Exception as e:
        return f"Error: {e}"


def anadir_fila(nombre_pestana: str, valores: list[str]) -> str:
    """Añade una fila nueva al final de una pestaña, en el orden de sus columnas."""
    try:
        pestana(nombre_pestana).append_row(valores, value_input_option="USER_ENTERED")
        return f"Fila añadida en {nombre_pestana}."
    except Exception as e:
        return f"Error: {e}"


def borrar_fila(nombre_pestana: str, numero_fila: int) -> str:
    """Borra una fila de una pestaña (la fila 1 son los encabezados; no la borres)."""
    try:
        if numero_fila < 2:
            return "No borro la fila de encabezados."
        pestana(nombre_pestana).delete_rows(numero_fila)
        return f"Fila {numero_fila} de {nombre_pestana} borrada."
    except Exception as e:
        return f"Error: {e}"


def crear_pestana(nombre: str, encabezados: list[str]) -> str:
    """Crea una pestaña nueva con los encabezados indicados en la fila 1."""
    try:
        hoja = obtener_libro().add_worksheet(title=nombre, rows=1000, cols=max(len(encabezados), 10))
        if encabezados:
            hoja.append_row(encabezados)
            hoja.format("1:1", {"textFormat": {"bold": True}})
            hoja.freeze(rows=1)
        return f"Pestaña '{nombre}' creada."
    except Exception as e:
        return f"Error: {e}"


HERRAMIENTAS = [listar_pestanas, leer_pestana, escribir_celda, anadir_fila, borrar_fila, crear_pestana]

INSTRUCCIONES = f"""Eres el asistente que organiza un pequeño negocio de dos socios: canales de
YouTube y TikTok de curiosidades (el principal se llama CurioBet) cuyos ingresos servirán para
financiar un negocio de dropshipping. Toda la información está en un Google Sheet con estas pestañas:

- Contenido: un vídeo por fila. Estado debe ser uno de: Idea, Guion, Grabado, Editado, Publicado.
- Métricas: un registro por canal, plataforma y semana.
- Finanzas: un movimiento por fila. Tipo es "Ingreso" o "Gasto". Importe siempre positivo y sin el símbolo €.
- Productos: ideas de productos para dropshipping. En Margen escribe la fórmula =D{{fila}}-C{{fila}}.

Reglas:
- Hoy es {date.today().isoformat()}. Si el usuario no da fecha, usa la de hoy en formato AAAA-MM-DD.
- Antes de modificar una pestaña, léela para saber sus columnas y en qué fila está cada cosa.
- Al añadir filas, respeta el orden exacto de las columnas y deja vacío lo que no sepas.
- Si no tienes claro en qué pestaña va algo, usa listar_pestanas o pregunta.
- Para totales o resúmenes, lee la pestaña y calcula tú el resultado.
- Responde en español, breve, confirmando qué has cambiado y en qué pestaña."""


def enviar(texto: str) -> str:
    """Manda el mensaje a la IA, con reintentos si Google está saturado."""
    for intento in range(1, 4):
        try:
            return st.session_state.chat.send_message(texto).text or "Hecho."
        except Exception as e:
            saturado = "503" in str(e) or "UNAVAILABLE" in str(e)
            if saturado and intento < 3:
                time.sleep(10)
            else:
                return f"Ha habido un error: {e}"


def a_numero(v):
    try:
        return float(str(v).replace("€", "").replace(",", ".").strip())
    except ValueError:
        return 0.0


# ---------- Página web ----------

st.set_page_config(page_title="Bot del negocio", page_icon="📊", layout="wide")
st.title("📊 Bot del negocio")

if "chat" not in st.session_state:
    clave = st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    st.session_state.client = genai.Client(api_key=clave)
    st.session_state.chat = st.session_state.client.chats.create(
        model=MODELO,
        config=types.GenerateContentConfig(tools=HERRAMIENTAS, system_instruction=INSTRUCCIONES),
    )
    st.session_state.mensajes = []

# Barra lateral: selector de pestaña, tabla, resumen de finanzas y descarga
with st.sidebar:
    st.header("Tu hoja")
    try:
        preparar_plantillas()
        libro = obtener_libro()
        hojas = libro.worksheets()
        nombres = [h.title for h in hojas]
        elegida = st.selectbox("Pestaña", nombres,
                               index=nombres.index("Contenido") if "Contenido" in nombres else 0)
        filas = pestana(elegida).get_all_values()

        if len(filas) > 1:
            df = pd.DataFrame(filas[1:], columns=[c or f"Col{i + 1}" for i, c in enumerate(filas[0])])
            df.index = range(2, len(df) + 2)  # coincide con el número de fila del Sheet
            st.dataframe(df, use_container_width=True)
        else:
            st.info("Esta pestaña aún no tiene datos.")

        if elegida == "Finanzas" and len(filas) > 1:
            ingresos = sum(a_numero(f[3]) for f in filas[1:] if len(f) > 3 and f[1].lower() == "ingreso")
            gastos = sum(a_numero(f[3]) for f in filas[1:] if len(f) > 3 and f[1].lower() == "gasto")
            c1, c2, c3 = st.columns(3)
            c1.metric("Ingresos", f"{ingresos:.2f} €")
            c2.metric("Gastos", f"{gastos:.2f} €")
            c3.metric("Balance", f"{ingresos - gastos:.2f} €")

        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            for h in hojas:
                datos = h.get_all_values()
                pd.DataFrame(datos).to_excel(writer, sheet_name=h.title[:31], index=False, header=False)
        st.download_button("⬇️ Descargar todo como Excel", buffer.getvalue(), file_name="negocio.xlsx")
        st.link_button("Abrir en Google Sheets", st.secrets["SHEET_URL"])

    except gspread.exceptions.SpreadsheetNotFound:
        st.error(
            "No encuentro la hoja. Comparte tu Google Sheet con el correo del robot "
            "(client_email del .json) como Editor, y revisa que SHEET_URL sea correcta."
        )
    except KeyError as e:
        st.error(f"Falta este dato en los Secrets de Streamlit: {e}")
    except json.JSONDecodeError:
        st.error("GCP_JSON no es válido: pega el .json completo, de { a }, entre ''' y '''.")
    except Exception as e:
        st.error(f"No puedo abrir la hoja ({type(e).__name__}): {e}")

# Historial del chat
for m in st.session_state.mensajes:
    with st.chat_message(m["rol"]):
        st.markdown(m["texto"])

# Caja para escribir
if texto := st.chat_input("Ej.: apunta en finanzas que hemos gastado 5 € en música"):
    st.session_state.mensajes.append({"rol": "user", "texto": texto})
    with st.chat_message("user"):
        st.markdown(texto)
    with st.chat_message("assistant"):
        with st.spinner("Pensando..."):
            respuesta = enviar(texto)
        st.markdown(respuesta)
    st.session_state.mensajes.append({"rol": "assistant", "texto": respuesta})
    st.rerun()  # recarga para que la tabla lateral muestre los cambios
