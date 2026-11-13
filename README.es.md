# Portable Hermes Agent

<p align="center">
  <a href="README.md"><img src="https://img.shields.io/badge/Language-English-blue?style=for-the-badge" alt="English"></a>
  <a href="README.zh-TW.md"><img src="https://img.shields.io/badge/Language-Traditional_Chinese-purple?style=for-the-badge" alt="Traditional Chinese"></a>
  <a href="README.zh-CN.md"><img src="https://img.shields.io/badge/Language-Simplified_Chinese-red?style=for-the-badge" alt="Simplified Chinese"></a>
  <a href="README.es.md"><img src="https://img.shields.io/badge/Language-Spanish-yellow?style=for-the-badge" alt="Spanish"></a>
  <a href="README.ur-pk.md"><img src="https://img.shields.io/badge/Language-Urdu-green?style=for-the-badge" alt="Urdu"></a>
</p>

**Agente de IA portátil para Windows**: interfaz gráfica, 100 herramientas, modelos locales mediante LM Studio, voz, música, ComfyUI, flujos de trabajo y creación de herramientas. Sin instalación en el sistema, Docker ni permisos de administrador.

Basado en [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) (licencia MIT), con personalizaciones para usuarios no técnicos. Este repositorio es **la distribución portátil de aivrar**, no el instalador del proyecto original.

---

## Funciones

### Interfaz gráfica

- Interfaz Tkinter con tema oscuro, chat, barra lateral e historial de sesiones.
- Idiomas: inglés, chino tradicional, chino simplificado y español; se pueden cambiar sin reiniciar.
- Imágenes adjuntas con miniaturas para modelos con visión.
- Modo guiado que funciona incluso sin un modelo conectado.
- Asistente de configuración de claves API por servicio.
- Panel de permisos para controlar el acceso a archivos, red y sistema.

### Herramientas

| Conjunto | Herramientas | Función |
|---|---:|---|
| **LM Studio** | 10 | Cargar y descargar modelos, buscar en Hugging Face, tokenizar, crear embeddings, chatear y gestionar la clave API |
| **Música** | 7 | Generar música, gestionar modelos y trabajadores de GPU, explorar resultados |
| **Voz (TTS)** | 7 | Texto a voz, modelos de voz, clonación, trabajos |
| **ComfyUI** | 7 | Generar imágenes y gestionar instancias, modelos y nodos |
| **Flujos de trabajo** | 6 | Crear, ejecutar, programar y gestionar automatizaciones |
| **Creador de herramientas** | 3 | Crear herramientas de API o Python en tiempo de ejecución |
| **Serper, guía, GPU y modelos** | 4 | Búsqueda, manual integrado, estado de GPU y cambio de modelo |
| **Actualización de Hermes** | 2 | Actualizar el agente original conservando las funciones portátiles |

También se incluyen las herramientas del agente original: búsqueda web, archivos, navegador, terminal, memoria, habilidades, mensajería y otras.

El panel de LM Studio guarda la dirección del servidor y la clave API en el `HERMES_HOME` activo (`.lmstudio_config`), fuera del código de la aplicación. Ambas vías de actualización conservan estos datos; el archivo no se incluye en las descargas. Mantén la clave en privado. Borrar el campo y pulsar **Guardar** elimina la clave guardada. El SDK opcional necesita compatibilidad con `api_token` para cargar modelos con autenticación; la búsqueda REST y el chat siguen disponibles sin esa conexión del SDK.

### Extensiones

Tres servidores portátiles de [aivrar](https://github.com/aivrar), instalados al usarlos por primera vez:

| Extensión | Puerto | Uso |
|---|---:|---|
| [Servidor de voz](https://github.com/aivrar/portable-tts-server) | 8200 | Modelos TTS y clonación de voz |
| [Servidor de música](https://github.com/aivrar/portable-music-server) | 9150 | Modelos de música y efectos de sonido |
| [ComfyUI](https://github.com/aivrar/comfyui-portable-installer) | 5000 | Generación de imágenes |

Los flujos de trabajo conectan herramientas con condiciones, bucles, ejecución paralela y programación. El creador de herramientas permite añadir integraciones de API o Python; las herramientas creadas se conservan entre sesiones.

---

## Inicio rápido

### 1. Descargar

Descarga el archivo llamado `portable-hermes-agent-v*.zip` desde las [versiones de Portable Hermes Agent](https://github.com/aivrar/portable-hermes-agent/releases/latest) y extráelo en una carpeta normal, por ejemplo `C:\Users\TuNombre\Portable-Hermes-Agent`. Evita carpetas protegidas como `C:\Program Files`. La ruta puede tener espacios, pero no los caracteres `!`, `%` ni `^`: los lanzadores no se inician desde una carpeta así.

**No uses el instalador de `NousResearch/hermes-agent` para instalar esta versión portátil:** es un proyecto distinto y no contiene los lanzadores ni las herramientas personalizadas de esta distribución.

### 2. Iniciar

Haz doble clic en `START.bat`. En el primer inicio descarga Python 3.14 integrado, el **núcleo más reciente de Hermes Agent desde `NousResearch/hermes-agent`**, sus dependencias exactas y el SDK de LM Studio **dentro de la carpeta portátil**. No requiere Python instalado en el sistema ni permisos de administrador. Antes de terminar, comprueba en un proceso aparte que el núcleo nuevo funciona con las herramientas portátiles y la interfaz gráfica.

También puedes ejecutar `install.bat` para la preparación manual, o `install.bat --yes` para una instalación sin preguntas.

| Archivo | Función |
|---|---|
| `START.bat` | Inicio más sencillo de la interfaz gráfica |
| `UPDATE.bat` | Actualizar la parte portátil y, si lo confirmas, el núcleo |
| `hermes_gui.bat` | Abrir la interfaz gráfica |
| `hermes.bat` | Abrir la línea de comandos |

### 3. Configurar un modelo

**En la nube:** abre **Archivo > Configurar Clave API**, elige OpenRouter, crea una clave y pégala en el asistente.

**En tu equipo:** instala [LM Studio](https://lmstudio.ai), descarga un modelo, inicia su servidor y abre **LM Studio (Modelos Locales)** en el menú de la interfaz. Carga el modelo y selecciona **Usar para el Chat**. Para modelos locales se recomienda una GPU NVIDIA con al menos 8 GB.

---

## Dos tipos de actualización

Portable Hermes tiene **dos partes que se actualizan por separado**:

| Parte | Origen | Qué contiene |
|---|---|---|
| **Parte portátil** | [versiones de `aivrar/portable-hermes-agent`](https://github.com/aivrar/portable-hermes-agent/releases/latest) | Lanzadores de Windows, interfaz gráfica, herramientas y habilidades portátiles, instalador y actualizador |
| **Núcleo de Hermes** | `NousResearch/hermes-agent` (rama `main` más reciente) | El agente en sí |

Cierra Hermes y ejecuta `UPDATE.bat`. Primero actualiza la parte portátil (comprueba cada archivo, sustituye solo archivos portátiles y deshace todo si algo falla). Después indica cuántos cambios lleva de retraso el núcleo y pregunta si quieres actualizarlo. Sin preguntas: `UPDATE.bat --yes` (solo la parte portátil) o `UPDATE.bat --yes --core` (ambas). También puedes pedirle a Hermes en el chat que compruebe o instale la actualización del núcleo.

Si vienes de la versión v1.4.18 o anterior, la primera ejecución de `UPDATE.bat` instala los nuevos lanzadores y te pide ejecutar `UPDATE.bat` otra vez; la segunda termina la actualización.

**Cuando el núcleo nuevo necesita un Python más reciente** (las instalaciones de v1.4.18 y anteriores tienen Python 3.13 y el núcleo actual necesita 3.14), el paso del núcleo explica lo que va a pasar y pregunta `Upgrade the portable Python to 3.14.9 now? [y/N]`. Si respondes `y`, cambia el nombre de `python_embedded` a `python_embedded.old-<versión>` (se conserva, no se borra), descarga el nuevo Python (unos 18 MB) y los paquetes (normalmente 150-300 MB) e instala el núcleo. Si falla, se deshace todo. Si respondes `N`, no cambia nada. `UPDATE.bat --yes --core` lo hace sin preguntar. Borra tú mismo la carpeta antigua cuando Hermes funcione.

El núcleo nuevo se prepara y se prueba en un proceso aparte antes de reemplazar ningún archivo; si algo falla, los archivos vuelven a su estado anterior y los paquetes cambiados se restauran y se comprueban (si no se pueden restaurar todos, la actualización lo dice y basta con ejecutar `UPDATE.bat` de nuevo). Nunca se modifican `.env`, `cli-config.yaml`, la carpeta `HERMES_HOME` (herramientas personalizadas, configuración de LM Studio e idioma), `extensions\` ni `workflows\`; `python_embedded\` solo cambia al instalar los paquetes que necesita el núcleo y en la actualización de Python descrita arriba. Reinicia Hermes después de actualizar el núcleo. Las copias de Git (desarrolladores) se actualizan con `git pull`.

---

## Requisitos y documentación

- Windows 10 u 11.
- Conexión a Internet para IA en la nube, o una GPU adecuada para modelos locales.
- No requiere permisos de administrador, Python del sistema ni Docker.

Hay una guía consultable dentro del agente (`search_guide`). El [manual en PDF](https://github.com/aivrar/portable-hermes-agent/releases/latest) se incluye en cada versión. Para los detalles técnicos y novedades que aún no estén traducidos, consulta el [README portátil en inglés](README.md).

---

## Créditos y licencia

- Framework original: [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent), licencia MIT.
- Extensiones portátiles: [aivrar](https://github.com/aivrar).
- Herramientas personalizadas, interfaz e integraciones: creadas con [Claude Code](https://claude.ai/claude-code).

Licencia MIT; consulta [LICENSE](LICENSE). Copyright del framework original © 2025 Nous Research.
