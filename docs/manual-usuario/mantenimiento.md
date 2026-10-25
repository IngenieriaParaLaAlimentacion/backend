# Mantener y verificar el manual

## Fuente única y alcance

El contenido editorial vive en `docs/manual-usuario/` del backend. App y backoffice se documentan juntos. Las issues de referencia son [backoffice#110](https://github.com/IngenieriaParaLaAlimentacion/backoffice/issues/110) y [app_mobile#95](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/issues/95).

Antes de otra edición, fijar las revisiones de los tres repositorios, revisar las rutas y los permisos, y actualizar el inventario de cobertura. No publicar una captura del formulario como prueba de que el guardado o una integración externa funcionaron.

## Entorno de la edición del 25/10/2026

| Componente | Configuración |
|---|---|
| Backend | `99a1acb`, HTTP en `127.0.0.1:8080`. |
| Backoffice | `6d79a17`, Next.js en `localhost:3001`, API local. |
| App | `b856633`, variante `tstDebug`, API `http://10.0.2.2:8080/`. |
| Datos | PostgreSQL local dedicado, puerto `55432`, usuario/base `manual`; Redis local en `56379`. |
| Navegador | Chrome mediante Playwright, 1440 × 1000, locale `es-AR`, huso de Buenos Aires. |
| Android | AVD dedicado `IPA_Manual`, Pixel 9 Pro, API 36, `google_apis_playstore`, `arm64-v8a`. |

Las copias de trabajo, logs, descargas y capturas originales están bajo `.context/manual/`. Las imágenes aprobadas para el manual se copian a `assets/`. No se modifican los checkouts de trabajo de otras personas ni se conectan las pruebas a producción.

## Preparar datos y ejecutar las capturas

Requisitos: checkouts de los tres repositorios en las revisiones indicadas; Node, JDK 21, Android SDK con API 36 y el AVD; PostgreSQL con `pg_trgm`, Redis y las dependencias del backend. Para el backoffice usar `npm ci`; para el backend instalar su lockfile. Ejecutar las migraciones Alembic y los seeds existentes del superadministrador y catálogo antes del fixture del manual.

Configurar el backend local con `DATABASE_URL=postgresql+asyncpg://manual@127.0.0.1:55432/manual`, Redis en `redis://127.0.0.1:56379/0` y límites de login altos para el entorno de captura. El script del fixture rechaza una base distinta de la dedicada al manual.

Después de preparar la base, mantener el backend levantado en una terminal. Para reproducir también las recetas y la carga manual con foto, usar el servidor de demostración explicado más abajo. En otra terminal, desde el checkout del backoffice, iniciar:

```bash
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8080 npm run dev -- --port 3001
```

Abrir el AVD `IPA_Manual`, instalar la app de prueba y comprobar que la API responda antes de ejecutar el fixture y los recorridos. El HTML final no necesita que esos servicios sigan levantados.

Desde el checkout del backend de captura, con su entorno virtual activo y `PYTHONPATH` apuntando a ese checkout:

```bash
python /ruta/al/workspace/scripts/manual/seed.py --output ../fixture.json
```

El fixture crea cuentas ficticias para `superadmin`, `admin`, `analyst` y `field_worker` con emails terminados en `@manual.example` y contraseña `Manual2026!`. Son credenciales exclusivamente locales. Crea un comedor, sujetos y mediciones, encuestas activas y stock de demostración; usa identificadores estables para sus cargas.

Desde el workspace del manual:

```bash
npm ci --prefix scripts/manual
node scripts/manual/capture-web.mjs
python3 scripts/manual/capture-android.py login
python3 scripts/manual/capture-android.py talla
python3 scripts/manual/capture-android.py encuestas
python3 scripts/manual/capture-android.py nutrir
python scripts/manual/make-receipt.py
python3 scripts/manual/capture-android.py recibos
python3 scripts/manual/capture-android.py recetas
python3 scripts/manual/capture-android.py perfil
python3 scripts/manual/capture-android.py apoyos
```

El driver Android comprueba que el dispositivo sea el AVD `IPA_Manual`. Requiere la app `tst` instalada, autenticada con la cuenta ficticia y con **Comedor Semillas del Sur** seleccionado. Cada escenario reinicia la actividad conservando sus datos. El escenario de medición genera un registro nuevo: no se debe correr contra una base compartida.

La fase `login` prepara la sesión si la app es nueva. Las dependencias del render y de la imagen de prueba están fijadas en `scripts/manual/requirements.txt`; instalarlas en el entorno Python de documentación. La fase `recibos` conserva y captura la incompatibilidad de esta revisión y continúa por la alternativa manual.

La fase `apoyos` captura el selector de comedor, las encuestas leídas sin conexión, el detalle de un movimiento y la confirmación de cierre de sesión, que cancela sin salir de la cuenta. Para actualizar solo las capturas web complementarias, usar `node scripts/manual/capture-web.mjs --extra-only`; conserva las entradas anteriores del registro de capturas.

Para compilar la app de captura, configurar `local.properties` con el SDK y `api_url_tst=http://10.0.2.2:8080/`, y ejecutar:

```bash
./gradlew :composeApp:assembleTstDebug --no-daemon
adb install -r composeApp/build/outputs/apk/tst/debug/composeApp-tst-debug.apk
```

Para comprobar trabajo sin conexión se deshabilitan las redes del AVD y después se restauran en un bloque `finally`. No usar `adb reverse` en ese escenario: el túnel puede mantener acceso al servidor aun al desactivar las radios y dar una prueba engañosa.

## Servicios externos de demostración

`scripts/manual/demo_server.py` proporciona un cliente de respuestas fijas para recibos y recetas, y guarda las fotos en un directorio local. Se ejecuta con el código del backend real en su `PYTHONPATH`:

```bash
PYTHONPATH=.:/ruta/al/workspace/scripts/manual \
  python -m uvicorn demo_server:app --host 127.0.0.1 --port 8080
```

El servidor rechaza una base que no sea la dedicada al manual. Mantiene los endpoints, la autenticación, el catálogo, los cálculos, las validaciones y las transacciones del backend. Sustituye solo la respuesta del modelo y el almacenamiento de objetos. **Estas capturas no validan Gemini, la extracción óptica real ni R2.** La propuesta de arroz es un ejemplo de interfaz con stock limitado; no representa una recomendación editorial del manual.

La entrega de emails se debe verificar con un buzón de prueba antes de considerar completados los recorridos de invitación, recuperación y verificación. Nunca incluir enlaces con tokens en el manual ni en los manifests versionados.

## Incompatibilidad encontrada en recibos

Con backend `99a1acb` y app `b856633`, `POST /api/v1/food-intakes/from-photo` devuelve 200 con líneas que no contienen `needs_review`. `ReceiptLineDto` en la app declara ese campo obligatorio sin valor por defecto. El log de Android confirma `JsonConvertException: Field 'needs_review' is required` en `$.lines[0]`. No se alteró el contrato durante la captura para ocultar esa falla. El manual identifica el bloqueo y muestra la alternativa de carga manual con la foto.

## Regenerar y revisar la entrega

1. Ejecutar los recorridos afectados y comprobar sus resultados en la otra interfaz o en la API real.
2. Revisar las imágenes originales en `.context/manual/screenshots/`; descartar estados de carga, errores inesperados, teclados que tapen el contenido y datos reales.
3. Copiar las capturas aprobadas a `docs/manual-usuario/assets/`, sin alterar el contenido de la interfaz.
4. Actualizar los textos y el registro de cobertura, con sus verificaciones pendientes.
5. Instalar `Markdown` en el entorno Python de documentación y ejecutar:

```bash
python scripts/manual/inventory.py
python scripts/manual/verify.py
python scripts/manual/verify-live.py
python scripts/manual/render.py --output .context/manual/manual.html
python scripts/manual/render.py --output docs/manual-usuario/index.html --linked-assets
```

El HTML reúne los capítulos y las imágenes en un archivo portátil, con navegación, búsqueda por Enter, ampliación de capturas y estilos de impresión. Revisar la versión de escritorio, una ventana angosta, los enlaces internos, la ampliación de imágenes y la impresión antes de compartir una edición final.

La versión `docs/manual-usuario/index.html` referencia las imágenes de `assets/` y se versiona junto con ellas. Para leerla fuera del repositorio, conservar esa estructura de directorios o generar la versión portátil con imágenes incrustadas.

La versión Markdown permite editar por módulo. La revisión visual debe comprobar también que el pie de cada figura y los pasos describan la pantalla que efectivamente se capturó.
