# Plan de producto: de gateway a asistente usable desde Odoo

Versión 1.0, 2026-11-23. Revisado con Daniel: las cuatro decisiones abiertas están tomadas.

## Qué queremos, en palabras

Hoy el gateway es un «enchufe» seguro entre un agente de IA y Odoo, pero hace falta ser desarrollador para usarlo. Queremos que **cualquier usuario de Odoo** pueda:

- abrir un **chat dentro de Odoo** y preguntar o pedir cosas («¿qué facturas vencidas tiene Acme?», «cambia el teléfono de este cliente»), con el agente usando todo lo construido: permisos de la persona, búsqueda en el manual, propuestas con aprobación, auditoría;
- ver las fuentes y las acciones del agente en cada respuesta;
- si aprueba cambios, tener una **bandeja de aprobaciones** en Odoo.

Y que un administrador pueda **configurar proveedores y modelos de IA**, ver si funcionan, cuánto se usan y qué falla, **sin tocar código**.

## Las piezas

| # | Pieza | Qué hace |
|---|---|---|
| 1 | **Servicio de agente** | El «cerebro» que hoy solo existe en el evaluador: recibe el mensaje, llama al modelo, ejecuta las herramientas como el usuario, responde **en streaming** (el texto aparece mientras se escribe) y guarda la conversación |
| 2 | **Chat** | La pantalla de conversación: mensajes, fuentes citadas, herramientas usadas, propuestas creadas y su estado, nuevo chat e historial |
| 3 | **Panel de proveedores y modelos** | Alta de proveedores (Groq, Cerebras, OpenAI, local, cualquiera compatible), sus claves, modelos, orden de reserva, límites y botón «probar conexión» |
| 4 | **Gestión de errores de proveedores** | Límites de los planes gratuitos, claves caducadas, modelos retirados, caídas: reintentar, cambiar de proveedor o explicarlo con claridad |
| 5 | **Bandeja de aprobaciones** | La interfaz de la API `/approvals` que ya existe: pendientes, valores actuales frente a los propuestos, aprobar o rechazar con nota |
| 6 | **Uso y salud** | Consumo por proveedor y modelo (llamadas, tokens, errores, latencia), estado de cada proveedor y avisos al administrador |
| 7 | **Módulo de Odoo** | Instala todo lo anterior dentro de Odoo: botón de chat en la barra superior, bandeja de aprobaciones y ajustes en Configuración |

## Todo lo que hay que poder configurar

| Ajuste | Quién | Detalle |
|---|---|---|
| Proveedores | Administrador | Nombre, tipo (preset o «compatible con OpenAI»), dirección de la API, activo o no |
| Claves de API | Administrador | Se guardan **cifradas**; después de guardarse **nunca se vuelven a mostrar**, solo se pueden sustituir |
| Modelos por proveedor | Administrador | Lista sacada del propio proveedor (`/models`) o escrita a mano; marcar cuáles admiten herramientas |
| Modelo por defecto y alternativas | Administrador | Ejemplo: Groq gpt-oss-120b por defecto; Cerebras y local como alternativas que el usuario puede elegir si el primero falla |
| Límites conocidos | Administrador | Peticiones y tokens por minuto y por día, para no chocar con el límite del plan gratuito |
| Instrucciones del agente | Administrador | Idioma, tono y reglas de la empresa (el «prompt de sistema»), con un valor por defecto seguro que no se puede quitar |
| Herramientas permitidas | Administrador | Activar o desactivar herramientas, por ejemplo dejar `propose_change` solo para ciertos grupos |
| Modelos de Odoo expuestos y umbral de búsqueda | Administrador | Lo que hoy está en variables de entorno, editable desde el panel |
| Retención de conversaciones | Administrador | Cuántos días se guardan; cada persona puede borrar las suyas |
| Límite de uso por persona | Administrador | Mensajes por minuto y por día, para repartir la cuota gratuita |
| Preferencias personales | Cada usuario | Idioma de respuesta y modelo preferido (entre los permitidos) |

## Errores que hay que gestionar

| Qué pasa | Cómo se detecta | Qué hace el sistema | Qué ve el usuario |
|---|---|---|---|
| Límite por minuto (plan gratuito) | HTTP 429 con `retry-after` | Espera si son pocos segundos; si no, se detiene | «Groq ha llegado a su límite por minuto. Puedes esperar unos segundos o seguir con otro modelo: [Cerebras] [Local]» |
| Cuota diaria agotada | 429 con mensaje de cuota, o el contador propio | Marca el proveedor como agotado hasta el día siguiente | Cuándo vuelve a estar disponible y los otros modelos para elegir |
| Clave inválida o caducada | 401 o 403 | Desactiva el proveedor y avisa al administrador | «Este proveedor no está disponible; el administrador ya está avisado» |
| Modelo retirado o inexistente | 404 o error de modelo | Lo marca como no disponible y avisa al administrador | Aviso y los otros modelos para elegir |
| Conversación demasiado larga | Error de contexto | Resume o recorta lo antiguo y reintenta | «He resumido la parte antigua de la conversación» |
| Proveedor caído o lento | 5xx o tiempo de espera | Reintentos con espera creciente; un **cortacircuitos** deja de usarlo un rato tras varios fallos | Aviso y los otros modelos para elegir |
| El modelo no sabe usar herramientas | Respuestas sin llamadas o con argumentos rotos | Avisa al modelo; tras varios fallos, cambia a un modelo que sí sepa | Respuesta normal o un aviso claro |
| El agente da vueltas | Máximo de pasos alcanzado (visto en la evaluación) | Corta y le pide al modelo que responda con lo que tiene | Respuesta honesta: «no lo he encontrado» |
| Odoo o la base del gateway caídos | Errores que ya existen | Fallo cerrado, igual que ahora | Mensaje claro, sin datos a medias |

## Seguridad: lo que no cambia y lo nuevo

**No cambia:** el agente actúa siempre como la persona (ADR 0002); solo propone cambios y aprueba otra persona (ADR 0012); todo queda auditado (ADR 0008).

**Nuevo, que hay que decidir bien:**
- **Claves de proveedores:** cifradas con una clave maestra que solo está en el entorno del servidor, nunca en la base de datos ni en el repositorio.
- **Quién administra:** lo decide Odoo con un grupo (por ejemplo «Agente de IA / Administrador»), siguiendo la misma regla de que Odoo es quien decide los permisos.
- **Cómo actúa el chat como la persona dentro de Odoo**, sin pedirle que pegue su API key: es la decisión más delicada (ver abajo).
- **Qué se manda al proveedor de IA:** las preguntas y lo que devuelven las herramientas, es decir, datos reales de la empresa. El panel debe dejar claro a qué proveedor van y permitir uno local para datos sensibles.

## Decisiones abiertas

1. **Orden de construcción: DECIDIDO (2026-11-23).** Primero el servicio de agente con un chat web propio del gateway, y después el módulo de Odoo, que reutiliza el mismo servicio.
2. **Identidad dentro de Odoo: DECIDIDO (2026-11-23).** El motor se queda **fuera de Odoo**, en el gateway, por dos razones:
   - fuera, el motor solo tiene la llave de la persona y no puede saltarse permisos aunque falle, mientras que dentro el código puede hacer `sudo()`;
   - las llamadas a la IA tardan segundos y ocuparían los workers de Odoo que necesitan otros usuarios.

   La primera vez, la persona acepta un aviso («¿Permites que el asistente actúe en tu nombre?»). Después, el módulo de Odoo, que se ejecuta como ella, crea una API key **solo para el asistente, de corta duración**, la renueva solo y se la pasa al motor por un canal cifrado. La persona puede revocarla cuando quiera. Descartadas: que cada persona pegue su clave (paso técnico que se repite al caducar) y una cuenta de servicio con permisos amplios (rompe la ADR 0002). Se registrará como ADR en M8.
3. **Conversaciones: DECIDIDO (2026-11-23).** Se guardan con un tiempo de retención configurable y cada persona puede borrar las suyas.
4. **Si un proveedor falla: DECIDIDO (2026-11-23).** No se cambia de modelo automáticamente: el chat explica qué ha pasado y deja que la persona elija otro modelo disponible, o espere.
5. **Despliegue:** sigue siendo el hito final, ahora con algo que enseñar: el chat funcionando con Odoo.

## Propuesta de hitos (sustituye a M6)

| Hito | Qué entrega |
|---|---|
| M6 | Servicio de agente con streaming, proveedores configurables con claves cifradas, avisos con elección de otro modelo, cortacircuitos, gestión de errores y uso por proveedor |
| M7 | Chat web y panel de administración (proveedores, modelos, ajustes, salud y uso) y bandeja de aprobaciones, con un diseño cuidado |
| M8 | Módulo de Odoo: chat en la barra superior, bandeja de aprobaciones y ajustes, con la identidad resuelta según la decisión 2 |
| M9 | Despliegue con demo pública y vídeo |

Cada hito sigue el mismo método: especificación y decisiones primero, pruebas primero, CI con Odoo real, y subida solo con el OK de Daniel.
