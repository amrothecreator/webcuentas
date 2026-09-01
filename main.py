from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import gspread
from google.oauth2.service_account import Credentials
from datetime import date

app = FastAPI()

# Permitir que tu página web (frontend) se conecte
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# CONFIGURACIÓN
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
KEY_FILE = "tu_cuenta_servicio.json"
SHEET_ID = "15Anhl6_phj48cFe4i2vC1-GXLIP5RLkiabLGxoxuR-k"
PASSWORD_ADMIN = "1234" 

MESES_NUM = {
    "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, 
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10
}

def conectar():
    creds = Credentials.from_service_account_file(KEY_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID)

class Cambio(BaseModel):
    nombre: str
    mes: str
    password: str

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
                
                # CAMBIO CLAVE: Buscar "PAGADO" en CUALQUIER columna de la fila
                pagado = any("PAGADO" in str(celda).upper() for celda in fila)
                estado = "PAGADO" if pagado else ""
                
                # Buscar método (transferencia) en cualquier columna
                metodo = ""
                if any("transferencia" in str(celda).lower() for celda in fila):
                    metodo = "transferencia"
                
                # Lógica para extras manuales en Marzo y Abril
                extra_manual = 0
                if mes == "marzo":
                    extra_manual = 500 if len(fila) > 3 and "500" in fila[3] else 0
                elif mes == "abril":
                    extra_manual = 300 if len(fila) > 3 and "300" in fila[3] else 0
                    extra_manual += 500 if len(fila) > 4 and "500" in fila[4] else 0

                # Lógica de recargo automático
                recargo_automatico = 0
                deuda_total = 0

                # Si NO está pagado, se calcula la deuda y el recargo
                if estado != "PAGADO":
                    if mes_num < mes_actual:
                        recargo_automatico = 500
                    
                    # Leer si hay un "debe 500" escrito manualmente en la columna D (Mayo-Octubre)
                    if len(fila) > 3 and "debe" in fila[3].lower():
                        deuda_total += 500
                    
                    # Sumar el recargo automático y el extra manual
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
            hoja.update_cell(i, 2, "PAGADO")
            return {"mensaje": f"{cambio.nombre} marcado como PAGADO en {cambio.mes}"}
    
    raise HTTPException(status_code=404, detail="Persona no encontrada")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)