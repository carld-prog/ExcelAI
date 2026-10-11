"""Tarea automática: apunta las métricas de YouTube en el Google Sheet.

La ejecuta GitHub Actions cada lunes (ver .github/workflows/metricas.yml).
Lee los datos secretos de las variables de entorno que le pasa GitHub.
"""
import json
import os
import sys

import gspread

from metricas import actualizar_youtube, lista_canales


def main():
    credenciales = json.loads(os.environ["GCP_JSON"])
    libro = gspread.service_account_from_dict(credenciales).open_by_url(os.environ["SHEET_URL"])
    canales = lista_canales(os.environ.get("YOUTUBE_CANALES") or "@curiobet")

    resultado = actualizar_youtube(libro, os.environ["YOUTUBE_API_KEY"], canales)
    print(resultado)
    if ": error," in resultado:
        sys.exit(1)  # GitHub marca la ejecución en rojo y te avisa por correo


if __name__ == "__main__":
    main()
