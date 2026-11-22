# Odoo Agent Gateway: especificación

Versión 1.0, aprobada por Daniel el 2026-11-22. Documentación interna en español; el README y el código van en inglés.
Nombre provisional del repositorio: `odoo-agent-gateway`.

## 1. Qué es y para quién

Un servidor MCP que deja a un agente de IA trabajar sobre un Odoo 18 Community **con los permisos del usuario que lo usa**, nunca con una cuenta de administrador. Incluye RAG sobre la documentación y los datos visibles para ese usuario, una batería de evaluación que prueba que el agente elige bien las herramientas y que no filtra datos ajenos, y un registro de auditoría.

Para quién: pymes y consultoras que usan Odoo y quieren dar un asistente a sus empleados sin abrir la puerta a que vea o cambie lo que no debe. Para Daniel, es el proyecto que demuestra en una sola pieza lo que piden SpainLink, ENCAMINA, NTT DATA, Malthus Darwin y T-Innova.

## 2. Reglas de limpieza (innegociables)

1. **Desde cero.** Ningún archivo, texto ni documento de Wavext (BerpIA, sus 22 documentos de diseño ni su código). Odoo Community y datos de demo inventados.
2. **Sin clientes reales.** Ni nombres, ni datos, ni capturas del asistente de WhatsApp.
3. **Se dice cómo se hizo.** El README incluye «Cómo lo construí con agentes»: qué especificación se dio, cómo se guió al agente y cómo se comprobó cada resultado. Hecho con ayuda de IA, y se dice.
4. **Nada de cifras sin demostrar.** Cada número del README sale de un comando que cualquiera puede ejecutar (cobertura, resultados de la evaluación).
5. `odoo_mcp_ultimate_toolkit` no se publica ni se copia. Si más adelante se revisa y algo aguanta, se reescribe y se pasa por las pruebas de este proyecto.

## 3. Alcance

**Entra (versión 1):**
- Servidor MCP en Python y FastAPI, con transporte HTTP.
- Autenticación contra Odoo con **la API key del propio usuario** por JSON-RPC, de modo que Odoo aplica sus permisos de acceso y reglas de registro. Sin `sudo`, sin cuenta de servicio con permisos de más.
- Herramientas de **lectura**: listar los modelos accesibles, buscar registros, leer un registro y obtener el esquema de un modelo.
- Herramientas de **escritura con aprobación**: el agente solo propone un cambio y una persona lo aprueba antes de ejecutarse.
- RAG con pgvector sobre la documentación de Odoo y los registros que el usuario puede ver.
- Registro de auditoría de cada llamada.
- Evaluación automatizada, CI con GitHub Actions y despliegue con demo pública.

**No entra:** interfaz de chat propia (se prueba desde un cliente MCP), multi-tenant, facturación, módulos de Odoo a medida.

## 4. Arquitectura

```
Cliente MCP (Claude, otro agente)
   │  MCP sobre HTTP, con token del usuario
┌──▼───────────────────────────────┐
│ Gateway (FastAPI + SDK de MCP)   │
│  · auth: token → API key Odoo    │
│  · herramientas lectura/propuesta│
│  · RAG (pgvector)                │
│  · auditoría, límites de uso     │
└──┬──────────────┬────────────────┘
   │ JSON-RPC     │ SQL
┌──▼────────┐ ┌───▼──────────────┐
│ Odoo 18   │ │ PostgreSQL       │
│ Community │ │ + pgvector       │
└───────────┘ └──────────────────┘
```

Todo en Docker Compose. Las decisiones importantes se registran como ADR cortos en `docs/adr/`.

## 5. Amenazas que se prueban

| Amenaza | Cómo se prueba |
|---|---|
| Un usuario ve datos de otro | Prueba automática: con dos usuarios de permisos distintos, el segundo nunca recibe registros del primero, ni por herramientas ni por RAG |
| Inyección de instrucciones en un registro (un campo con «ignora tus reglas») | Casos en la batería de evaluación; el agente no ejecuta acciones fuera de las propuestas |
| Escrituras sin permiso | El gateway no ejecuta; solo propone, y Odoo vuelve a comprobar el permiso al aprobar |
| Abuso de uso o coste | Límite de llamadas por usuario y por minuto |
| Secretos en el repositorio | Solo `.env.example`; escaneo de secretos en CI |

## 6. Evaluación

Tres suites, con los resultados guardados en el repositorio:
1. **Elección de herramienta:** preguntas en español e inglés con la herramienta esperada.
2. **Fuga de permisos:** el conjunto de la sección 5, que debe dar 0 fallos.
3. **Fundamentación del RAG:** preguntas con respuesta conocida en la documentación; se mide si la respuesta cita la fuente correcta.

Se publica una tabla con los resultados de cada versión.

## 7. Hitos

| Hito | Qué se entrega | Qué demuestra | Brecha del registro |
|---|---|---|---|
| M0 | Repositorio, esta especificación, Docker Compose con Odoo y PostgreSQL, CI con tests vacíos | Método de trabajo y CI | CI/CD |
| M1 | Servidor MCP de solo lectura con la API key del usuario y tests primero | MCP, API, permisos | Servidor MCP propio, OAuth/JWT |
| M2 | Suite de fuga de permisos y registro de auditoría | Seguridad de agentes | Seguridad de agentes |
| M3 | RAG con pgvector filtrado por permisos | RAG | RAG y bases vectoriales |
| M4 | Escrituras con aprobación | Control humano | Seguridad de agentes |
| M5 | Evaluación completa y trazas | Evaluación y observabilidad | Evaluación, observabilidad |
| M6 | Despliegue en la nube con URL pública, README en inglés y vídeo de 90 segundos | Nube y presentación | Azure o AWS |

El orden es deliberado: tras M1 ya se puede enlazar algo útil a SpainLink y T-Innova, y cada hito deja el repositorio presentable.

## 8. Cómo se trabaja (spec primero, tests primero)

- Cada hito empieza con una especificación corta y escenarios en Gherkin antes del código.
- Rojo, verde, refactor: ningún código sin su prueba.
- Cada hito termina con la «definición de hecho»: tests en verde en CI, README actualizado, ADR de las decisiones y resultados de la evaluación guardados.

## 9. Decisiones tomadas

1. **Herramientas de la versión 1:** las 9 de `TOOLS.md` (7 de lectura y 2 de escritura con aprobación), construidas por hitos.
2. **Nombre y licencia:** `odoo-agent-gateway` y licencia MIT.
3. **Idioma:** README, código, ADR y CI en inglés; especificación interna en español.
4. **Dónde vive:** carpeta local con su propio historial de git. Se publica en GitHub (`Aguimoda`) solo cuando Daniel lo apruebe, tras pasar las pruebas del hito M1.

## 10. Decisiones aplazadas

- **Nube de despliegue** (Azure Container Apps u otra): se decide al llegar a M6.
- **Cliente MCP para el vídeo de la demo:** se decide al llegar a M6.
