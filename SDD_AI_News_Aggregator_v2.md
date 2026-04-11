# SDD — AI News & Tools Aggregator v2.0
**Software Design Document**
**Fecha:** Abril 2026 | **Versión:** 2.0 | **Estado:** Producción

---

## 0. Diagnóstico — Por qué v1.0 era insuficiente

Antes de rediseñar, se realiza una auditoría crítica de la v1.0 para no repetir los mismos errores.

### 0.1 Fallos de la v1.0 (análisis crítico)

**Fallo crítico #1 — La consulta no existe.**
El SDD decía "hoja consultable online" pero nunca definía cómo. Un usuario sin cuenta Google o sin el enlace exacto no puede acceder. Compartir un Google Sheet crudo no es una interfaz de producto: no tiene búsqueda, no filtra, no es legible en móvil y su aspecto es el de una hoja de cálculo corporativa, no de una herramienta propia.

**Fallo crítico #2 — Deduplicación frágil.**
Guardar hashes en una pestaña de Google Sheets obliga al script a hacer una lectura completa de esa pestaña en cada ejecución. A los 6 meses, con miles de hashes, esta operación se vuelve lenta y consume cuota de la API. Un fallo de lectura anula toda la deduplicación.

**Fallo crítico #3 — Resúmenes de baja calidad.**
Los feeds RSS ofrecen títulos y descripciones truncadas de 200-300 caracteres. Groq resume eso. El resultado es un resumen de un resumen, con información mínima. Para herramientas de ProductHunt, el feed apenas incluye más que el nombre.

**Fallo crítico #4 — Campo "precio" inutilizable.**
La mayoría de RSS feeds no incluyen precios. El resultado es que el campo queda mayormente como "Ver enlace" o "Noticia", haciendo la columna casi decorativa. No aporta valor real.

**Fallo crítico #5 — Taxonomía binaria insuficiente.**
Clasificar como solo `noticia` o `herramienta` es demasiado burdo. Un lanzamiento de GPT-5 y una noticia sobre normativa europea de IA son ambas "noticias", pero de impacto radicalmente diferente. Sin granularidad, el sheet es ruido.

**Fallo crítico #6 — Sin scoring de relevancia.**
Todos los ítems tienen el mismo peso visual. Un post menor de un blog tiene la misma jerarquía que el lanzamiento del modelo más importante del año. El usuario no sabe por dónde empezar.

**Fallo crítico #7 — Sin resiliencia.**
Si Groq da error, todos los ítems de esa ejecución obtienen el fallback de 200 caracteres. Si GitHub Actions falla, el sistema para silenciosamente. No hay monitoreo, no hay alertas, no hay reintentos inteligentes.

**Fallo crítico #8 — Proveedor único de IA.**
Groq es gratuito hoy. Los límites gratuitos de APIs cambian sin previo aviso. Una sola dependencia sin fallback convierte un cambio de política de Groq en una interrupción total del servicio.

**Fallo crítico #9 — La hoja crece indefinidamente.**
Sin política de retención, en un año la hoja tiene decenas de miles de filas. Consultar, desplazarse por ella y la propia API de Sheets se ralentizan progresivamente.

**Fallo crítico #10 — Configuración acoplada al código.**
Para añadir o quitar una fuente RSS hay que editar `config.py` y hacer un push. Esto crea fricción innecesaria para una operación que debería ser trivial.

---

## 1. Resumen Ejecutivo

**AI News & Tools Aggregator v2.0** es un sistema de inteligencia de contenidos que recopila, enriquece, clasifica y puntúa automáticamente las últimas noticias y herramientas de inteligencia artificial, presentando los resultados en un **dashboard web público** alojado en GitHub Pages y respaldado en Google Sheets como base de datos.

La arquitectura es completamente serverless, se ejecuta cada 6 horas mediante GitHub Actions y tiene coste de infraestructura **cero euros al mes**.

La pregunta "¿cómo accedo al sheet actualizado?" tiene ahora una respuesta concreta:

```
https://{tu-usuario}.github.io/{nombre-repo}/
```

Esta URL muestra un dashboard con búsqueda, filtros por categoría, idioma y relevancia, y se actualiza automáticamente tras cada ejecución del pipeline.

---

## 2. Objetivos

**Funcionales:**
- Recopilar automáticamente noticias y herramientas de IA en inglés y español.
- Enriquecer cada ítem obteniendo el contenido completo del artículo (no solo el snippet del RSS).
- Generar resúmenes de calidad (2-4 frases) basados en el contenido real.
- Clasificar cada ítem en 6 categorías granulares mediante IA.
- Asignar una puntuación de relevancia del 1 al 10 a cada ítem.
- Extraer automáticamente 3-5 tags temáticos por ítem.
- Almacenar los datos en Google Sheets como base de datos.
- Publicar un dashboard web consultable, filtrable y buscable en GitHub Pages.
- Evitar duplicados semánticos y por URL.
- Ejecutar el ciclo completo cada 6 horas sin intervención humana.

**No funcionales:**
- Coste de infraestructura: 0 €/mes.
- Resiliencia: el fallo de una fuente o de un proveedor de IA no detiene el pipeline.
- Mantenibilidad: añadir o quitar fuentes no requiere tocar código Python.
- Retención: máximo 1.000 ítems activos en la hoja principal; los históricos se archivan.

---

## 3. Alcance

### Incluido en v2.0
- Pipeline Python completo con enriquecimiento de contenido.
- Clasificación y scoring por IA (Groq primario, Gemini como fallback).
- Deduplicación por hash SHA256 de URL almacenada en archivo JSON en el repositorio.
- Escritura estructurada en Google Sheets con 11 columnas.
- Dashboard HTML/JS en GitHub Pages con búsqueda, filtros y ordenación.
- Configuración de fuentes en archivo YAML externo (sin tocar código).
- Monitoreo básico: email automático de GitHub Actions en caso de fallo.
- Política de retención: archivo automático al superar 1.000 ítems.
- Fallback de IA: Groq → Gemini Free → extracto original.

### Excluido de v2.0
- Notificaciones push (Telegram, Slack).
- Autenticación de usuarios en el dashboard.
- Scraping de sitios con JavaScript dinámico (requeriría Playwright/Selenium).
- Extracción automática de precios (demasiado inconsistente entre fuentes).

---

## 4. Arquitectura del Sistema

```
┌─────────────────────────────────────────────────────────────────┐
│                    GITHUB ACTIONS (cada 6h)                     │
│                    cron: '0 */6 * * *'                          │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    PIPELINE PYTHON 3.11                         │
│                                                                 │
│  ┌──────────────┐  ┌────────────────┐  ┌─────────────────────┐ │
│  │  1. COLLECT  │  │  2. ENRICH     │  │  3. DEDUPLICATE     │ │
│  │  RSS + HN    │→ │  Fetch article │→ │  hashes.json        │ │
│  │  (feedparser │  │  full content  │  │  (en el repo)       │ │
│  │  + requests) │  │  (requests +   │  │  SHA256(url)        │ │
│  └──────────────┘  │  readability)  │  └─────────┬───────────┘ │
│                    └────────────────┘            │             │
│                                                  ▼             │
│                    ┌─────────────────────────────────────────┐ │
│                    │  4. AI ENRICHMENT (Groq / Gemini)       │ │
│                    │  · Resumen (2-4 frases)                 │ │
│                    │  · Categoría (6 opciones)               │ │
│                    │  · Relevancia (1-10)                    │ │
│                    │  · Tags (3-5 keywords)                  │ │
│                    └──────────────────┬──────────────────────┘ │
│                                       │                        │
│                                       ▼                        │
│                    ┌─────────────────────────────────────────┐ │
│                    │  5. WRITE → Google Sheets API           │ │
│                    │  + Retención: archiva si >1000 ítems    │ │
│                    └──────────────────┬──────────────────────┘ │
│                                       │                        │
│                                       ▼                        │
│                    ┌─────────────────────────────────────────┐ │
│                    │  6. COMMIT hashes.json al repo          │ │
│                    └─────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                           │
                           ▼ (sheet actualizado)
┌─────────────────────────────────────────────────────────────────┐
│                    CAPA DE CONSULTA                             │
│                                                                 │
│  Google Sheets                    GitHub Pages                  │
│  (base de datos)  ──JSON API──►   Dashboard HTML/JS            │
│  (view-only public)              https://{user}.github.io/...  │
│                                  · Búsqueda full-text          │
│                                  · Filtros: cat/idioma/tipo    │
│                                  · Ordenar por relevancia      │
│                                  · Cards responsive (móvil)    │
└─────────────────────────────────────────────────────────────────┘
```

**Stack tecnológico completo:**

| Componente | Tecnología | Justificación | Coste |
|---|---|---|---|
| Lenguaje | Python 3.11 | Ecosistema maduro para scraping y APIs | 0 € |
| Scheduler | GitHub Actions | Serverless, cron nativo, logs incluidos | 0 € |
| IA primaria | Groq (llama-3.1-8b-instant) | Más rápida y gratuita del mercado | 0 € |
| IA fallback | Gemini 1.5 Flash API | Free tier generoso, diferente proveedor | 0 € |
| Base de datos | Google Sheets API v4 | Consultable online, sin setup de BD | 0 € |
| Frontend | GitHub Pages (HTML/JS) | Hosting estático gratuito, CI/CD incluido | 0 € |
| JSON Bridge | opensheet.elk.sh | Expone Sheets como JSON limpio sin auth | 0 € |
| Config fuentes | YAML en el repo | Sin acoplamiento al código Python | 0 € |
| Deduplicación | hashes.json en repo | Sin dependencia de APIs externas | 0 € |
| RSS parsing | feedparser 6.x | Estándar de industria, sin auth | 0 € |
| Content fetch | requests + trafilatura | Extrae texto limpio de artículos | 0 € |

---

## 5. Capa de Consulta — Cómo Acceder al Sheet

Esta sección responde directamente a la pregunta: **¿cómo accedo al sheet actualizado?**

### 5.1 La respuesta directa

```
https://{tu-usuario-github}.github.io/{nombre-del-repo}/
```

Esta URL está disponible desde el momento en que haces el primer push. No requiere login, funciona en cualquier dispositivo, y muestra los datos más recientes (la latencia es el tiempo que tarda la última ejecución de Actions en escribir en la hoja, normalmente < 5 minutos).

### 5.2 Cómo funciona la conexión Sheet → Dashboard

```
Google Sheet (pública en modo lectura)
    │
    │  GET https://opensheet.elk.sh/{SHEET_ID}/AI_Feed
    │  → Devuelve array JSON limpio, sin autenticación
    │
    ▼
Dashboard JavaScript (GitHub Pages)
    │
    ├── Parsea el JSON
    ├── Renderiza tarjetas ordenadas por relevancia DESC
    ├── Activa filtros dinámicos (categoría, idioma, tipo)
    └── Activa búsqueda full-text sobre nombre + resumen + tags
```

**Servicio `opensheet.elk.sh`** [web:27]: proxy open-source que envuelve la Google Visualization API y devuelve JSON plano sin necesidad de credenciales. El sheet debe estar compartido como "Cualquiera con el enlace puede ver" (lectura pública). Es open-source y puede auto-hostearse si se desea.

### 5.3 Características del Dashboard (GitHub Pages)

El archivo `index.html` (en la raíz del repo) es un documento HTML autocontenido que incluye:

- **Cards de contenido**: una tarjeta por ítem con badge de categoría, score de relevancia, idioma, nombre, resumen, fuente y enlace.
- **Barra de búsqueda**: filtra en tiempo real sobre nombre + resumen + tags.
- **Filtros**: selector de categoría (6 opciones), idioma (EN/ES/Ambos), tipo (noticia/herramienta).
- **Ordenación**: por fecha (más reciente primero) o por relevancia (más importante primero).
- **Paginación**: 20 ítems por página para no sobrecargar el DOM.
- **Modo oscuro/claro**: toggle con persistencia en variable local.
- **Responsive**: funciona en móvil, tablet y escritorio.
- **Sin dependencias externas de JS**: todo vanilla JS, sin frameworks pesados.
- **Actualización de datos**: botón "Actualizar" que re-fetch el JSON del Sheet.

### 5.4 Acceso directo a Google Sheets (opcional)

Para quienes prefieran ver o exportar los datos crudos:
- El Sheet está compartido públicamente en modo lectura.
- URL de acceso: `https://docs.google.com/spreadsheets/d/{SHEET_ID}`.
- Permite exportar a CSV, XLSX, o conectar con otras herramientas como Tableau, Power BI, Looker Studio.

---

## 6. Fuentes de Datos

### 6.1 Criterios de selección

- **Gratuitas**: sin suscripción ni pago.
- **Sin autenticación**: accesibles con HTTP simple o sin credenciales.
- **Estables**: fuentes con historial de disponibilidad > 2 años.
- **RSS o API pública**: no scraping de HTML dinámico en v2.0.

### 6.2 Fuentes configuradas

Las fuentes se definen en `config/sources.yaml`. Añadir o eliminar una fuente es editar este archivo y hacer push; no hay que tocar código Python.

```yaml
# config/sources.yaml
sources:
  # ─── INGLÉS ─────────────────────────────────────────────────
  - name: "The Verge AI"
    url: "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"
    type: "rss"
    language: "EN"
    default_type: "noticia"

  - name: "TechCrunch AI"
    url: "https://techcrunch.com/category/artificial-intelligence/feed/"
    type: "rss"
    language: "EN"
    default_type: "noticia"

  - name: "VentureBeat AI"
    url: "https://venturebeat.com/category/ai/feed/"
    type: "rss"
    language: "EN"
    default_type: "noticia"

  - name: "Wired AI"
    url: "https://www.wired.com/feed/tag/ai/latest/rss"
    type: "rss"
    language: "EN"
    default_type: "noticia"

  - name: "OpenAI Blog"
    url: "https://openai.com/news/rss.xml"
    type: "rss"
    language: "EN"
    default_type: "noticia"

  - name: "MIT Technology Review"
    url: "https://www.technologyreview.com/feed/"
    type: "rss"
    language: "EN"
    default_type: "noticia"

  - name: "Towards Data Science"
    url: "https://towardsdatascience.com/feed"
    type: "rss"
    language: "EN"
    default_type: "noticia"

  - name: "ProductHunt"
    url: "https://www.producthunt.com/feed"
    type: "rss"
    language: "EN"
    default_type: "herramienta"

  # ─── ESPAÑOL ────────────────────────────────────────────────
  - name: "Xataka IA"
    url: "https://www.xataka.com/tag/inteligencia-artificial/feed"
    type: "rss"
    language: "ES"
    default_type: "noticia"

  - name: "El País Tecnología"
    url: "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/tecnologia/portada"
    type: "rss"
    language: "ES"
    default_type: "noticia"

  # ─── HACKER NEWS (API) ──────────────────────────────────────
  - name: "Hacker News"
    url: "https://hacker-news.firebaseio.com/v0/"
    type: "hn_api"
    language: "EN"
    default_type: "noticia"
    keywords:
      - "AI"
      - "LLM"
      - "GPT"
      - "Claude"
      - "Gemini"
      - "machine learning"
      - "neural network"
      - "artificial intelligence"
      - "deep learning"
      - "agent"
      - "transformer"
      - "diffusion"
```

### 6.3 Filtros de calidad mínima

Antes de pasar al paso de enriquecimiento, cada ítem debe superar:
- Título con al menos 5 palabras.
- URL válida (comienza con `https://`).
- Fecha de publicación en los últimos 7 días (ítems más antiguos se descartan).
- Para HN: score de la story > 10 puntos (filtra ruido).

---

## 7. Modelo de Datos

### 7.1 Pestaña principal: `AI_Feed`

| # | Columna | Tipo | Descripción | Ejemplo |
|---|---|---|---|---|
| A | `fecha` | Datetime | Fecha de publicación original (UTC) | `2026-04-11 06:00` |
| B | `tipo` | String | `noticia` o `herramienta` | `herramienta` |
| C | `categoria` | String | Categoría granular (ver 7.2) | `Modelos` |
| D | `relevancia` | Integer | Puntuación IA del 1 al 10 | `9` |
| E | `nombre` | String | Título del artículo o nombre de la herramienta | `GPT-5 Turbo lanzado` |
| F | `link` | URL | Enlace directo al contenido original | `https://...` |
| G | `precio` | String | Precio si herramienta; `Noticia` si artículo | `$20/mes` o `Noticia` |
| H | `resumen` | String | Resumen de 2-4 frases generado por IA | `GPT-5 Turbo es...` |
| I | `tags` | String | 3-5 keywords separadas por comas | `GPT-5, OpenAI, LLM` |
| J | `fuente` | String | Nombre de la fuente | `TechCrunch` |
| K | `idioma` | String | `EN` o `ES` | `EN` |

### 7.2 Taxonomía de categorías

| Categoría | Descripción | Ejemplos |
|---|---|---|
| `Modelos` | Lanzamientos o actualizaciones de modelos de IA | GPT-5, Claude 4, Gemini 2.0 |
| `Herramientas` | Apps, APIs y plataformas nuevas | Cursor, Midjourney v7, Perplexity Pro |
| `Investigación` | Papers, estudios y avances técnicos | Paper de atención cuadrática, benchmark nuevo |
| `Industria` | Noticias corporativas, funding, adquisiciones | OpenAI recauda $5B, Google adquiere X |
| `Normativa` | Regulación, ética, política de IA | EU AI Act, copyright IA, restricciones |
| `Tutoriales` | Guías, how-tos, recursos educativos | Cómo usar RAG, fine-tuning tutorial |

### 7.3 Criterio de scoring de relevancia

La IA asigna el score basándose en:

| Puntuación | Criterio |
|---|---|
| 9-10 | Lanzamiento mayor de modelo frontier, cambio regulatorio global, adquisición >$1B |
| 7-8 | Nueva herramienta significativa, paper importante, funding destacado |
| 5-6 | Actualización de producto existente, noticia sectorial relevante |
| 3-4 | Tutorial interesante, noticia menor, herramienta nicho |
| 1-2 | Contenido redundante, poco impacto, muy específico |

### 7.4 Pestaña de control: `_meta`

| Columna | Descripción |
|---|---|
| `last_run` | Timestamp de la última ejecución exitosa |
| `items_total` | Total de ítems en AI_Feed |
| `items_last_run` | Ítems añadidos en la última ejecución |
| `errors_last_run` | Número de errores en la última ejecución |

### 7.5 Pestaña de archivo: `AI_Feed_Archive_{YYYY}`

Cuando `AI_Feed` supera 1.000 ítems, los ítems más antiguos se mueven a esta pestaña con la misma estructura de columnas.

---

## 8. Componentes del Sistema

### 8.1 `src/collector.py`

**Responsabilidad**: Obtener ítems crudos de todas las fuentes definidas en `config/sources.yaml`.

```
Funciones:

load_sources() → List[SourceConfig]
    Lee sources.yaml y devuelve lista de configuraciones.

fetch_rss(source: SourceConfig) → List[RawItem]
    Descarga y parsea el feed RSS con feedparser.
    Aplica filtros de calidad mínima (fecha, longitud título, URL válida).
    Timeout: 15 segundos. En caso de error: log + retorno lista vacía.

fetch_hackernews(config: SourceConfig) → List[RawItem]
    GET /v0/topstories.json → lista de IDs.
    Para cada ID (máx 100): GET /v0/item/{id}.json.
    Filtra por keywords y score > 10.
    Máximo 30 ítems por ejecución para no agotar cuota de Groq.

collect_all() → List[RawItem]
    Itera todas las fuentes. Combina resultados.
    Normaliza campos: title, url, published_at, source_name, language, default_type.
```

### 8.2 `src/enricher.py`

**Responsabilidad**: Obtener el contenido completo del artículo para mejorar la calidad de los resúmenes.

```
Funciones:

fetch_article_text(url: str) → str
    Descarga la página con requests (User-Agent: Mozilla/5.0).
    Extrae texto limpio con trafilatura.extract().
    Timeout: 10 segundos. Máximo 3.000 caracteres del resultado.
    En caso de error (paywall, timeout, JS requerido): devuelve descripción RSS original.
    No falla silenciosamente: registra en log qué URLs no pudieron enriquecerse.

enrich_all(items: List[RawItem]) → List[EnrichedItem]
    Aplica fetch_article_text a cada ítem.
    Paraleliza con ThreadPoolExecutor(max_workers=5) para reducir tiempo.
    Respeta un rate limit interno de 1 req/seg por dominio para no ser bloqueado.
```

### 8.3 `src/dedup.py`

**Responsabilidad**: Evitar procesar el mismo ítem más de una vez.

```
Funciones:

load_hashes() → Set[str]
    Lee data/hashes.json del repositorio.
    Si el archivo no existe, devuelve set vacío (primera ejecución).

filter_new(items: List[EnrichedItem], hashes: Set[str]) → List[EnrichedItem]
    Para cada ítem: calcula hash = SHA256(item.url.strip().lower()).
    Descarta ítems cuyo hash ya está en el set.
    Devuelve solo los nuevos.

save_hashes(new_hashes: Set[str])
    Carga hashes existentes, añade los nuevos, guarda data/hashes.json.
    El archivo se limita a los últimos 50.000 hashes para evitar crecimiento ilimitado.
    (50.000 hashes × ~32 bytes = ~1.6 MB — aceptable para un archivo en el repo)
```

### 8.4 `src/ai_enricher.py`

**Responsabilidad**: Enriquecer cada ítem con resumen, categoría, relevancia y tags usando IA.

```
Modelo primario: Groq llama-3.1-8b-instant
Modelo fallback: Gemini 1.5 Flash (google-generativeai SDK)
Temperatura: 0.2 (respuestas consistentes y factuales)

Prompt de sistema:
    "Eres un analista experto en inteligencia artificial.
     Dado el siguiente artículo, devuelve un JSON con estos campos:
     - resumen: string, 2-4 frases en el mismo idioma del artículo.
       Incluye el dato más relevante (cifra, nombre de modelo, empresa, impacto).
     - categoria: uno de [Modelos, Herramientas, Investigación, Industria, Normativa, Tutoriales]
     - relevancia: integer del 1 al 10 según el impacto real en el sector IA global.
     - tags: array de 3-5 strings, keywords específicas del artículo.
     Devuelve SOLO el JSON, sin markdown, sin explicaciones."

Funciones:

enrich_item(item: EnrichedItem, provider='groq') → AIResult
    Construye el prompt con título + contenido (máx 2.000 chars).
    Llama a la API (Groq o Gemini según provider).
    Parsea el JSON de respuesta.
    En caso de JSON malformado: reintenta hasta 2 veces.
    En caso de fallo total: devuelve valores por defecto (resumen truncado, cat='Industria', rel=5).

enrich_all(items: List[EnrichedItem]) → List[ProcessedItem]
    Itera items con retry automático en rate limit (espera exponencial).
    Si Groq falla 3 veces consecutivas: cambia a Gemini para el resto de ítems.
    Registra en log cuántos ítems usaron cada proveedor y cuántos usaron fallback.
```

### 8.5 `src/sheets_writer.py`

**Responsabilidad**: Escribir los ítems procesados en Google Sheets y mantener la política de retención.

```
Funciones:

connect() → gspread.Client
    Autentica con Service Account desde variable de entorno GOOGLE_CREDENTIALS_JSON.
    
write_items(sheet, items: List[ProcessedItem])
    Prepara lista de listas con los 11 campos en el orden correcto.
    Usa sheet.append_rows() (batch) para una sola llamada a la API.
    Actualiza la pestaña _meta con estadísticas de la ejecución.

enforce_retention(sheet, max_items=1000)
    Cuenta filas actuales.
    Si > max_items: mueve las filas más antiguas (excedente) a AI_Feed_Archive_{YYYY}.
    Crea la pestaña de archivo si no existe.
    Esta operación usa batch updates para minimizar llamadas a la API.

classify_precio(item: ProcessedItem) → str
    Si tipo='herramienta': intenta extraer precio del resumen con regex simple.
      Patrones: "$X/mo", "€X/mes", "free", "gratuito", "freemium", "open source".
      Si no encuentra: devuelve "Ver enlace".
    Si tipo='noticia': devuelve "Noticia".
```

### 8.6 `src/main.py` — Orquestador principal

```python
# Pseudocódigo del flujo principal

def main():
    log_start()
    
    # 1. Recopilar
    raw_items = collect_all()                    # collector.py
    log(f"Recopilados: {len(raw_items)} ítems")
    
    # 2. Enriquecer contenido
    enriched = enrich_all(raw_items)             # enricher.py
    
    # 3. Deduplicar
    hashes = load_hashes()                       # dedup.py
    new_items = filter_new(enriched, hashes)
    log(f"Nuevos (sin duplicados): {len(new_items)}")
    
    if not new_items:
        log("Sin nuevos ítems. Ejecución finalizada.")
        return
    
    # 4. Enriquecimiento IA
    processed = enrich_all_ai(new_items)         # ai_enricher.py
    
    # 5. Escribir en Sheets
    client = connect()
    sheet = client.open_by_key(SHEET_ID)
    write_items(sheet, processed)                # sheets_writer.py
    enforce_retention(sheet)
    
    # 6. Actualizar hashes
    new_hashes = {sha256(i.url) for i in new_items}
    save_hashes(new_hashes)                      # dedup.py
    
    # 7. Commit hashes.json (via git en el workflow)
    log_end(len(processed))
```

---

## 9. Flujo de Datos Completo

```
CADA 6 HORAS
     │
     ▼ [1] RECOPILACIÓN (~30s)
     feedparser × 10 fuentes RSS
     HN API (top 100 → filtrar por keywords → 30 max)
     Total estimado: 50-150 ítems crudos por ejecución
     │
     ▼ [2] FILTRO DE CALIDAD (~1s)
     ¿Fecha < 7 días? ¿URL válida? ¿Título > 5 palabras?
     Descarte típico: 20-30% de ítems
     │
     ▼ [3] ENRIQUECIMIENTO DE CONTENIDO (~45s)
     ThreadPoolExecutor(5) → requests.get(url) + trafilatura
     Timeout por URL: 10s
     Fallback: descripción RSS si falla
     │
     ▼ [4] DEDUPLICACIÓN (~1s)
     SHA256(url) ∉ hashes.json → nuevo
     SHA256(url) ∈ hashes.json → descartar
     Resultado típico: 10-40 ítems genuinamente nuevos
     │
     ▼ [5] ENRIQUECIMIENTO IA (~20-60s)
     Por cada ítem nuevo:
       POST Groq API (llama-3.1-8b-instant)
       → JSON: {resumen, categoria, relevancia, tags}
       Si Groq falla 3× → fallback a Gemini
       Si Gemini falla → valores por defecto
     │
     ▼ [6] ESCRITURA EN SHEETS (~3s)
     gspread.append_rows(all_rows) — una sola llamada batch
     Verificar retención → archivar si >1000 ítems
     Actualizar _meta
     │
     ▼ [7] COMMIT hashes.json (~5s)
     git add data/hashes.json
     git commit -m "chore: update hashes [skip ci]"
     git push
     │
     ▼ FIN
     Log: "Añadidos X ítems en Ys. Proveedor: Groq(X) Gemini(Y) Fallback(Z)"
     Total duración estimada: 2-3 minutos
```

---

## 10. APIs e Integraciones

### 10.1 Groq API (primario)

| Parámetro | Valor |
|---|---|
| Endpoint | `https://api.groq.com/openai/v1/chat/completions` |
| Modelo | `llama-3.1-8b-instant` |
| Límite gratuito | 14.400 req/día, 30 req/min |
| Consumo estimado | ~40 req/ejecución × 4 ejecuciones = ~160 req/día |
| Margen disponible | ~99% del límite gratuito libre |
| Autenticación | `GROQ_API_KEY` en GitHub Secrets |

### 10.2 Gemini API (fallback)

| Parámetro | Valor |
|---|---|
| Modelo | `gemini-1.5-flash` |
| Límite gratuito | 1.500 req/día |
| Activación | Solo si Groq falla 3 veces consecutivas |
| Autenticación | `GEMINI_API_KEY` en GitHub Secrets |

### 10.3 Google Sheets API v4

| Parámetro | Valor |
|---|---|
| Autenticación | Service Account JSON |
| Operaciones | `append_rows`, `get_all_values`, `batch_update` |
| Límite | 100 req/100s por usuario |
| Consumo estimado | ~10 req/ejecución (muy por debajo del límite) |
| Secret | `GOOGLE_CREDENTIALS_JSON` (JSON completo del Service Account) |

### 10.4 Hacker News Firebase API

| Parámetro | Valor |
|---|---|
| Base URL | `https://hacker-news.firebaseio.com/v0/` |
| Autenticación | Ninguna |
| Rate limit | Sin límite documentado |
| Ítems procesados | Máximo 30 por ejecución (filtrados por score y keywords) |

### 10.5 opensheet.elk.sh (bridge de consulta)

| Parámetro | Valor |
|---|---|
| URL | `https://opensheet.elk.sh/{SHEET_ID}/{sheet_name}` |
| Autenticación | Ninguna (la hoja debe ser pública en lectura) |
| Retorno | Array JSON limpio con headers de columna como keys |
| Uso | Solo por el dashboard HTML (lectura, no escritura) |
| Alternativa self-hosted | Fork de https://github.com/benborgers/opensheet |

---

## 11. Configuración y Despliegue

### 11.1 Estructura de archivos del repositorio

```
ai-news-aggregator/
├── index.html                      ← Dashboard público (GitHub Pages)
├── .github/
│   └── workflows/
│       └── aggregator.yml          ← GitHub Actions workflow
├── src/
│   ├── main.py                     ← Orquestador
│   ├── collector.py
│   ├── enricher.py
│   ├── dedup.py
│   ├── ai_enricher.py
│   └── sheets_writer.py
├── config/
│   └── sources.yaml                ← Fuentes configurables sin tocar código
├── data/
│   └── hashes.json                 ← Hashes de URLs procesadas (commiteado)
├── requirements.txt
└── README.md
```

### 11.2 GitHub Actions Workflow completo

```yaml
# .github/workflows/aggregator.yml
name: AI News Aggregator

on:
  schedule:
    - cron: '0 */6 * * *'     # 00:00, 06:00, 12:00, 18:00 UTC
  workflow_dispatch:            # Ejecución manual desde GitHub UI

permissions:
  contents: write               # Necesario para el commit de hashes.json

jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: 15

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run aggregator
        run: python src/main.py
        env:
          GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          GOOGLE_CREDENTIALS_JSON: ${{ secrets.GOOGLE_CREDENTIALS_JSON }}
          SHEET_ID: ${{ secrets.SHEET_ID }}

      - name: Commit updated hashes
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/hashes.json
          git diff --staged --quiet || git commit -m "chore: update processed hashes [skip ci]"
          git push
```

**Nota**: el tag `[skip ci]` en el commit message evita que el push del commit de hashes dispare otra ejecución del workflow en bucle.

### 11.3 Dependencias (`requirements.txt`)

```
feedparser==6.0.11
requests==2.32.3
trafilatura==1.12.0
groq==0.8.0
google-generativeai==0.7.2
gspread==6.1.2
google-auth==2.29.0
pyyaml==6.0.1
python-dateutil==2.9.0
```

### 11.4 Pasos de configuración inicial (guía completa)

**Paso 1 — Google Cloud (10 minutos)**
1. Ir a https://console.cloud.google.com → crear proyecto nuevo.
2. Habilitar "Google Sheets API" en la biblioteca de APIs.
3. Crear credencial: IAM → Cuentas de servicio → Crear → descargar JSON.
4. Guardar ese JSON; lo usaremos como secret.

**Paso 2 — Google Sheets (2 minutos)**
1. Crear una nueva Google Sheet en https://sheets.google.com.
2. Crear dos pestañas: `AI_Feed` y `_meta`.
3. En `AI_Feed`, añadir la fila de encabezados: `fecha | tipo | categoria | relevancia | nombre | link | precio | resumen | tags | fuente | idioma`.
4. Compartir el Sheet: "Cualquiera con el enlace puede ver" (para el dashboard público).
5. También compartir con el email de la Service Account con permisos de Editor.
6. Copiar el ID del Sheet (la parte de la URL entre `/d/` y `/edit`).

**Paso 3 — Groq y Gemini API Keys (5 minutos)**
1. Groq: registrarse en https://console.groq.com → API Keys → Create.
2. Gemini: registrarse en https://aistudio.google.com → Get API Key → Create.

**Paso 4 — GitHub Secrets (3 minutos)**
1. En el repositorio: Settings → Secrets and variables → Actions → New repository secret.
2. Añadir:
   - `GROQ_API_KEY`: tu API key de Groq.
   - `GEMINI_API_KEY`: tu API key de Gemini.
   - `GOOGLE_CREDENTIALS_JSON`: contenido completo del JSON de la Service Account.
   - `SHEET_ID`: ID de tu Google Sheet.

**Paso 5 — GitHub Pages (1 minuto)**
1. En el repositorio: Settings → Pages → Source: Deploy from a branch → Branch: `main` → Folder: `/ (root)`.
2. Guardar. GitHub Pages publica `index.html` en `https://{usuario}.github.io/{repo}/`.

**Paso 6 — Primera ejecución (1 click)**
1. Ir a Actions → "AI News Aggregator" → "Run workflow".
2. Verificar que termina en verde.
3. Visitar `https://{usuario}.github.io/{repo}/` → el dashboard muestra los primeros datos.

---

## 12. Gestión de Errores y Resiliencia

### 12.1 Matriz de fallos

| Escenario | Comportamiento | Impacto en datos |
|---|---|---|
| RSS feed no disponible | Log de aviso + skip de esa fuente | Ninguno (resto de fuentes continúan) |
| URL de artículo no accesible | Usa descripción RSS como contenido | Resumen de menor calidad |
| Groq rate limit | Espera exponencial (1s, 2s, 4s) + reintento × 3 | Ninguno |
| Groq falla 3 veces seguidas | Cambia a Gemini para el resto del batch | Ninguno |
| Groq y Gemini ambos fallan | Resumen = extracto original (200 chars), cat='Industria', rel=5 | Calidad reducida, sin pérdida de datos |
| JSON malformado de IA | Reintento con prompt simplificado × 2 | Ninguno |
| Google Sheets API falla | Reintento exponencial × 3 | Si falla todo: el pipeline termina con error |
| Error de red en GitHub Actions | GitHub Actions reintenta automáticamente el job | Ninguno |
| Deduplicación: hashes.json corrupto | Detecta JSON inválido → inicializa set vacío + log de alerta | Posibles duplicados en esa ejecución |

### 12.2 Monitoreo básico (sin coste adicional)

GitHub Actions envía automáticamente un email al dueño del repositorio cuando:
- El workflow termina con estado `failure`.
- El workflow termina con estado `cancelled` (timeout de 15 minutos).

Esto es suficiente para saber cuándo el sistema está roto sin configurar nada adicional. La notificación llegará al email asociado a la cuenta de GitHub.

---

## 13. Política de Retención de Datos

**Problema**: sin límite, el Sheet crece indefinidamente. A 40 ítems/día × 365 días = 14.600 ítems/año. Google Sheets empieza a ralentizarse con hojas de más de ~5.000 filas con fórmulas activas.

**Solución implementada en v2.0**:

```
Tras cada escritura:
  IF filas en AI_Feed > 1.000:
    1. Seleccionar las (total - 1.000) filas más antiguas.
    2. Copiar al pestaña AI_Feed_Archive_{YYYY_actual}.
       (Se crea si no existe; si existe, se añade al final)
    3. Eliminar esas filas de AI_Feed.
    
Resultado: AI_Feed siempre tiene ≤ 1.000 ítems (los más recientes).
Los históricos se conservan en pestañas de archivo por año.
```

El dashboard muestra los últimos 1.000 ítems, que equivalen aproximadamente a **25 días de contenido** con el ritmo estimado de publicación.

---

## 14. Estimación de Recursos y Costes

### 14.1 Consumo de APIs (por día)

| API | Calls/día | Límite gratuito/día | Uso del límite |
|---|---|---|---|
| Groq (llama-3.1-8b-instant) | ~160 | 14.400 | **1.1%** |
| Gemini 1.5 Flash (fallback) | ~0-20 | 1.500 | **<1%** |
| Google Sheets API | ~40 | 300/100s | **<1%** |
| GitHub Actions | ~12 min/día | 2.000 min/mes (67/día) | **~18%** |

### 14.2 Costes mensuales

| Servicio | Coste |
|---|---|
| GitHub Actions + GitHub Pages | **0 €** |
| Groq API | **0 €** |
| Gemini API | **0 €** |
| Google Sheets API | **0 €** |
| opensheet.elk.sh | **0 €** |
| **Total** | **0 €/mes** |

---

## 15. Roadmap — Mejoras Futuras

### v2.1 — Calidad de datos
- Extracción de precio con scraping de página real para herramientas de ProductHunt.
- Deduplicación semántica: detectar misma noticia de distintas fuentes usando embeddings.
- Detección automática de idioma con `langdetect` en lugar de asumir el idioma de la fuente.

### v2.2 — Experiencia de consulta
- Filtro por rango de fechas en el dashboard.
- Vista "solo herramientas" con columna de precio visible.
- Exportar a CSV directamente desde el dashboard.
- Feed RSS del propio dashboard para suscribirse con un lector de feeds.

### v3.0 — Inteligencia avanzada
- Detección de tendencias: topics que aparecen con alta frecuencia en los últimos 7 días.
- Digest semanal en PDF generado automáticamente con los 10 ítems de mayor relevancia.
- Notificaciones opcionales vía Telegram cuando relevancia ≥ 9.
- Soporte para fuentes con JavaScript dinámico usando Playwright en Actions.

---

*Documento redactado en Abril 2026. Versión 2.0. Supersede completamente la versión 1.0.*
