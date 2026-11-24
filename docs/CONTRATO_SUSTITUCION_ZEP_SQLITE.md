# Contrato de sustitución de Zep por memoria local

Fecha de revisión: 2026-11-24
Rama: `adaptacion-gratuita-sin-zep`

## Estado comprobado

- El workflow `.github/workflows/memory-store-tests.yml` se ejecutó en GitHub Actions.
- Run: `45387949222`; job: `memory-store-tests`; resultado: `success`.
- El job completó los pasos de checkout, configuración de Python y ejecución de `python -m unittest discover -s backend/tests -p "test_memory_store.py" -v`.
- Esto valida únicamente el contrato aislado de `SQLiteMemoryStore`; no valida todavía la aplicación completa ni una simulación OASIS.

## Acoplamientos encontrados

### 1. Construcción del grafo

`backend/app/services/graph_builder.py` importa directamente tipos de `zep_cloud` y construye un cliente Zep en `GraphBuilderService.__init__`. Sus responsabilidades abarcan:
- crear y borrar grafos;
- convertir la ontología a modelos específicos de Zep;
- dividir texto, crear/enviar/procesar batches y esperar episodios;
- recuperar nodos/aristas y calcular `GraphInfo`.

Por tanto, `SQLiteMemoryStore` no puede sustituirlo simplemente con una variable de entorno: falta un constructor local que convierta los chunks y la ontología a nodos/aristas con IDs estables.

### 2. Lectura de entidades

`backend/app/services/zep_entity_reader.py` depende de `zep_cloud.NotFoundError`, del cliente Zep y de paginación Zep. Su contrato público produce:
- nodos con `uuid`, `name`, `labels`, `summary`, `attributes`;
- aristas con `uuid`, `name`, `fact`, `source_node_uuid`, `target_node_uuid`, `attributes`;
- entidades filtradas por etiquetas y enriquecidas con relaciones y nodos relacionados.

Un lector local debe preservar exactamente estas formas de salida para no romper las rutas ni los consumidores posteriores.

### 3. Memoria durante la simulación

`backend/app/services/zep_graph_memory_updater.py` convierte actividades de agentes en episodios, las envía mediante `client.graph.add` y espera su procesamiento. El gestor `ZepGraphMemoryManager` administra actualizadores por simulación.

El almacén SQLite actual registra actividades, pero aún no sustituye el ciclo de vida del updater ni convierte actividades en nodos/aristas. Hay que preservar el registro de actividad y definir qué información estructurada debe modificar el grafo.

### 4. Puntos de entrada y configuración

- `backend/app/api/graph.py` invoca `GraphBuilderService` y elimina grafos mediante operaciones Zep.
- `backend/app/api/simulation.py` comprueba `Config.ZEP_API_KEY` antes de leer entidades y crea `ZepGraphMemoryManager`.
- `backend/app/services/simulation_runner.py` importa y coordina `ZepGraphMemoryManager`.
- `backend/app/config.py` lee y valida `ZEP_API_KEY`.

No se debe quitar todavía la dependencia `zep-cloud`, eliminar la variable ni cambiar esas rutas: aún existen consumidores que esperan el comportamiento de Zep.

## Contrato local mínimo requerido

Antes de conectar SQLite, el adaptador local debe ofrecer equivalentes funcionales para:

1. **Graph lifecycle:** crear, obtener y borrar grafo; persistir nombre y metadatos.
2. **Ontology:** conservar tipos de entidad y relación, y normalizar nombres/atributos.
3. **Ingestion:** convertir texto en nodos y relaciones; operación repetible sin duplicar registros.
4. **Read model:** listar nodos/aristas y devolver entidades con el esquema actual de `EntityNode`.
5. **Simulation memory:** almacenar cada actividad con orden temporal y vincularla a `simulation_id` y `graph_id`.
6. **Concurrency and errors:** transacciones, claves foráneas, aislamiento por grafo y errores distinguibles de resultados vacíos.

## Secuencia segura de implementación

1. Añadir pruebas de contrato para las formas de nodo/arista y ciclo de vida.
2. Implementar un adaptador local de grafo sobre `SQLiteMemoryStore`, sin tocar aún rutas productivas.
3. Implementar un lector local compatible con `EntityNode` y `FilteredEntities`.
4. Implementar un updater local que registre actividades y actualice memoria estructurada de forma determinista.
5. Añadir selección explícita de backend (`zep` o `sqlite`) manteniendo Zep como opción de compatibilidad.
6. Integrar por etapas y ejecutar pruebas unitarias y de rutas; después probar una simulación completa.
7. Solo cuando la ruta SQLite esté validada, documentar la retirada opcional de Zep.

## Riesgos y límites

- La base SQLite actual usa por defecto `backend/uploads/mirofish_memory.sqlite3`. En Render Free el disco del servicio es efímero: no se debe prometer persistencia de datos entre reinicios/redeploys.
- El CI exitoso no prueba despliegue, proveedor LLM, frontend, ejecución OASIS ni equivalencia semántica con Zep.
- La integración sigue pendiente. No se ha eliminado ni desactivado Zep.


## Implementación local incremental (2026-11-24)

Se añadieron componentes aislados sobre el almacén SQLite:

- `backend/app/services/local_graph_adapter.py`: ciclo de vida, escritura/lectura de nodos y relaciones, y vistas de datos del grafo.
- `backend/app/services/local_entity_reader.py`: filtro de entidades por etiquetas y enriquecimiento con relaciones entrantes/salientes, con estructuras `EntityNode` y `FilteredEntities`.
- `backend/app/services/local_graph_memory_updater.py`: registra las acciones originales de los agentes en la tabla de actividades y ofrece un gestor con métodos de ciclo de vida compatibles con los puntos de coordinación del runner.

### Límite funcional del updater

El updater SQLite registra acciones estructuradas; no realiza extracción semántica de texto ni convierte automáticamente publicaciones, nombres o acciones en entidades y relaciones del grafo. Esa equivalencia con la ingestión episódica de Zep sigue pendiente y requiere diseño/pruebas independientes.

### Validación actual

GitHub Actions run `45389523275` terminó en `success` en commit `eecbf3c2ac8361bca8cbac9cecea565b7f352b6d`. Ejecutó cuatro suites: almacén (6), adaptador (4), lector (4) y updater (3): **17 pruebas aprobadas**.

Estos módulos siguen aislados: no están conectados todavía a las rutas Flask ni a `SimulationRunner`. La construcción del grafo desde documentos y la ejecución completa OASIS siguen dependiendo del flujo original con Zep hasta que se implemente y valide su reemplazo.
