# Portable Hermes Agent

<p align="center">
  <a href="README.md"><img src="https://img.shields.io/badge/Language-English-blue?style=for-the-badge" alt="English"></a>
  <a href="README.zh-TW.md"><img src="https://img.shields.io/badge/語言-繁體中文-purple?style=for-the-badge" alt="繁體中文"></a>
  <a href="README.zh-CN.md"><img src="https://img.shields.io/badge/语言-简体中文-red?style=for-the-badge" alt="简体中文"></a>
  <a href="README.es.md"><img src="https://img.shields.io/badge/Idioma-Español-yellow?style=for-the-badge" alt="Español"></a>
  <a href="README.ur-pk.md"><img src="https://img.shields.io/badge/زبان-اردو-green?style=for-the-badge" alt="اردو"></a>
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

Descarga el archivo llamado `portable-hermes-agent-v*.zip` desde las [versiones de Portable Hermes Agent](https://github.com/aivrar/portable-hermes-agent/releases/latest) y extráelo en una carpeta normal, por ejemplo `C:\Users\TuNombre\Portable-Hermes-Agent`. Evita carpetas protegidas como `C:\Program Files`.

**No uses el instalador de `NousResearch/hermes-agent` para instalar esta versión portátil:** es un proyecto distinto y no contiene los lanzadores ni las herramientas personalizadas de esta distribución.

### 2. Iniciar

Haz doble clic en `START.bat`. En el primer inicio prepara Python integrado, dependencias, el SDK de LM Studio y las herramientas de Node.js **dentro de la carpeta portátil**. No requiere Python ni Node.js instalados en el sistema, ni permisos de administrador.

También puedes ejecutar `install.bat` para la preparación manual, o `scripts\install.ps1` desde PowerShell.

| Archivo | Función |
|---|---|
| `START.bat` | Inicio más sencillo de la interfaz gráfica |
| `UPDATE.bat` | Actualización de la distribución portátil |
| `hermes_gui.bat` | Abrir la interfaz gráfica |
| `hermes.bat` | Abrir la línea de comandos |

### 3. Configurar un modelo

**En la nube:** abre **Archivo > Configurar Clave API**, elige OpenRouter, crea una clave y pégala en el asistente.

**En tu equipo:** instala [LM Studio](https://lmstudio.ai), descarga un modelo, inicia su servidor y abre **LM Studio (Modelos Locales)** en el menú de la interfaz. Carga el modelo y selecciona **Usar para el Chat**. Para modelos locales se recomienda una GPU NVIDIA con al menos 8 GB.

---

## Dos tipos de actualización

Portable Hermes tiene **dos vías independientes**. Actualizar una no actualiza automáticamente la otra.

| Vía | Origen | Qué actualiza |
|---|---|---|
| **Distribución portátil** | `aivrar/portable-hermes-agent` | Lanzadores de Windows, interfaz gráfica, integraciones, herramientas portátiles y la versión del agente probada con este repositorio |
| **Agente Hermes original** | `NousResearch/hermes-agent` | Código más reciente del núcleo del agente, conservando los archivos propios de Portable Hermes |

Para la actualización normal, cierra Hermes y ejecuta `UPDATE.bat`. También puedes usar `hermes.bat update --backup --yes`. La actualización conserva los datos de ejecución, las herramientas personalizadas, extensiones y el Python integrado.

Si además deseas código más reciente del proyecto original, inicia Hermes y pídele primero que **compruebe** si hay una actualización del agente original, sin instalarla. Si decides aplicarla, pídele que actualice el agente original **conservando Portable Hermes**. Reinicia Hermes después para cargar los módulos nuevos. Una instalación desde ZIP puede actualizarse aunque no tenga historial de Git.

Consulta [Cómo mantener actualizado Portable Hermes](https://github.com/aivrar/portable-hermes-agent/wiki/Keeping-Portable-Hermes-Updated) para el proceso completo, copias de seguridad y solución de problemas.

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
