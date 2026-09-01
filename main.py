import os
import json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import gspread
from google.oauth2.service_account import Credentials
from datetime import date

app = FastAPI()

# Permitir conexiones desde cualquier dispositivo
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# CONFIGURACIÓN DESDE VARIABLES DE ENTORNO (Render)
SHEET_ID = os.getenv("SHEET_ID")
PASSWORD_ADMIN = os.getenv("PASSWORD_ADMIN")
CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

MESES_NUM = {
    "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, 
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10
}

# Conectar con Google Sheets usando las credenciales desde la variable de entorno
def conectar():
    creds_dict = json.loads(CREDENTIALS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID)

class Cambio(BaseModel):
    nombre: str
    mes: str
    password: str
    metodo: str  # Nuevo campo para "efectivo" o "transferencia"

# Validar contraseña
from pydantic import BaseModel

# Asegúrate de tener este modelo definido
class LoginData(BaseModel):
    password: str

@app.post("/api/login")
def login(data: LoginData):
    if data.password != PASSWORD_ADMIN:
        raise HTTPException(status_code=401, detail="Contraseña incorrecta")
    return {"ok": True}

# Servir el archivo index.html cuando entren a la raíz "/"
@app.get("/")
def read_index():
    return FileResponse("index.html")

@app.get("/api/datos")
def obtener_datos():
    sh = conectar()
    meses = ["marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre"]
    mes_actual = date.today().month
    
    datos = {}
    for mes in meses:
        try:
            hoja = sh.worksheet(mes) 
            valores = hoja.get_all_values()
            mes_num = MESES_NUM[mes]
            
            for fila in valores[1:]:
                nombre = fila[0].strip()
                if not nombre: continue
                
                pagado = any("PAGADO" in str(celda).upper() for celda in fila)
                estado = "PAGADO" if pagado else ""
                
                metodo = ""
                if any("transferencia" in str(celda).lower() for celda in fila):
                    metodo = "transferencia"
                elif any("efectivo" in str(celda).lower() for celda in fila):
                    metodo = "efectivo"
                
                extra_manual = 0
                if mes == "marzo":
                    extra_manual = 500 if len(fila) > 3 and "500" in fila[3] else 0
                elif mes == "abril":
                    extra_manual = 300 if len(fila) > 3 and "300" in fila[3] else 0
                    extra_manual += 500 if len(fila) > 4 and "500" in fila[4] else 0

                recargo_automatico = 0
                deuda_total = 0

                if estado != "PAGADO":
                    if mes_num < mes_actual:
                        recargo_automatico = 500
                    if len(fila) > 3 and "debe" in fila[3].lower():
                        deuda_total += 500
                    deuda_total += recargo_automatico + extra_manual
                
                if nombre not in datos:
                    datos[nombre] = {}
                
                datos[nombre][mes] = {
                    "estado": estado or "PENDIENTE",
                    "metodo": metodo,
                    "extra": extra_manual, 
                    "recargo_automatico": recargo_automatico, 
                    "deuda": deuda_total 
                }
        except Exception as e:
            print(f"Error leyendo {mes}: {e}")
    return datos

@app.post("/api/marcar_pagado")
def marcar_pagado(cambio: Cambio):
    if cambio.password != PASSWORD_ADMIN:
        raise HTTPException(status_code=401, detail="Contraseña incorrecta")
    
    sh = conectar()
    mes = cambio.mes.lower()
    hoja = sh.worksheet(mes) 
    valores = hoja.get_all_values()
    
    for i, fila in enumerate(valores, start=1):
        if fila[0].strip() == cambio.nombre:
            # Actualizar columna B (Estado) a PAGADO
            hoja.update_cell(i, 2, "PAGADO")
            # Actualizar columna C (Método) con efectivo o transferencia
            hoja.update_cell(i, 3, cambio.metodo)
            return {"mensaje": f"{cambio.nombre} marcado como PAGADO en {cambio.mes}"}
    
    raise HTTPException(status_code=404, detail="Persona no encontrada")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
