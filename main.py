import os
import re
import json
import time
import threading
from datetime import datetime
from typing import List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import gspread
from google.oauth2.service_account import Credentials

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("America/Santiago")
except Exception:
    TZ = None

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ---------------- CONFIGURACIÓN ----------------
SHEET_ID = os.getenv("SHEET_ID")
PASSWORD_ADMIN = os.getenv("PASSWORD_ADMIN")
CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")

VALOR_CUOTA = 2000
RECARGO = 500
CACHE_TTL = 30  # segundos que se reutiliza la lectura de Google Sheets

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
MESES = ["marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre"]
MESES_NUM = {
    "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10,
}

# ---------------- CONEXIÓN Y CACHÉ ----------------
_lock = threading.Lock()          # una sola escritura a la vez
_estado = {"sh": None, "titulos": None, "hojas": None, "t": 0}


def conectar(forzar=False):
    """Reutiliza la conexión en vez de autenticarse en cada petición."""
    if _estado["sh"] is None or forzar:
        creds = Credentials.from_service_account_info(json.loads(CREDENTIALS_JSON), scopes=SCOPES)
        _estado["sh"] = gspread.authorize(creds).open_by_key(SHEET_ID)
        _estado["titulos"] = None
    return _estado["sh"]


def titulos(sh):
    if _estado["titulos"] is None:
        _estado["titulos"] = {ws.title.lower(): ws.title for ws in sh.worksheets()}
    return _estado["titulos"]


def leer_hojas(forzar=False):
    """Lee las 8 pestañas con UNA sola llamada a la API de Google."""
    if not forzar and _estado["hojas"] is not None and time.time() - _estado["t"] < CACHE_TTL:
        return _estado["hojas"]

    for intento in range(2):
        try:
            sh = conectar(forzar=intento > 0)
            tit = titulos(sh)
            meses_ok = [m for m in MESES if m in tit]
            rangos = [f"'{tit[m]}'!A:E" for m in meses_ok]
            resp = sh.values_batch_get(rangos)
            hojas = {}
            for mes, vr in zip(meses_ok, resp.get("valueRanges", [])):
                hojas[mes] = vr.get("values", [])
            _estado["hojas"] = hojas
            _estado["t"] = time.time()
            return hojas
        except Exception as e:
            print(f"Error leyendo Google Sheets (intento {intento + 1}): {e}")
    raise HTTPException(status_code=503, detail="No se pudo leer Google Sheets")


def mes_hoy():
    return (datetime.now(TZ) if TZ else datetime.now()).month


# ---------------- LÓGICA DE UNA FILA ----------------
def celda(fila, i):
    return fila[i].strip().lower() if len(fila) > i else ""


def indice_recargo(mes):
    # Abril: columna E (índice 4). Resto: columna D (índice 3).
    return 4 if mes == "abril" else 3


def analizar_fila(mes, fila, mes_actual):
    mes_num = MESES_NUM[mes]
    pagado = "pagado" in celda(fila, 1)           # solo la columna B
    metodo = celda(fila, 2)
    texto = celda(fila, indice_recargo(mes))
    # Los recargos existen SOLO de marzo a junio. Cualquier "debe" en otros meses se ignora.
    aplica_recargo = mes_num <= 6
    # En la hoja un recargo sin pagar puede decir "debe 500" o "500 pendiente".
    texto_pendiente = "debe" in texto or "pendiente" in texto
    debe = aplica_recargo and texto_pendiente
    recargo_pagado = aplica_recargo and ("500" in texto) and not texto_pendiente
    atrasado = aplica_recargo and mes_num < mes_actual
    # Si la celda dice "debe 1000", se usa ese monto; si no trae número, 500.
    m = re.search(r"\d[\d.]*", texto)
    monto_debe = int(m.group().replace(".", "") or 0) if (debe and m) else RECARGO

    # El recargo pendiente se cuenta UNA sola vez:
    # ya sea porque la celda dice "debe", o porque el mes está atrasado y sin pagar.
    pendiente = debe or (not pagado and atrasado and not recargo_pagado)
    recargo_pend = (monto_debe or RECARGO) if pendiente else 0

    return {
        "pagado": pagado,
        "metodo": metodo,
        "debe": debe,
        "recargo_pagado": recargo_pagado,
        "atrasado": atrasado,
        "recargo_pend": recargo_pend,
        "deuda": (0 if pagado else VALOR_CUOTA) + recargo_pend,
    }


# ---------------- MODELOS ----------------
class LoginData(BaseModel):
    password: str


class Item(BaseModel):
    mes: str
    cuota: bool = False
    recargo: bool = False


class Lote(BaseModel):
    nombre: str
    password: str
    metodo: str = ""
    items: List[Item]


# ---------------- ENDPOINTS ----------------
@app.post("/api/login")
def login(data: LoginData):
    if data.password != PASSWORD_ADMIN:
        raise HTTPException(status_code=401, detail="Contraseña incorrecta")
    return {"ok": True}


@app.get("/")
def read_index():
    return FileResponse("index.html")


@app.get("/api/datos")
def obtener_datos():
    hojas = leer_hojas()
    mes_actual = mes_hoy()
    datos = {}
    for mes in MESES:
        for fila in hojas.get(mes, [])[1:]:
            nombre = fila[0].strip() if fila else ""
            if not nombre:
                continue
            a = analizar_fila(mes, fila, mes_actual)
            datos.setdefault(nombre, {})[mes] = {
                "estado": "PAGADO" if a["pagado"] else "PENDIENTE",
                "metodo": a["metodo"],
                "atrasado": a["atrasado"],
                "recargo_pendiente": a["recargo_pend"],
                "recargo_pagado": a["recargo_pagado"],
                "deuda": a["deuda"],
            }
    return datos


@app.get("/api/recaudacion")
def obtener_recaudacion():
    hojas = leer_hojas()
    recaudacion = {}
    for mes in MESES:
        if mes not in hojas:
            continue
        mes_num = MESES_NUM[mes]
        total = 0
        for fila in hojas[mes][1:]:
            nombre = fila[0].strip() if fila else ""
            if not nombre:
                continue
            if not ("pagado" in celda(fila, 1) and celda(fila, 2) == "transferencia"):
                continue
            monto = VALOR_CUOTA
            col_d = celda(fila, 3)
            col_e = celda(fila, 4)
            if mes == "abril":
                if "300 listo" in col_d and "efectivo" not in col_d and "no transf" not in col_d:
                    monto += 300
                if "500 pagado" in col_e:
                    monto += 500
            elif mes_num <= 6:
                if "500" in col_d and "debe" not in col_d and "pendiente" not in col_d:
                    monto += 500
            total += monto
        recaudacion[mes] = total
    return {"recaudacion": recaudacion}


@app.post("/api/pagar_lote")
def pagar_lote(lote: Lote):
    if lote.password != PASSWORD_ADMIN:
        raise HTTPException(status_code=401, detail="Contraseña incorrecta")
    if not lote.items:
        raise HTTPException(status_code=400, detail="No hay nada seleccionado")
    if any(i.cuota for i in lote.items) and lote.metodo not in ("efectivo", "transferencia"):
        raise HTTPException(status_code=400, detail="Método de pago inválido")

    with _lock:
        hojas = leer_hojas(forzar=True)   # datos frescos, 1 sola llamada
        tit = titulos(conectar())
        mes_actual = mes_hoy()
        data = []

        for item in lote.items:
            mes = item.mes.lower()
            if mes not in MESES_NUM or mes not in hojas:
                raise HTTPException(status_code=404, detail=f"Pestaña no encontrada: {item.mes}")

            filas = hojas[mes]
            idx = next((i for i, f in enumerate(filas) if i > 0 and f and f[0].strip() == lote.nombre), None)
            if idx is None:
                raise HTTPException(status_code=404, detail=f"{lote.nombre} no está en {mes}")

            fila = filas[idx]
            row = idx + 1
            t = tit[mes]
            a = analizar_fila(mes, fila, mes_actual)
            letra = "E" if mes == "abril" else "D"
            texto_pagado = f"{a['recargo_pend']} pagado"

            if item.cuota and not a["pagado"]:
                data.append({"range": f"'{t}'!B{row}:C{row}", "values": [["PAGADO", lote.metodo]]})

            if item.recargo and a["recargo_pend"] > 0:
                data.append({"range": f"'{t}'!{letra}{row}", "values": [[texto_pagado]]})
            elif item.cuota and not a["pagado"] and a["atrasado"] and not a["recargo_pagado"] and not a["debe"]:
                # Se pagó la cuota atrasada pero no el recargo: queda registrado como deuda.
                data.append({"range": f"'{t}'!{letra}{row}", "values": [["500 pendiente"]]})

        if data:
            for intento in range(2):
                try:
                    sh = conectar(forzar=intento > 0)
                    sh.values_batch_update({"valueInputOption": "RAW", "data": data})
                    break
                except Exception as e:
                    print(f"Error escribiendo (intento {intento + 1}): {e}")
                    if intento == 1:
                        raise HTTPException(status_code=502, detail="No se pudo escribir en Google Sheets")
            _estado["hojas"] = None   # invalida la caché

    return {"ok": True, "celdas": len(data)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
