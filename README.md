# QA de apps iOS con Duplicación del iPhone

Herramientas para que una IA con acceso a la terminal (Claude Code, Codex CLI, Gemini CLI, el agente de Cursor, etc.) recorra una app instalada en un iPhone real a través de la **Duplicación del iPhone** de macOS, y genere un reporte HTML con:

- capturas de cada paso, agrupadas por flujo;
- hallazgos clasificados por severidad y categoría;
- textos en **portugués** y claves de traducción sin resolver (p. ej. `offshore.home.title`), además de palabras sin tilde. **El inglés está permitido** y no se marca;
- tiempo de espera entre pantallas y cargas que nunca terminan;
- toques que no cambiaron la pantalla.

No necesita el código fuente de la app ni cable USB: funciona con la app tal como está instalada en el teléfono.

## Cómo funciona

| Archivo | Qué hace |
|---|---|
| `tools/mirror.swift` | Controla la ventana de Duplicación del iPhone: captura, OCR (Apple Vision, español e inglés), toques, scroll, teclado y comparación de píxeles. |
| `tools/qa.py` | Ejecuta cada paso: hace la acción, espera a que la pantalla quede estable midiendo el tiempo, guarda captura y texto, y aplica los detectores de portugués, tildes y formatos. También registra los hallazgos. |
| `tools/report.py` | Genera `runs/<run>/reporte.html` a partir de los pasos y hallazgos. |

Los scripts son las herramientas. **La IA decide qué tocar, revisa cada pantalla y registra los hallazgos**, así que la calidad de la revisión depende de la IA y de las instrucciones que le des (ver [Prompt para la IA](#prompt-para-la-ia)).

## Requisitos

- Mac con **macOS 15 (Sequoia) o superior** y un iPhone compatible con la Duplicación del iPhone, ambos con el mismo Apple ID.
- **Xcode** o sus herramientas de línea de comandos (`xcode-select --install`), para compilar `mirror.swift`.
- **Python 3.10+**, sin dependencias externas.
- Una IA que pueda **ejecutar comandos y ver imágenes** en tu Mac. ChatGPT o Claude en la web no sirven, porque no pueden ejecutar nada en tu equipo.

## Instalación

1. Compila el controlador:

   ```bash
   swiftc -O tools/mirror.swift -o tools/mirror
   ```

2. Da permisos a la app desde la que corre la IA (Terminal, iTerm, VS Code, Cursor…), en **Ajustes del Sistema → Privacidad y seguridad**:
   - **Grabación de pantalla y audio del sistema**: para capturar la ventana del iPhone.
   - **Accesibilidad**: para enviar toques y teclas.

   Después **cierra y vuelve a abrir esa app** (Cmd+Q). macOS solo aplica el permiso de grabación tras reiniciarla.

3. Abre la **Duplicación del iPhone**, desbloquea el teléfono, **inicia sesión en la app tú mismo** y déjala en la pantalla desde donde empieza la revisión.

4. Comprueba que todo funciona:

   ```bash
   tools/mirror info                       # debe mostrar el tamaño de la ventana
   python3 tools/qa.py start prueba
   python3 tools/qa.py step inicio "Pantalla actual" none
   ```

   El último comando imprime los textos de la pantalla con sus coordenadas. Si dice `could not create image from window`, falta el permiso de grabación o no reiniciaste la app.

## Prompt para la IA

Abre la IA en esta carpeta y pégale algo así, ajustando la sección y los flujos:

```text
Lee README.md y haz una revisión de QA de la sección <NOMBRE> de la app que está
abierta en la Duplicación del iPhone, usando tools/qa.py y tools/report.py.

1. Inicia un run: python3 tools/qa.py start <nombre>-<fecha>
2. Recorre todos los flujos de la sección: cada botón, pestaña, filtro, detalle,
   formulario y mensaje de ayuda. Baja con scroll hasta el final de cada pantalla.
   En los formularios prueba valores inválidos (vacío, bajo el mínimo, sobre el
   máximo) y uno válido.
3. Usa SIEMPRE qa.py step para cada acción, con un nombre de flujo corto y una
   descripción clara. Mira la captura (runs/<run>/shots/NNN.png) cuando el texto
   no baste para entender la pantalla.
4. Registra cada problema con qa.py issue, solo después de verificarlo en la
   captura: errores, datos que no cuadran entre pantallas, textos en portugués,
   faltas de ortografía, formatos inconsistentes, problemas de diseño,
   lentitud (> 3 s) y toques que no responden.
   El inglés está permitido: NO registres textos en inglés como hallazgo.
5. Al terminar, genera el reporte con python3 tools/report.py y resume los
   hallazgos de severidad alta.

Reglas de seguridad:
- No escribas contraseñas ni datos personales. Si la app pide login, detente y avísame.
- No toques botones finales que ejecuten operaciones reales (Confirmar, Invertir,
  Transferir, Firmar, Cancelar orden). Llega hasta esa pantalla y vuelve atrás.
- No abras enlaces externos ni descargues archivos.
```

## Referencia de comandos

Las coordenadas son **normalizadas** respecto a la ventana de la Duplicación: `0,0` es la esquina superior izquierda y `1,1` la inferior derecha. `qa.py step` y `qa.py screen` imprimen el centro de cada texto en ese formato.

### `qa.py`

```bash
python3 tools/qa.py start <run>                                    # crea runs/<run>/ y lo deja activo
python3 tools/qa.py screen                                         # textos de la pantalla actual, sin registrar paso

python3 tools/qa.py step <flujo> "<descripción>" tapt "<texto>" [n] # toca el texto visible (n-ésima coincidencia)
python3 tools/qa.py step <flujo> "<descripción>" tap <x> <y>        # toca coordenadas
python3 tools/qa.py step <flujo> "<descripción>" scroll down|up [px] # rueda del mouse (por defecto 400 px)
python3 tools/qa.py step <flujo> "<descripción>" type "<texto>"     # escribe en el campo con foco
python3 tools/qa.py step <flujo> "<descripción>" none               # solo captura el estado actual
python3 tools/qa.py step <flujo> "<descripción>" swipe <x1> <y1> <x2> <y2>

python3 tools/qa.py issue <alta|media|baja> <categoria> "<descripción>" [paso]

python3 tools/report.py [runs/<run>]                               # por defecto, el run activo
```

Cada `step` imprime el número de paso, el tiempo hasta que la pantalla quedó estable, avisos (`la pantalla NO cambió`, `lento`, `TIMEOUT`), los textos visibles y las detecciones automáticas.

**Categorías de hallazgo:** `error`, `datos`, `i18n`, `ortografia`, `texto`, `formato`, `ux`, `ui`, `rendimiento`, `navegacion`, `interaccion`, `contenido`.

### `tools/mirror` (bajo nivel)

```bash
tools/mirror info                       # posición y tamaño de la ventana
tools/mirror shot <archivo.png>         # captura solo la ventana del iPhone
tools/mirror ocr <archivo.png>          # JSON con texto y posición de cada línea
tools/mirror diff <a.png> <b.png>       # fracción de píxeles distintos
tools/mirror tap <x> <y>
tools/mirror scroll <x> <y> <px>        # negativo = bajar
tools/mirror type "<texto>"
tools/mirror key home|switcher|return|delete|escape
```

## Consejos y limitaciones conocidas

- **Volver atrás:** toca la flecha ← de la app (`tap 0.1 0.138` en un iPhone con la ventana estándar). El gesto `back` suele no funcionar en la Duplicación.
- **Scroll:** arrastrar no mueve las listas en la Duplicación; usa siempre `scroll`.
- **Borrar un campo:** `tools/mirror key delete` varias veces.
- **`tapt`** busca primero una coincidencia exacta y después parcial. Si toca el elemento equivocado, usa `tap` con las coordenadas que imprime `screen`.
- **Tiempos:** incluyen unos 0,3 s de latencia de la Duplicación. Un `TIMEOUT` (25 s) significa que la pantalla siguió animándose (skeleton o spinner) y nunca se estabilizó.
- **Idioma:** solo se marca el portugués (el inglés está permitido). La detección es heurística (OCR + lista de palabras portuguesas que no existen en español, en `PT_WORDS` al inicio de `qa.py`). Confirma cada caso en la captura antes de registrarlo como hallazgo.
- **Datos sensibles:** `runs/` guarda capturas con la información de la cuenta usada en la prueba. Está en `.gitignore`; no lo subas a repositorios ni lo publiques.
- Mientras la Duplicación está activa, el iPhone queda bloqueado y no se puede usar directamente.
