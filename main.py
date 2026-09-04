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
VALOR_CUOTA = 2000  # ¡Cámbialo por el valor real de tu cuota!

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

MESES = ["marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre"]
MESES_NUM = {"marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10}

def conectar():
    creds_dict = json.loads(CREDENTIALS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID)

class LoginData(BaseModel):
    password: str

class Cambio(BaseModel):
    nombre: str
    mes: str
    password: str
    metodo: str

class NombreMes(BaseModel):
    nombre: str
    mes: str
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
            if not hoja: continue
                
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
                deuda_extra = 0
                meses_pendientes = 0

                if estado != "PAGADO":
                    meses_pendientes += 1
                    if mes_num < mes_actual and mes_num <= 6:
                        recargo_automatico = 500
                    if len(fila) > 3 and "debe" in fila[3].lower() and mes_num <= 6:
                        deuda_extra += 500
                    
                if nombre not in datos:
                    datos[nombre] = {}
                
                deuda_total = (meses_pendientes * VALOR_CUOTA) + recargo_automatico + deuda_extra + extra_manual
                
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

@app.get("/api/recaudacion")
def obtener_recaudacion():
    sh = conectar()
    todas_las_hojas = {hoja.title.lower(): hoja for hoja in sh.worksheets()}
    
    recaudacion = {}
    for mes in MESES:
        total_transferencia = 0
        try:
            hoja = todas_las_hojas.get(mes)
            if not hoja: continue
                
            valores = hoja.get_all_values()
            for fila in valores[1:]:
                nombre = fila[0].strip()
                if not nombre: continue
                
                pagado = any("PAGADO" in str(celda).upper() for celda in fila)
                es_transferencia = any("transferencia" in str(celda).lower() for celda in fila)
                
                if pagado and es_transferencia:
                    monto = VALOR_CUOTA
                    if mes == "marzo":
                        monto += 500
                    elif mes == "abril":
                        monto += 300
                    
                    total_transferencia += monto
                    
            recaudacion[mes] = total_transferencia
        except Exception as e:
            print(f"Error calculando recaudación para {mes}: {e}")
    
    return {"recaudacion": recaudacion}

# NUEVO: Pagar deuda de atraso específica (ej. pagar los $500 de marzo)
@app.post("/api/pagar_deuda")
def pagar_deuda(data: NombreMes):
    if data.password != PASSWORD_ADMIN:
        raise HTTPException(status_code=401, detail="Contraseña incorrecta")
    
    sh = conectar()
    mes = data.mes.lower()
    hoja = None
    for worksheet in sh.worksheets():
        if worksheet.title.lower() == mes:
            hoja = worksheet
            break
    if not hoja:
        raise HTTPException(status_code=404, detail="Pestaña no encontrada")
    
    valores = hoja.get_all_values()
    for i, fila in enumerate(valores, start=1):
        if fila[0].strip() == data.nombre:
            # Limpiar la celda de deuda según el mes
            # Marzo: col D (4), Abril: col E (5), Mayo-Oct: col D (4)
            col_deuda = 5 if mes == "abril" else 4
            hoja.update_cell(i, col_deuda, "")  # Borrar el "debe 500" o "500"
            return {"mensaje": f"Deuda de {data.nombre} en {data.mes} saldada."}
    
    raise HTTPException(status_code=404, detail="Persona no encontrada")

# NUEVO: Deshacer pago (volver a estado pendiente)
@app.post("/api/deshacer_pago")
def deshacer_pago(data: NombreMes):
    if data.password != PASSWORD_ADMIN:
        raise HTTPException(status_code=401, detail="Contraseña incorrecta")
    
    sh = conectar()
    mes = data.mes.lower()
    hoja = None
    for worksheet in sh.worksheets():
        if worksheet.title.lower() == mes:
            hoja = worksheet
            break
    if not hoja:
        raise HTTPException(status_code=404, detail="Pestaña no encontrada")
    
    valores = hoja.get_all_values()
    for i, fila in enumerate(valores, start=1):
        if fila[0].strip() == data.nombre:
            # Desmarcar pago (B vacío)
            hoja.update_cell(i, 2, "")
            # Limpiar método de pago (C vacío)
            hoja.update_cell(i, 3, "")
            # Restaurar deuda si es un mes anterior a junio
            if MESES_NUM.get(mes, 0) <= 6:
                col_deuda = 5 if mes == "abril" else 4
                hoja.update_cell(i, col_deuda, "debe 500")
            return {"mensaje": f"Pago de {data.nombre} en {data.mes} deshecho."}
    
    raise HTTPException(status_code=404, detail="Persona no encontrada")

# NUEVO: Actualizar pagos de septiembre (pagar deudas atrasadas automáticamente)
@app.post("/api/actualizar_pagos")
def actualizar_pagos(data: LoginData):
    if data.password != PASSWORD_ADMIN:
        raise HTTPException(status_code=401, detail="Contraseña incorrecta")
    
    # Solo ejecutar si hoy es mayor o igual al 1 de septiembre (ej. 2026-09-04)
    hoy = date.today()
    fecha_limite = date(2026, 9, 1)
    
    if hoy < fecha_limite:
        return {"mensaje": "Aún no es 1 de septiembre."}
    
    sh = conectar()
    todas_las_hojas = {hoja.title.lower(): hoja for hoja in sh.worksheets()}
    actualizados = 0
    
    for mes in MESES:
        hoja = todas_las_hojas.get(mes)
        if not hoja: continue
        
        valores = hoja.get_all_values()
        for i, fila in enumerate(valores, start=1):
            nombre = fila[0].strip()
            if not nombre: continue
            
            # Si está pagado
            pagado = any("PAGADO" in str(celda).upper() for celda in fila)
            if pagado:
                # Buscar y limpiar cualquier deuda en la columna D o E
                col_deuda = 5 if mes == "abril" else 4
                if len(fila) > col_deuda - 1 and ("debe" in str(fila[col_deuda - 1]).lower() or "500" in str(fila[col_deuda - 1])):
                    hoja.update_cell(i, col_deuda, "")
                    actualizados += 1
    
    return {"mensaje": f"Actualización completada. {actualizados} deudas saldadas."}

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
            return {"mensaje": f"{cambio.nombre} marcado como PAGADO en {cambio.mes}"}
    
    raise HTTPException(status_code=404, detail="Persona no encontrada")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
