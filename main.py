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
                
                # Verificar si está pagado (en cualquier columna)
                es_pagado = any("PAGADO" in str(celda).upper() for celda in fila)
                
                # Verificar si el método es transferencia (SOLO columna C, índice 2)
                metodo = fila[2].strip().lower() if len(fila) > 2 else ""
                es_transferencia = metodo == "transferencia"
                
                if es_pagado and es_transferencia:
                    monto = VALOR_CUOTA
                    
                    # Extra fijo solo en abril (columna D con "300")
                    if mes == "abril":
                        col_extra = fila[3].strip().lower() if len(fila) > 3 else ""
                        if "300" in col_extra:
                            monto += 300
                    
                    # Determinar qué columna contiene el recargo según el mes
                    if mes == "marzo":
                        col_recargo = fila[3].strip().lower() if len(fila) > 3 else ""
                    elif mes == "abril":
                        col_recargo = fila[4].strip().lower() if len(fila) > 4 else ""
                    else:  # Mayo a Octubre
                        col_recargo = fila[3].strip().lower() if len(fila) > 3 else ""
                    
                    # 🔴 CORRECCIÓN: Solo sumar $500 si la casilla tiene contenido y NO dice "debe"
                    # Si la casilla está vacía, significa que pagó a tiempo y NUNCA tuvo deuda.
                    if col_recargo and "debe" not in col_recargo:
                        monto += 500
                    
                    total_transferencia += monto
                    
            recaudacion[mes] = total_transferencia
        except Exception as e:
            print(f"Error calculando recaudación para {mes}: {e}")
    return {"recaudacion": recaudacion}
