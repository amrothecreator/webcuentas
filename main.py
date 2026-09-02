<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>Control de Cuotas</title>
    <style>
        body { font-family: sans-serif; padding: 20px; background: #f4f4f4; }
        table { width: 100%; border-collapse: collapse; background: white; }
        th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
        th { background: #333; color: white; }
        input, button { padding: 10px; margin: 5px; }
        .admin-btn { background: green; color: white; border: none; cursor: pointer; }
        .metodo-btn { background: #555; color: white; border: none; padding: 5px 10px; margin-left: 5px; cursor: pointer; }
        .metodo-btn:hover { opacity: 0.8; }
        
        /* Estilos para la tabla de recaudación */
        #tabla-recaudacion {
            margin-top: 30px;
            display: none; /* Oculto por defecto */
        }
        #tabla-recaudacion h2 {
            margin-bottom: 10px;
        }

        .modal { display: none; position: fixed; z-index: 1000; left: 0; top: 0; width: 100%; height: 100%; background-color: rgba(0,0,0,0.5); }
        .modal-contenido { background-color: #fefefe; margin: 10% auto; padding: 20px; border-radius: 10px; width: 50%; max-width: 500px; box-shadow: 0 4px 8px rgba(0,0,0,0.2); position: relative; }
        .cerrar { color: #aaa; float: right; font-size: 28px; font-weight: bold; cursor: pointer; }
        .cerrar:hover, .cerrar:focus { color: black; text-decoration: none; cursor: pointer; }
        .lista-meses { list-style: none; padding: 0; }
        .lista-meses li { padding: 10px; border-bottom: 1px solid #eee; }
    </style>
</head>
<body>
    <h1>Control de Cuotas (Marzo - Octubre)</h1>
    <input type="text" id="buscador" placeholder="Buscar persona..." onkeyup="filtrar()">
    <button onclick="loginAdmin()">Soy Admin</button>
    
    <table id="tabla">
        <thead>
            <tr>
                <th>Nombre</th>
                <th>Pagados</th>
                <th>Pendientes</th>
                <th>Deuda Total ($)</th>
                <th>Detalle</th>
            </tr>
        </thead>
        <tbody id="cuerpo-tabla"></tbody>
    </table>

    <!-- Tabla de recaudación por transferencia -->
    <div id="tabla-recaudacion">
        <h2>💰 Recaudado por Transferencia (Mes a Mes)</h2>
        <table>
            <thead>
                <tr>
                    <th>Mes</th>
                    <th>Total Recaudado</th>
                </tr>
            </thead>
            <tbody id="cuerpo-recaudacion"></tbody>
        </table>
    </div>

    <div id="miModal" class="modal">
        <div class="modal-contenido">
            <span class="cerrar" onclick="cerrarModal()">&times;</span>
            <div id="detalle-persona"></div>
        </div>
    </div>

    <script>
        let esAdmin = false;
        let datosGlobales = {};

        async function cargarDatos() {
            const respuesta = await fetch('/api/datos');
            datosGlobales = await respuesta.json();
            renderTabla();
        }

        async function cargarRecaudacion() {
            const respuesta = await fetch('/api/recaudacion');
            const data = await respuesta.json();
            renderTablaRecaudacion(data.recaudacion);
        }

        function renderTablaRecaudacion(recaudacion) {
            const cuerpo = document.getElementById('cuerpo-recaudacion');
            cuerpo.innerHTML = '';
            for (const [mes, total] of Object.entries(recaudacion)) {
                cuerpo.innerHTML += `
                    <tr>
                        <td>${mes.toUpperCase()}</td>
                        <td>$${total}</td>
                    </tr>
                `;
            }
        }

        function renderTabla() {
            const cuerpo = document.getElementById('cuerpo-tabla');
            cuerpo.innerHTML = '';
            for (const [nombre, meses] of Object.entries(datosGlobales)) {
                let pagados = 0, pendientes = 0, deuda = 0;
                for (const [mes, info] of Object.entries(meses)) {
                    if (info.estado === 'PAGADO') pagados++;
                    else pendientes++;
                    deuda += info.deuda;
                }
                cuerpo.innerHTML += `
                    <tr>
                        <td>${nombre}</td>
                        <td>${pagados}</td>
                        <td>${pendientes}</td>
                        <td>$${deuda}</td>
                        <td><button onclick="verDetalle('${nombre}')">Ver</button></td>
                    </tr>
                `;
            }
        }

        function verDetalle(nombre) {
            const meses = datosGlobales[nombre];
            let html = `<h2>${nombre}</h2><ul class="lista-meses">`;
            for (const [mes, info] of Object.entries(meses)) {
                const estado = info.estado === 'PAGADO' ? '✅ Pagado' : '❌ Pendiente';
                let extraHTML = info.extra > 0 ? ` (Extra $${info.extra})` : '';
                let deudaHTML = info.deuda > 0 ? ` (Debe $${info.deuda})` : '';
                let metodoHTML = info.estado === 'PAGADO' && info.metodo ? ` (${info.metodo})` : '';

                html += `<li>${mes.toUpperCase()}: ${estado}${metodoHTML}${extraHTML}${deudaHTML}`;
                if (esAdmin && info.estado !== 'PAGADO') {
                    html += ` <button class="admin-btn" onclick="toggleMetodo('${nombre}', '${mes}')">Marcar Pagado</button>`;
                    html += ` <div id="opciones-${nombre}-${mes}" style="display:none; margin-top:5px;">
                                <button class="metodo-btn" onclick="marcarPagado('${nombre}', '${mes}', 'efectivo')">💵 Efectivo</button>
                                <button class="metodo-btn" onclick="marcarPagado('${nombre}', '${mes}', 'transferencia')">🏦 Transferencia</button>
                              </div>`;
                }
                html += `</li>`;
            }
            html += `</ul>`;
            
            document.getElementById('detalle-persona').innerHTML = html;
            document.getElementById('miModal').style.display = 'block';
        }

        function toggleMetodo(nombre, mes) {
            const div = document.getElementById(`opciones-${nombre}-${mes}`);
            if (div) div.style.display = div.style.display === 'none' ? 'block' : 'none';
        }

        function cerrarModal() {
            document.getElementById('miModal').style.display = 'none';
        }

        window.onclick = function(event) {
            const modal = document.getElementById('miModal');
            if (event.target == modal) modal.style.display = 'none';
        }

        async function loginAdmin() {
            const pass = prompt("Contraseña de administrador:");
            if (!pass) return;

            const respuesta = await fetch('/api/login', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ password: pass }) 
            });

            if (respuesta.ok) {
                esAdmin = true;
                alert("Modo administrador activado.");
                renderTabla();
                // Mostrar y cargar la tabla de recaudación
                document.getElementById('tabla-recaudacion').style.display = 'block';
                await cargarRecaudacion();
            } else {
                alert("Contraseña incorrecta.");
                esAdmin = false;
                renderTabla();
                document.getElementById('tabla-recaudacion').style.display = 'none';
            }
        }

        async function marcarPagado(nombre, mes, metodo) {
            const pass = prompt("Confirma tu contraseña de admin para modificar:");
            if (!pass) return;

            const respuesta = await fetch('/api/marcar_pagado', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ nombre, mes, password: pass, metodo })
            });

            if (respuesta.ok) {
                alert("¡Pago registrado con éxito!");
                await cargarDatos();
                verDetalle(nombre); // Mantener el modal abierto
                if (esAdmin) {
                    await cargarRecaudacion(); // Actualizar la tabla de recaudación
                }
            } else {
                alert("Error: Contraseña incorrecta o persona no encontrada.");
            }
        }

        function filtrar() {
            const texto = document.getElementById('buscador').value.toLowerCase();
            const filas = document.querySelectorAll('#cuerpo-tabla tr');
            filas.forEach(fila => {
                const nombre = fila.cells[0].textContent.toLowerCase();
                fila.style.display = nombre.includes(texto) ? '' : 'none';
            });
        }

        cargarDatos();
    </script>
</body>
</html>
