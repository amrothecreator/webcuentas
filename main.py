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

# VALOR DE LA CUOTA FIJO
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
                
                # Lógica para deuda y extras
                # Columna D y E según mes
                if mes == "marzo":
                    col_recargo = fila[3].strip().lower() if len(fila) > 3 else ""
                elif mes == "abril":
                    col_d = fila[3].strip().lower() if len(fila) > 3 else ""
                    col_e = fila[4].strip().lower() if len(fila) > 4 else ""
                    # En abril, la deuda está solo en la E
                    col_recargo = col_e
                else:
                    col_recargo = fila[3].strip().lower() if len(fila) > 3 else ""
                
                # Detectar deuda de 500 pendiente (solo si dice "debe")
                deuda_extra = 0
                if "debe" in col_recargo:
                    deuda_extra = 500
                
                # Extras manuales: solo en abril, si es un pago claro
                extra_manual = 0
                if mes == "abril":
                    # Solo sumar a la deuda si está pendiente el mes
                    # El 300 listo ya fue pagado, no es deuda, solo lo sumamos si el mes está pendiente? No, no es deuda.
                    # En el cálculo de deuda solo contamos cuota pendiente + deuda extra.
                    # El 300 listo no es deuda porque ya se pagó.
                    pass
                
                # Recargo automático
                recargo_automatico = 0
                meses_pendientes = 0
                if estado != "PAGADO":
                    meses_pendientes += 1
                    if mes_num < mes_actual and mes_num <= 6:
                        recargo_automatico = 500
                
                # Cálculo de la deuda total
                if estado != "PAGADO":
                    deuda_total = (meses_pendientes * VALOR_CUOTA) + recargo_automatico + deuda_extra
                else:
                    deuda_total = deuda_extra  # Solo lo que quedó pendiente
                
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
                    
                    # ABRIL: condicion estricta
                    if mes == "abril":
                        col_d = fila[3].strip().lower() if len(fila) > 3 else ""
                        col_e = fila[4].strip().lower() if len(fila) > 4 else ""
                        
                        # Sumar 300 solo si dice exactamente "300 listo"
                        if "300 listo" in col_d:
                            monto += 300
                        # Sumar 500 solo si dice exactamente "500 pagado"
                        if "500 pagado" in col_e:
                            monto += 500
                    
                    # MARZO: recargo 500 solo si dice "500" y no "debe"
                    elif mes == "marzo":
                        col_d = fila[3].strip().lower() if len(fila) > 3 else ""
                        if "500" in col_d and "debe" not in col_d:
                            monto += 500
                    
                    # MAYO A OCTUBRE (solo hasta junio para recargo)
                    else:
                        col_d = fila[3].strip().lower() if len(fila) > 3 else ""
                        if mes_num <= 6:
                            if "500" in col_d and "debe" not in col_d:
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
            return {"mensaje": f"{cambio.nombre} actualizado en {cambio.mes}"}
    
    raise HTTPException(status_code=404, detail="Persona no encontrada")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
