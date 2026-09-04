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
