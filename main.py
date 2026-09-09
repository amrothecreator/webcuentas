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

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# CONFIGURACIÓN
SHEET_ID = os.getenv("SHEET_ID")
PASSWORD_ADMIN = os.getenv("PASSWORD_ADMIN")
CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")

# 🔴 CAMBIA ESTE VALOR POR EL DE TU CUOTA MENSUAL (ej: 2000, 2500, 10000, etc.)
VALOR_CUOTA = 2000 

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

MESES = ["marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre"]

MESES_NUM = {
    "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, 
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10
}

def conectar():
    creds_dict = json.loads(CREDENTIALS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID)

class Cambio(BaseModel):
    nombre: str
    mes: str
    password: str
    metodo: str
    pagar_deuda: bool = False

class LoginData(BaseModel):
    password: str

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
    sh = conectar()
    mes_actual = date.today().month
    
    todas_las_hojas = {hoja.title.lower(): hoja for hoja in sh.worksheets()}
    
    datos = {}
    for mes in MESES:
        try:
            hoja = todas_las_hojas.get(mes)
            if not hoja:
                print(f"Error: No se encontró la pestaña para {mes}.")
                continue
                
            valores = hoja.get_all_values()
            mes_num = MESES_NUM[mes]
            
            for fila in valores[1:]:
                nombre = fila[0].strip()
                if not nombre: continue
                
                pagado = any("PAGADO" in str(celda).upper() for celda in fila)
                estado = "PAGADO" if pagado else ""
                
                # Leer método SOLO de la columna C
                metodo = ""
                if len(fila) > 2:
                    metodo = fila[2].strip().lower()
                
                # Extras manuales (300 en abril, etc.)
                extra_manual = 0
                if mes == "abril" and len(fila) > 3 and "300" in fila[3]:
                    extra_manual = 300
                
                # Determinar la columna del recargo (500) según el mes
                if mes == "marzo":
                    col_recargo = fila[3].strip().lower() if len(fila) > 3 else ""
                elif mes == "abril":
                    col_recargo = fila[4].strip().lower() if len(fila) > 4 else ""
                else:
                    col_recargo = fila[3].strip().lower() if len(fila) > 3 else ""
                
                # 🔴 LÓGICA CORRECTA PARA CALCULAR DEUDA
                deuda_total = 0
                recargo_automatico = 0
                deuda_extra = 0
                
                if estado != "PAGADO":
                    # Debe la cuota del mes
                    deuda_total += VALOR_CUOTA
                    
                    # Debe el recargo si el mes es <= junio y ya pasó
                    if mes_num <= 6 and mes_num < mes_actual:
                        recargo_automatico = 500
                        deuda_total += 500
                    
                    # Sumar extras manuales (300 de abril)
                    deuda_total += extra_manual
                    
                else:
                    # Mes pagado, revisar si dejó deuda de 500
                    if "debe" in col_recargo:
                        deuda_extra = 500
                        deuda_total += 500
                
                if nombre not in datos:
                    datos[nombre] = {}
                
                datos[nombre][mes] = {
                    "estado": estado or "PENDIENTE",
                    "metodo": metodo,
                    "extra": extra_manual, 
                    "deuda_extra": deuda_extra,
                    "recargo_automatico": recargo_automatico, 
                    "deuda": deuda_total 
                }
        except Exception as e:
            print(f"Error leyendo {mes}: {e}")
    return datos

@app.get("/api/recaudacion")
def obtener_recaudacion():
    sh = conectar()
    todas_las_hojas = {hoja.title.lower(): hoja for hoja in sh.worksheets()}
    recaudacion = {}
    
    for mes in MESES:
        total_transferencia = 0
        mes_num = MESES_NUM[mes]
        try:
            hoja = todas_las_hojas.get(mes)
            if not hoja:
                continue
            valores = hoja.get_all_values()
            
            for fila in valores[1:]:
                nombre = fila[0].strip()
                if not nombre: continue
                
                es_pagado = any("PAGADO" in str(celda).upper() for celda in fila)
                metodo = fila[2].strip().lower() if len(fila) > 2 else ""
                es_transferencia = metodo == "transferencia"
                
                if es_pagado and es_transferencia:
                    monto = VALOR_CUOTA
                    
                    # Extra fijo de abril (300)
                    if mes == "abril" and len(fila) > 3 and "300" in fila[3]:
                        monto += 300
                    
                    # Determinar columna del recargo
                    if mes == "marzo":
                        col_recargo = fila[3].strip().lower() if len(fila) > 3 else ""
                    elif mes == "abril":
                        col_recargo = fila[4].strip().lower() if len(fila) > 4 else ""
                    else:
                        col_recargo = fila[3].strip().lower() if len(fila) > 3 else ""
                    
                    # 🔴 SOLO SUMAR RECARGO DE 500 EN MESES <= JUNIO
                    if mes_num <= 6:
                        if col_recargo and "debe" not in col_recargo and "500" in col_recargo:
                            monto += 500
                    
                    total_transferencia += monto
                    
            recaudacion[mes] = total_transferencia
        except Exception as e:
            print(f"Error calculando recaudación para {mes}: {e}")
    return {"recaudacion": recaudacion}

@app.post("/api/marcar_pagado")
def marcar_pagado(cambio: Cambio):
    if cambio.password != PASSWORD_ADMIN:
        raise HTTPException(status_code=401, detail="Contraseña incorrecta")
    
    sh = conectar()
    mes = cambio.mes.lower()
    hoja = None
    for worksheet in sh.worksheets():
        if worksheet.title.lower() == mes:
            hoja = worksheet
            break
    
    if not hoja:
        raise HTTPException(status_code=404, detail="Pestaña no encontrada")
    
    valores = hoja.get_all_values()
    
    for i, fila in enumerate(valores, start=1):
        if fila[0].strip() == cambio.nombre:
            hoja.update_cell(i, 2, "PAGADO")
            hoja.update_cell(i, 3, cambio.metodo)
            if cambio.pagar_deuda:
                hoja.update_cell(i, 4, "")
            return {"mensaje": f"{cambio.nombre} actualiz$20000ado en {cambio.mes}"}
    
    raise HTTPException(status_code=404, detail="Persona no encontrada")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
