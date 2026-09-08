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

# 🔴 CAMBIA ESTE VALOR POR EL DE TU CUOTA MENSUAL (ej: 2000, 10000, etc.)
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
                
                # Detectar si el mes está pagado (en cualquier columna)
                pagado = any("PAGADO" in str(celda).upper() for celda in fila)
                estado = "PAGADO" if pagado else ""
                
                # Detectar método
                metodo = ""
                if any("transferencia" in str(celda).lower() for celda in fila):
                    metodo = "transferencia"
                elif any("efectivo" in str(celda).lower() for celda in fila):
                    metodo = "efectivo"
                
                # Extras manuales de marzo y abril (se pagan con el mes)
                extra_manual = 0
                if mes == "marzo":
                    extra_manual = 500 if len(fila) > 3 and "500" in fila[3] else 0
                elif mes == "abril":
                    extra_manual = 300 if len(fila) > 3 and "300" in fila[3] else 0
                    extra_manual += 500 if len(fila) > 4 and "500" in fila[4] else 0

                # 🔴 CORRECCIÓN CLAVE: Detectar deuda de 500 pendiente en la columna D
                # (Ya sea "debe 500" o simplemente "500", sin importar si el mes está pagado)
                deuda_extra = 0
                col_d = fila[3].strip().lower() if len(fila) > 3 else ""
                if "500" in col_d and "pagado" not in col_d:
                    deuda_extra = 500

                # Recargo automático SOLO si el mes está pendiente y es anterior al actual y <= junio
                recargo_automatico = 0
                meses_pendientes = 0
                if estado != "PAGADO":
                    meses_pendientes += 1
                    if mes_num < mes_actual and mes_num <= 6:
                        recargo_automatico = 500
                
                # Cálculo de la deuda total:
                # - Si el mes NO está pagado: cuota + recargo + deuda_extra
                # - Si el mes SÍ está pagado pero tiene deuda_extra: solo deuda_extra
                if estado != "PAGADO":
                    deuda_total = (meses_pendientes * VALOR_CUOTA) + recargo_automatico + deuda_extra + extra_manual
                else:
                    deuda_total = deuda_extra  # Solo lo que quedó pendiente del recargo
                
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
        try:
            hoja = todas_las_hojas.get(mes)
            if not hoja:
                continue
            valores = hoja.get_all_values()
            
            for fila in valores[1:]:
                nombre = fila[0].strip()
                if not nombre: continue
                
                es_pagado = any("PAGADO" in str(celda).upper() for celda in fila)
                es_transferencia = any("transferencia" in str(celda).lower() for celda in fila)
                
                if es_pagado and es_transferencia:
                    monto = VALOR_CUOTA
                    
                    if mes == "marzo":
                        monto += 500
                    elif mes == "abril":
                        monto += 300
                        if len(fila) > 4 and "500" in fila[4]:
                            monto += 500
                    else: 
                        # Si la columna D NO tiene "500" ni "debe", significa que el recargo fue pagado
                        col_d = fila[3].strip().lower() if len(fila) > 3 else ""
                        if "500" not in col_d and "debe" not in col_d:
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
            # 1. Marcar el mes como pagado y método
            hoja.update_cell(i, 2, "PAGADO")
            hoja.update_cell(i, 3, cambio.metodo)
            
            # 2. Solo si se quiere pagar la deuda, se limpia la columna D
            if cambio.pagar_deuda:
                hoja.update_cell(i, 4, "")
                
            return {"mensaje": f"{cambio.nombre} actualizado en {cambio.mes}"}
    
    raise HTTPException(status_code=404, detail="Persona no encontrada")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
