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
VALOR_CUOTA = 2000  # 🔴 ¡Cámbialo por el valor real de tu cuota!

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

class PagoDeuda(BaseModel):
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

@app.post("/api/pagar_deuda")
def pagar_deuda(data: PagoDeuda):
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
            col_deuda = 5 if mes == "abril" else 4
            hoja.update_cell(i, col_deuda, "")  # Borrar el "debe 500" o "500"
            # Registrar el método de pago en la columna C
            hoja.update_cell(i, 3, data.metodo)
            return {"mensaje": f"Deuda de {data.nombre} en {data.mes} saldada por {data.metodo}."}
    
    raise HTTPException(status_code=404, detail="Persona no encontrada")

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

@app.post("/api/actualizar_pagos")
def actualizar_pagos(data: LoginData):
    if data.password != PASSWORD_ADMIN:
        raise HTTPException(status_code=401, detail="Contraseña incorrecta")
    
    hoy = date.today()
    fecha_limite = date(2026, 9, 1)
    if hoy < fecha_limite:
        return {"mensaje": "Aún no es 1 de septiembre."}
    
    sh = conectar()
    todas_las_hojas = {hoja.title.lower(): hoja for hoja in sh.worksheets()}
    
    # Leer la hoja de respaldo
    if "respaldo_septiembre" not in todas_las_hojas:
        return {"mensaje": "Error: No existe la hoja 'respaldo_septiembre'."}
    
    hoja_respaldo = todas_las_hojas["respaldo_septiembre"]
    respaldo_valores = hoja_respaldo.get_all_values()
    
    # Crear diccionario de respaldo: {(mes, nombre): estado_antes}
    respaldo = {}
    for fila in respaldo_valores[1:]:  # Saltar encabezado
        if len(fila) < 3: continue
        mes = fila[0].strip().lower()
        nombre = fila[1].strip()
        estado_antes = fila[2].strip().upper()
        respaldo[(mes, nombre)] = estado_antes
    
    actualizados = 0
    
    # Solo trabajamos con los meses que tienen recargo
    meses_con_recargo = ["marzo", "abril", "mayo", "junio"]
    
    for mes in meses_con_recargo:
        hoja = todas_las_hojas.get(mes)
        if not hoja: continue
        
        valores = hoja.get_all_values()
        col_deuda = 5 if mes == "abril" else 4
        
        for i, fila in enumerate(valores, start=1):
            nombre = fila[0].strip()
            if not nombre: continue
            
            estado_actual = fila[1].strip().upper() if len(fila) > 1 else ""
            deuda_celda = fila[col_deuda - 1].strip() if len(fila) >= col_deuda else ""
            
            # Obtener estado antes de septiembre
            estado_antes = respaldo.get((mes, nombre), "")
            
            # Si la celda de deuda ya tiene algo, no hacer nada
            if deuda_celda != "":
                continue
            
            # Lógica principal
            if estado_actual == "PAGADO":
                # Si estaba pagado antes, no hacemos nada (ya pagó todo antes)
                if estado_antes == "PAGADO":
                    continue
                # Si NO estaba pagado antes, entonces pagó después -> "500 pagado"
                else:
                    hoja.update_cell(i, col_deuda, "500 pagado")
                    actualizados += 1
                    
            elif estado_actual == "":
                # Si sigue sin pagar (y no estaba pagado antes tampoco) -> "500 pendiente"
                if estado_antes != "PAGADO":
                    hoja.update_cell(i, col_deuda, "500 pendiente")
                    actualizados += 1
                # Si estaba pagado antes y ahora no, es un error, pero no hacemos nada.
    
    return {"mensaje": f"Actualización completada. {actualizados} recargos actualizados correctamente."}

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
