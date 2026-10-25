# Mantener y verificar el manual

## Fuente única y alcance

El contenido editorial vive en `docs/manual-usuario/` del backend. App y backoffice se documentan juntos. Las issues de referencia son [backoffice#110](https://github.com/IngenieriaParaLaAlimentacion/backoffice/issues/110) y [app_mobile#95](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/issues/95).

Antes de otra edición, fijar las revisiones de los tres repositorios, revisar las rutas y los permisos, y actualizar el inventario de cobertura. No publicar una captura del formulario como prueba de que el guardado o una integración externa funcionaron.

## Evidencias conservadas de la edición del 25/10/2026

| Componente | Configuración |
|---|---|
| Backend | `99a1acb`, HTTP en `127.0.0.1:8080`. |
| Backoffice | `6d79a17`, Next.js en `localhost:3001`, API local. |
| App | `b856633`, variante `tstDebug`, API `http://10.0.2.2:8080/`. |
| Datos | PostgreSQL local dedicado, puerto `55432`, usuario/base `manual`; Redis local en `56379`. |
| Navegador | Chrome mediante Playwright, 1440 × 1000, locale `es-AR`, huso de Buenos Aires. |
| Android | AVD dedicado `IPA_Manual`, Pixel 9 Pro, API 36, `google_apis_playstore`, `arm64-v8a`. |

Las 91 capturas publicadas y sus verificaciones corresponden al escenario Semillas del Sur de esta edición, anterior a la adaptación al dataset compartido. Se conservan sin renombrar personas ni alterar imágenes. Las próximas capturas usan el dataset de #219; al publicarlas, actualizar también los ejemplos y el inventario de revisiones. La adaptación de los scripts no convierte estas imágenes históricas en evidencia de una ejecución del dataset nuevo.

Las copias de trabajo, logs, descargas y capturas originales están bajo `.context/manual/`. Las imágenes aprobadas para el manual se copian a `assets/`. No se modifican los checkouts de trabajo de otras personas ni se conectan las pruebas a producción.

## Preparar datos y ejecutar las capturas

La reproducción usa el dataset compartido de [backend#219](https://github.com/IngenieriaParaLaAlimentacion/backend/pull/219) y el entorno E2E de [backend#217](https://github.com/IngenieriaParaLaAlimentacion/backend/pull/217). Ambos deben estar integrados en el checkout y en la imagen seleccionada antes de usar Compose. El PR del manual depende de esos cambios: no contiene copias de sus seeds ni de su infraestructura.

`scripts/manual/seed.py` llama a `seed_superadmin.create_super_admin()` y `seed_reference_e2e.seed_reference_e2e()`. Reutiliza las cuentas, seis comedores, quince personas, mediciones, stock, FIES y solicitudes pendientes. Sólo agrega tres encuestas para mostrar los destinos sujeto, establecimiento y anónimo. No inserta usuarios ni contraseñas mediante ORM propio.

El fixture selecciona **Comedor Plaza de Mayo**, **Camila Fernández** y **Mateo Rodríguez** del dataset común. Para mostrar el aviso de revisión de medidas, el recorrido Android carga un peso ficticio de 23 kg para Mateo, conservando la talla de referencia; no es un dato clínico ni modifica el seed compartido. Exporta las credenciales de prueba, identificadores y nombres que consumen Playwright, Android y la verificación posterior; no exporta tokens de sesión. El superadministrador usa `SEED_ADMIN_EMAIL` y `SEED_ADMIN_PASSWORD` del entorno; el resto usa las credenciales definidas por #219. No versionar `fixture.json`.

### Con el entorno compartido de #217

Desde la raíz de un checkout que contenga ambos PRs y los scripts del manual:

```bash
mkdir -p .context/manual
export MANUAL_UID="$(id -u)" MANUAL_GID="$(id -g)"
# Imagen publicada que contenga #217 y #219; fijar un sha concreto.
export BACKEND_IMAGE=ghcr.io/ingenieriaparalaalimentacion/backend:sha-COMMIT
# Autenticarse en GHCR como indica docs/commands.md.
docker compose -f e2e/compose.yml -f scripts/manual/compose.yml up -d --wait backend
docker compose -f e2e/compose.yml -f scripts/manual/compose.yml run --rm manual-fixture
```

La extensión mantiene el PostgreSQL, las migraciones, las credenciales y los límites de #217. Añade el adaptador de datos y monta el servidor de demostración para las recetas y recibos. El contenedor escribe el fixture y las fotos en `.context/manual/`; los dos servicios usan el UID/GID del usuario local para escribir en ese montaje. El fixture guarda la URL de la API accesible desde el host (`127.0.0.1:8080`), aunque internamente se prepare mediante `http://backend:8080`.

### Sin Docker, con los mismos seeds

Requisitos: dependencias del backend y PostgreSQL con `pg_trgm`; Node, JDK 21 y Android SDK para las interfaces. En una base descartable dedicada, ejecutar las migraciones y el catálogo. Configurar `ENVIRONMENT=e2e`, `SMTP_ENABLED=false`, `OTEL_SDK_DISABLED=true` y `RATE_LIMIT_REDIS_URL=memory://`, junto con credenciales ficticias y los límites de `e2e/.env.e2e`. El seed compartido y el adaptador rechazan otros entornos.

Mantener levantado el backend (servidor de demostración indicado más abajo). Desde su checkout con su entorno virtual activo:

```bash
PYTHONPATH=. python /ruta/al/workspace/scripts/manual/seed.py \
  --output /ruta/al/workspace/.context/manual/fixture.json
```

Ejecutar la preparación antes de los recorridos. El fixture conserva los IDs iniciales de mediciones y movimientos para distinguirlos de los registros creados después por la app. Repetir el seed es idempotente; regenerar el fixture después de capturar redefine esa referencia inicial.

Para el backoffice, instalar su lockfile y levantarlo:

```bash
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8080 npm run dev -- --port 3001
```

Abrir el AVD dedicado `IPA_Manual`, instalar la variante `tst` y usar una sesión limpia al cambiar de dataset. Nunca ejecutar los recorridos de carga contra una base compartida. El HTML final no necesita que estos servicios sigan levantados.

Desde el workspace del manual:

```bash
npm ci --prefix scripts/manual
python3 scripts/manual/capture-android.py login
python3 scripts/manual/capture-android.py talla
python3 scripts/manual/capture-android.py encuestas
python3 scripts/manual/capture-android.py nutrir
python scripts/manual/make-receipt.py
python3 scripts/manual/capture-android.py recibos
python3 scripts/manual/capture-android.py recetas
python3 scripts/manual/capture-android.py perfil
python3 scripts/manual/capture-android.py apoyos
node scripts/manual/capture-web.mjs
```

Si hay otros emuladores abiertos, configurar `export MANUAL_ADB_SERIAL=emulator-5556` con el serial del AVD dedicado que muestre `adb devices`; no usar el emulador de trabajo de otra persona.

El driver Android comprueba que el dispositivo sea el AVD `IPA_Manual`. Requiere la app `tst` instalada, autenticada con la cuenta ficticia y con el comedor indicado en `fixture.json` seleccionado. Cada escenario reinicia la actividad conservando sus datos. El escenario de medición genera un registro nuevo: no se debe correr contra una base compartida.

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

El servidor exige `ENVIRONMENT=test` o `e2e`, igual que el seed compartido. Mantiene los endpoints, la autenticación, el catálogo, los cálculos, las validaciones y las transacciones del backend. Sustituye solo la respuesta del modelo y el almacenamiento de objetos. **Estas capturas no validan Gemini, la extracción óptica real ni R2.** La propuesta de arroz es un ejemplo de interfaz con stock limitado; no representa una recomendación editorial del manual.

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
