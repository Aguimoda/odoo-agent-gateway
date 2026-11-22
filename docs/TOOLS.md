# Herramientas del Odoo Agent Gateway

Versión 1.0, aprobada por Daniel el 2026-11-22: las 9 herramientas entran en la versión 1. Complementa a `SPEC.md`.

Una «herramienta» es una acción concreta que el agente de IA puede pedirle al portero. Cuantas menos y más claras, mejor: cada una es una puerta que hay que vigilar y probar.

## Lo que todas las herramientas cumplen

- El agente siempre actúa **como la persona que pregunta**. Si Odoo no deja a esa persona ver algo, la herramienta tampoco.
- Cada respuesta tiene un **tope de tamaño** (por defecto 50 registros) para que nadie vuelque la base de datos entera de golpe.
- Cada llamada queda **apuntada** en el registro de auditoría: quién, cuándo, qué herramienta y con qué datos.
- Lo que devuelven los registros se entrega como **dato**, nunca como instrucción. Si un campo dice «ignora tus reglas», el agente no lo obedece.

## Versión 1: herramientas de lectura

| # | Herramienta | Qué hace, con una frase | Pregunta de ejemplo | Hito |
|---|---|---|---|---|
| 1 | `mis_permisos` | Dice qué áreas de Odoo puede ver y tocar la persona que pregunta | «¿Qué puedo consultar aquí?» | M1 |
| 2 | `listar_modelos` | Lista las áreas de datos accesibles (clientes, ventas, facturas, productos, inventario…) | «¿Con qué datos puedes ayudarme?» | M1 |
| 3 | `describir_modelo` | Explica qué campos tiene un área y qué significa cada uno | «¿Qué datos guardo de cada factura?» | M1 |
| 4 | `buscar_registros` | Busca registros con filtros y devuelve los campos pedidos | «Facturas vencidas del cliente Acme» | M1 |
| 5 | `leer_registro` | Devuelve un registro concreto, completo | «Enséñame el pedido S00042» | M1 |
| 6 | `resumir_datos` | Cuenta o suma agrupando (totales por mes, por cliente…) | «¿Cuánto vendimos por mes este año?» | M1 |
| 7 | `buscar_conocimiento` | Busca en la documentación y en los textos visibles para esa persona, y cita la fuente | «¿Cómo se registra una devolución?» | M3 |

## Versión 1: herramientas de escritura, siempre con aprobación

| # | Herramienta | Qué hace | Hito |
|---|---|---|---|
| 8 | `proponer_cambio` | El agente **no cambia nada**: escribe una propuesta (qué registro, qué valores nuevos y por qué) y se queda esperando | M4 |
| 9 | `ver_mis_propuestas` | Muestra el estado de las propuestas de esa persona (pendiente, aprobada, rechazada) | M4 |

**La aprobación no es una herramienta del agente.** Se hace por otro camino, para una persona (una pantalla o un comando). Así el agente no puede aprobar sus propias propuestas. Al aprobar, el gateway vuelve a comprobar con Odoo que esa persona tiene permiso para el cambio.

## Lo que NO existe, a propósito

- Borrar registros.
- Consultas SQL libres.
- Ejecutar cualquier función de Odoo a petición del agente (botones, acciones del servidor).
- Una cuenta con todos los permisos que se salte las reglas de Odoo.
- Cambios sin aprobación humana.

## Después de la versión 1 (no entra ahora)

Cuenta de aprobador con aviso por correo, notas internas de Odoo para dejar rastro, herramientas por módulo (por ejemplo, un resumen de pipeline de ventas), varios Odoo a la vez.

## Cómo se prueba cada herramienta

Antes de programar, para cada una se escriben tres cosas:
1. **Escenario normal:** una persona con permiso recibe lo esperado.
2. **Escenario prohibido:** otra persona sin permiso no recibe nada y el motivo queda en el registro.
3. **Escenario hostil:** un registro con texto malicioso no cambia el comportamiento del agente.

Las pruebas de fuga de permisos (SPEC, sección 5) usan siempre dos usuarios de demo con permisos distintos: «Ana, de ventas» y «Luis, de dirección».

## Datos de demo

Empresa ficticia con clientes, pedidos y facturas inventados, más dos o tres usuarios con permisos distintos. Nada de datos reales.

## Nombres técnicos (en inglés, como los verá el agente)

| Español | Nombre MCP |
|---|---|
| mis_permisos | `my_permissions` |
| listar_modelos | `list_models` |
| describir_modelo | `describe_model` |
| buscar_registros | `search_records` |
| leer_registro | `read_record` |
| resumir_datos | `summarize_data` |
| buscar_conocimiento | `search_knowledge` |
| proponer_cambio | `propose_change` |
| ver_mis_propuestas | `list_my_proposals` |
