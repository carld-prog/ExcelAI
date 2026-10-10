import io
import json
import os
import time

import gspread
import pandas as pd
import streamlit as st
from google import genai
from google.genai import types

MODELO = "gemini-flash-lite-latest"  # si da problemas, prueba "gemini-flash-latest"


# ---------- Conexión con Google Sheets ----------

@st.cache_resource
def obtener_hoja():
    """Conecta con la hoja de Google Sheets usando la cuenta de servicio."""
    credenciales = json.loads(st.secrets["GCP_JSON"])
    gc = gspread.service_account_from_dict(credenciales)
    return gc.open_by_url(st.secrets["SHEET_URL"]).sheet1


# ---------- Herramientas que la IA puede usar ----------

def leer_hoja() -> str:
    """Devuelve todo el contenido actual de la hoja, fila por fila."""
    filas = obtener_hoja().get_all_values()
    return str(filas) if filas else "La hoja está vacía."


def escribir_celda(celda: str, valor: str) -> str:
    """Escribe un valor en una celda concreta, por ejemplo B3."""
    obtener_hoja().update_acell(celda, valor)
    return f"{celda} = {valor}"


def anadir_fila(valores: list[str]) -> str:
    """Añade una fila nueva al final de la hoja."""
    obtener_hoja().append_row(valores, value_input_option="USER_ENTERED")
    return "Fila añadida."


def borrar_fila(numero_fila: int) -> str:
    """Borra la fila indicada (la fila 1 es la primera)."""
    obtener_hoja().delete_rows(numero_fila)
    return f"Fila {numero_fila} borrada."


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


# ---------- Página web ----------

st.set_page_config(page_title="Bot de Excel", page_icon="📊", layout="wide")
st.title("📊 Bot de Excel")

if "chat" not in st.session_state:
    clave = st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    st.session_state.client = genai.Client(api_key=clave)
    st.session_state.chat = st.session_state.client.chats.create(
        model=MODELO,
        config=types.GenerateContentConfig(
            tools=[leer_hoja, escribir_celda, anadir_fila, borrar_fila],
            system_instruction=(
                "Eres un asistente que gestiona una hoja de cálculo. "
                "Lee siempre la hoja antes de modificarla. "
                "Responde en español y de forma breve, confirmando lo que has cambiado."
            ),
        ),
    )
    st.session_state.mensajes = []

# Barra lateral: vista de la hoja, enlace y descarga
with st.sidebar:
    st.header("Tu hoja")
    try:
        filas = obtener_hoja().get_all_values()
        if filas:
            df = pd.DataFrame(filas)
            df.columns = [chr(65 + i) if i < 26 else f"Col{i + 1}" for i in range(len(df.columns))]
            df.index = range(1, len(df) + 1)
            st.dataframe(df, use_container_width=True)

            buffer = io.BytesIO()
            pd.DataFrame(filas).to_excel(buffer, index=False, header=False)
            st.download_button("⬇️ Descargar como Excel", buffer.getvalue(), file_name="datos.xlsx")
        else:
            st.info("La hoja está vacía. Pídele al bot que cree una tabla.")
        st.link_button("Abrir en Google Sheets", st.secrets["SHEET_URL"])
    except Exception as e:
        st.error(f"No puedo abrir la hoja: {e}")

# Historial del chat
for m in st.session_state.mensajes:
    with st.chat_message(m["rol"]):
        st.markdown(m["texto"])

# Caja para escribir
if texto := st.chat_input("Ej.: crea una tabla con columnas Nombre, Edad y Ciudad"):
    st.session_state.mensajes.append({"rol": "user", "texto": texto})
    with st.chat_message("user"):
        st.markdown(texto)
    with st.chat_message("assistant"):
        with st.spinner("Pensando..."):
            respuesta = enviar(texto)
        st.markdown(respuesta)
    st.session_state.mensajes.append({"rol": "assistant", "texto": respuesta})
    st.rerun()  # recarga para que la tabla lateral muestre los cambios
