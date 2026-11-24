# Auditoría técnica: adaptación sin Zep

Fecha de auditoría: 2026-11-24
Rama: `adaptacion-gratuita-sin-zep`

## Estado verificado

- El repositorio es un fork de MiroFish y la rama de adaptación parte de `main`.
- La configuración actual exige `LLM_API_KEY` y `ZEP_API_KEY`.
- El backend importa directamente `zep_cloud` en rutas y servicios.
- La memoria Zep no está encapsulada en un único módulo: intervienen construcción del grafo, lectura de entidades, actualización durante simulaciones y ciclo de vida/eliminación del grafo.
- `backend/requirements.txt` fija `zep-cloud==3.25.0`.
- El estado de proyectos/tareas/simulaciones y archivos también requiere revisión independiente; sustituir Zep no resuelve por sí solo la persistencia del despliegue.

## Archivos y puntos de acoplamiento identificados

| Archivo | Responsabilidad / dependencia |
|---|---|
| `backend/app/config.py` | Exige ZEP_API_KEY en `Config.validate()`. |
| `backend/app/services/graph_builder.py` | Construye y elimina grafos; importa tipos y cliente de Zep. |
| `backend/app/services/zep_entity_reader.py` | Lee nodos/aristas y filtra entidades desde Zep. |
| `backend/app/services/zep_graph_memory_updater.py` | Convierte actividades OASIS en episodios y actualiza el grafo. |
| `backend/app/services/simulation_manager.py` | Prepara simulaciones usando el lector de entidades. |
| `backend/app/services/simulation_runner.py` | Conecta el proceso OASIS con el actual gestor de memoria Zep. |
| `backend/app/api/graph.py` | Usa Zep para ciclo de vida del grafo y control de consumidores. |
| `backend/app/api/simulation.py` | Consulta entidades y usa el gestor de memoria Zep. |
| `backend/app/utils/zep.py`, `zep_paging.py`, `zep_lifecycle.py` | Cliente, paginación y coordinación de operaciones Zep. |
| `backend/requirements.txt` | Dependencia instalada de Zep Cloud. |

## Restricción de alojamiento gratuito

Render Free no ofrece disco persistente. Cualquier SQLite/JSON guardado en el sistema de archivos de ese servicio puede perderse al reiniciar, redeplegar o dormir. Por tanto, SQLite local puede servir para pruebas o desarrollo, pero no debe presentarse como memoria duradera en producción.

Tampoco se debe asumir que una base de datos gratuita externa sea permanente o que no requiera tarjeta: antes de elegirla hay que comprobar sus límites y condiciones vigentes.

## Plan de implementación seguro

1. Definir una interfaz de almacenamiento/memoria con operaciones explícitas para crear/leer/eliminar grafos, consultar entidades y registrar actividades.
2. Implementar un adaptador local de desarrollo y pruebas, sin borrar ni alterar el adaptador Zep existente.
3. Crear pruebas de contrato para grafo, nodos, relaciones, actividades, reinicio y aislamiento entre proyectos.
4. Migrar rutas y servicios a la interfaz por etapas; conservar compatibilidad Zep.
5. Probar el backend completo y las rutas antes de cambiar dependencias o configuración de producción.
6. Seleccionar y verificar un almacenamiento persistente gratuito compatible con el requisito de no tarjeta. Si no existe una opción que cumpla, comunicar la limitación antes de desplegar.
7. Solo entonces preparar Render y la PWA.

## No realizado todavía

- No se modificó código funcional.
- No se eliminó Zep ni su dependencia.
- No se ejecutaron pruebas ni backtests.
- No se creó ni desplegó un servicio Render.
- No se configuraron claves secretas.

Esta auditoría documenta el estado y evita confundir un cambio de configuración con una sustitución real de memoria.
