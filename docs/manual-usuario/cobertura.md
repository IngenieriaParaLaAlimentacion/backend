# Cobertura y evidencias de esta edición

El inventario registra las páginas web y los archivos de pantallas nativas encontrados en las revisiones fijadas. Una pantalla inventariada o capturada no implica que todas sus alternativas hayan sido ejecutadas.

## Revisiones

| Repositorio | Revisión |
|---|---|
| backend | `99a1acbfee78b021558155bbae13c2aa882b6bf2` |
| backoffice | `6d79a177742391443dc9560444be2d10f620b439` |
| app_mobile | `b856633c35da5d452ef7a2dffb015bd6c55bf795` |

## Comprobaciones de recorridos

| Recorrido | Evidencia y alcance |
|---|---|
| Acceso web y consulta de secciones | Playwright inicia sesión por la interfaz real; cada captura espera un texto propio de su pantalla. |
| Medición sin conexión → sincronización | App Android: selección del sujeto, carga, confirmación, aviso de pendiente offline y estado sincronizado en Historial. |
| Consulta y evolución de mediciones | Backoffice real con datos persistidos y apertura del gráfico por Playwright. |
| Exportación de mediciones | Descarga CSV real mediante Playwright; archivo conservado en `.context/manual/downloads/`. |
| Recibos y recetas | Respuesta del modelo y almacenamiento de objetos sustituidos explícitamente por servicios locales de demostración. No valida Gemini ni R2. |
| Recibo: propuesta automática | Incompatibilidad comprobada: el backend no envía needs_review y el DTO Android lo exige. La alternativa manual con foto sí se guardó. |
| Invitaciones, recuperación y verificación de email | Procedimientos revisados en código; entrega de correo y recorrido completo del enlace pendientes de comprobación con un buzón de prueba. |
| Casos de permisos, validación y errores | Documentados a partir de UI, contratos y código. La lista de capturas no acredita ejecución exhaustiva de todas las combinaciones. |
| iOS | Sin capturas ni ejecución de esta edición. |

## Inventario de pantallas (64)

Cada fuente está enlazada a la revisión exacta y asociada a un capítulo. Los componentes y diálogos se revisan junto con su pantalla; el inventario no cuenta cada componente como una función independiente.

| Interfaz | Pantalla o ruta | Capítulo |
|---|---|---|
| backoffice | [app/(auth)/forgot-password/page.tsx](https://github.com/IngenieriaParaLaAlimentacion/backoffice/blob/6d79a177742391443dc9560444be2d10f620b439/app/(auth)/forgot-password/page.tsx) | [01-acceso.md](01-acceso.md) |
| backoffice | [app/(auth)/invite/admin/page.tsx](https://github.com/IngenieriaParaLaAlimentacion/backoffice/blob/6d79a177742391443dc9560444be2d10f620b439/app/(auth)/invite/admin/page.tsx) | [01-acceso.md](01-acceso.md) |
| backoffice | [app/(auth)/invite/analyst/page.tsx](https://github.com/IngenieriaParaLaAlimentacion/backoffice/blob/6d79a177742391443dc9560444be2d10f620b439/app/(auth)/invite/analyst/page.tsx) | [01-acceso.md](01-acceso.md) |
| backoffice | [app/(auth)/invite/page.tsx](https://github.com/IngenieriaParaLaAlimentacion/backoffice/blob/6d79a177742391443dc9560444be2d10f620b439/app/(auth)/invite/page.tsx) | [01-acceso.md](01-acceso.md) |
| backoffice | [app/(auth)/reset-password/page.tsx](https://github.com/IngenieriaParaLaAlimentacion/backoffice/blob/6d79a177742391443dc9560444be2d10f620b439/app/(auth)/reset-password/page.tsx) | [01-acceso.md](01-acceso.md) |
| backoffice | [app/(auth)/signin/page.tsx](https://github.com/IngenieriaParaLaAlimentacion/backoffice/blob/6d79a177742391443dc9560444be2d10f620b439/app/(auth)/signin/page.tsx) | [01-acceso.md](01-acceso.md) |
| backoffice | [app/(auth)/verify-email/page.tsx](https://github.com/IngenieriaParaLaAlimentacion/backoffice/blob/6d79a177742391443dc9560444be2d10f620b439/app/(auth)/verify-email/page.tsx) | [01-acceso.md](01-acceso.md) |
| backoffice | [dashboard/anthropometric-measurements/page.tsx](https://github.com/IngenieriaParaLaAlimentacion/backoffice/blob/6d79a177742391443dc9560444be2d10f620b439/app/dashboard/anthropometric-measurements/page.tsx) | [02-talla-y-peso.md](02-talla-y-peso.md) |
| backoffice | [dashboard/establishments/(list)/page.tsx](https://github.com/IngenieriaParaLaAlimentacion/backoffice/blob/6d79a177742391443dc9560444be2d10f620b439/app/dashboard/establishments/(list)/page.tsx) | [01-acceso.md](01-acceso.md) |
| backoffice | [dashboard/establishments/[id]/(ficha)/field-workers/page.tsx](https://github.com/IngenieriaParaLaAlimentacion/backoffice/blob/6d79a177742391443dc9560444be2d10f620b439/app/dashboard/establishments/[id]/(ficha)/field-workers/page.tsx) | [01-acceso.md](01-acceso.md) |
| backoffice | [dashboard/establishments/[id]/(ficha)/page.tsx](https://github.com/IngenieriaParaLaAlimentacion/backoffice/blob/6d79a177742391443dc9560444be2d10f620b439/app/dashboard/establishments/[id]/(ficha)/page.tsx) | [01-acceso.md](01-acceso.md) |
| backoffice | [dashboard/establishments/[id]/(ficha)/profile/page.tsx](https://github.com/IngenieriaParaLaAlimentacion/backoffice/blob/6d79a177742391443dc9560444be2d10f620b439/app/dashboard/establishments/[id]/(ficha)/profile/page.tsx) | [01-acceso.md](01-acceso.md) |
| backoffice | [dashboard/establishments/[id]/(ficha)/stock/page.tsx](https://github.com/IngenieriaParaLaAlimentacion/backoffice/blob/6d79a177742391443dc9560444be2d10f620b439/app/dashboard/establishments/[id]/(ficha)/stock/page.tsx) | [04-nutrir.md](04-nutrir.md) |
| backoffice | [dashboard/establishments/[id]/stock/movements/page.tsx](https://github.com/IngenieriaParaLaAlimentacion/backoffice/blob/6d79a177742391443dc9560444be2d10f620b439/app/dashboard/establishments/[id]/stock/movements/page.tsx) | [04-nutrir.md](04-nutrir.md) |
| backoffice | [dashboard/establishments/create/page.tsx](https://github.com/IngenieriaParaLaAlimentacion/backoffice/blob/6d79a177742391443dc9560444be2d10f620b439/app/dashboard/establishments/create/page.tsx) | [01-acceso.md](01-acceso.md) |
| backoffice | [dashboard/establishments/propose/page.tsx](https://github.com/IngenieriaParaLaAlimentacion/backoffice/blob/6d79a177742391443dc9560444be2d10f620b439/app/dashboard/establishments/propose/page.tsx) | [01-acceso.md](01-acceso.md) |
| backoffice | [dashboard/page.tsx](https://github.com/IngenieriaParaLaAlimentacion/backoffice/blob/6d79a177742391443dc9560444be2d10f620b439/app/dashboard/page.tsx) | [01-acceso.md](01-acceso.md) |
| backoffice | [dashboard/profile/edit/page.tsx](https://github.com/IngenieriaParaLaAlimentacion/backoffice/blob/6d79a177742391443dc9560444be2d10f620b439/app/dashboard/profile/edit/page.tsx) | [01-acceso.md](01-acceso.md) |
| backoffice | [dashboard/profile/page.tsx](https://github.com/IngenieriaParaLaAlimentacion/backoffice/blob/6d79a177742391443dc9560444be2d10f620b439/app/dashboard/profile/page.tsx) | [01-acceso.md](01-acceso.md) |
| backoffice | [dashboard/requests/establishment-creations/page.tsx](https://github.com/IngenieriaParaLaAlimentacion/backoffice/blob/6d79a177742391443dc9560444be2d10f620b439/app/dashboard/requests/establishment-creations/page.tsx) | [01-acceso.md](01-acceso.md) |
| backoffice | [dashboard/requests/establishments/page.tsx](https://github.com/IngenieriaParaLaAlimentacion/backoffice/blob/6d79a177742391443dc9560444be2d10f620b439/app/dashboard/requests/establishments/page.tsx) | [01-acceso.md](01-acceso.md) |
| backoffice | [dashboard/requests/page.tsx](https://github.com/IngenieriaParaLaAlimentacion/backoffice/blob/6d79a177742391443dc9560444be2d10f620b439/app/dashboard/requests/page.tsx) | [01-acceso.md](01-acceso.md) |
| backoffice | [dashboard/subjects/page.tsx](https://github.com/IngenieriaParaLaAlimentacion/backoffice/blob/6d79a177742391443dc9560444be2d10f620b439/app/dashboard/subjects/page.tsx) | [02-talla-y-peso.md](02-talla-y-peso.md) |
| backoffice | [dashboard/surveys/[id]/page.tsx](https://github.com/IngenieriaParaLaAlimentacion/backoffice/blob/6d79a177742391443dc9560444be2d10f620b439/app/dashboard/surveys/[id]/page.tsx) | [03-encuestas.md](03-encuestas.md) |
| backoffice | [dashboard/surveys/[id]/responses/page.tsx](https://github.com/IngenieriaParaLaAlimentacion/backoffice/blob/6d79a177742391443dc9560444be2d10f620b439/app/dashboard/surveys/[id]/responses/page.tsx) | [03-encuestas.md](03-encuestas.md) |
| backoffice | [dashboard/surveys/new/page.tsx](https://github.com/IngenieriaParaLaAlimentacion/backoffice/blob/6d79a177742391443dc9560444be2d10f620b439/app/dashboard/surveys/new/page.tsx) | [03-encuestas.md](03-encuestas.md) |
| backoffice | [dashboard/surveys/page.tsx](https://github.com/IngenieriaParaLaAlimentacion/backoffice/blob/6d79a177742391443dc9560444be2d10f620b439/app/dashboard/surveys/page.tsx) | [03-encuestas.md](03-encuestas.md) |
| backoffice | [dashboard/users/[role]/page.tsx](https://github.com/IngenieriaParaLaAlimentacion/backoffice/blob/6d79a177742391443dc9560444be2d10f620b439/app/dashboard/users/[role]/page.tsx) | [01-acceso.md](01-acceso.md) |
| backoffice | [dashboard/users/page.tsx](https://github.com/IngenieriaParaLaAlimentacion/backoffice/blob/6d79a177742391443dc9560444be2d10f620b439/app/dashboard/users/page.tsx) | [01-acceso.md](01-acceso.md) |
| backoffice | [app/page.tsx](https://github.com/IngenieriaParaLaAlimentacion/backoffice/blob/6d79a177742391443dc9560444be2d10f620b439/app/page.tsx) | [01-acceso.md](01-acceso.md) |
| app_mobile | [auth/forgot_password/ForgotPasswordScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/auth/forgot_password/ForgotPasswordScreen.kt) | [01-acceso.md](01-acceso.md) |
| app_mobile | [auth/login/LoginScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/auth/login/LoginScreen.kt) | [01-acceso.md](01-acceso.md) |
| app_mobile | [auth/reset_password/ResetPasswordScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/auth/reset_password/ResetPasswordScreen.kt) | [01-acceso.md](01-acceso.md) |
| app_mobile | [auth/reset_password/ResetPasswordSuccessScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/auth/reset_password/ResetPasswordSuccessScreen.kt) | [01-acceso.md](01-acceso.md) |
| app_mobile | [auth/verify_email/VerifyEmailScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/auth/verify_email/VerifyEmailScreen.kt) | [01-acceso.md](01-acceso.md) |
| app_mobile | [establishment/characterization/edit_characterization/EditCharacterizationScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/establishment/characterization/edit_characterization/EditCharacterizationScreen.kt) | [01-acceso.md](01-acceso.md) |
| app_mobile | [establishment/select_establishment/SelectEstablishmentScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/establishment/select_establishment/SelectEstablishmentScreen.kt) | [01-acceso.md](01-acceso.md) |
| app_mobile | [food/create_food_intake/CreateFoodIntakeScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/food/create_food_intake/CreateFoodIntakeScreen.kt) | [04-nutrir.md](04-nutrir.md) |
| app_mobile | [food/create_food_outflow/CreateFoodOutflowScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/food/create_food_outflow/CreateFoodOutflowScreen.kt) | [04-nutrir.md](04-nutrir.md) |
| app_mobile | [food/establishment_food_movement_detail/EstablishmentFoodMovementDetailScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/food/establishment_food_movement_detail/EstablishmentFoodMovementDetailScreen.kt) | [04-nutrir.md](04-nutrir.md) |
| app_mobile | [food/establishment_food_movement_history/EstablishmentFoodMovementHistoryScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/food/establishment_food_movement_history/EstablishmentFoodMovementHistoryScreen.kt) | [04-nutrir.md](04-nutrir.md) |
| app_mobile | [food/food_overview/FoodOverviewScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/food/food_overview/FoodOverviewScreen.kt) | [04-nutrir.md](04-nutrir.md) |
| app_mobile | [food/food_stock/FoodStockScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/food/food_stock/FoodStockScreen.kt) | [04-nutrir.md](04-nutrir.md) |
| app_mobile | [food/receipt_food_intake/ReceiptFoodIntakeScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/food/receipt_food_intake/ReceiptFoodIntakeScreen.kt) | [04-nutrir.md](04-nutrir.md) |
| app_mobile | [food/recipes/RecipesScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/food/recipes/RecipesScreen.kt) | [04-nutrir.md](04-nutrir.md) |
| app_mobile | [get_started/GetStartedScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/get_started/GetStartedScreen.kt) | [01-acceso.md](01-acceso.md) |
| app_mobile | [history/HistoryHubScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/history/HistoryHubScreen.kt) | [01-acceso.md](01-acceso.md) |
| app_mobile | [home/HomeScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/home/HomeScreen.kt) | [01-acceso.md](01-acceso.md) |
| app_mobile | [measurement/create_measurement/MeasurementScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/measurement/create_measurement/MeasurementScreen.kt) | [02-talla-y-peso.md](02-talla-y-peso.md) |
| app_mobile | [profile/edit/EditProfileScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/profile/edit/EditProfileScreen.kt) | [01-acceso.md](01-acceso.md) |
| app_mobile | [profile/establishments/MyEstablishmentsScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/profile/establishments/MyEstablishmentsScreen.kt) | [01-acceso.md](01-acceso.md) |
| app_mobile | [profile/notify_establishment/NotifyEstablishmentScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/profile/notify_establishment/NotifyEstablishmentScreen.kt) | [01-acceso.md](01-acceso.md) |
| app_mobile | [profile/request_establishment/RequestEstablishmentScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/profile/request_establishment/RequestEstablishmentScreen.kt) | [01-acceso.md](01-acceso.md) |
| app_mobile | [profile/view/ProfileScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/profile/view/ProfileScreen.kt) | [01-acceso.md](01-acceso.md) |
| app_mobile | [register/RegisterScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/register/RegisterScreen.kt) | [01-acceso.md](01-acceso.md) |
| app_mobile | [register/RegisterSuccessScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/register/RegisterSuccessScreen.kt) | [01-acceso.md](01-acceso.md) |
| app_mobile | [subject/create_subject/CreateSubjectScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/subject/create_subject/CreateSubjectScreen.kt) | [02-talla-y-peso.md](02-talla-y-peso.md) |
| app_mobile | [subject/select_subject/SelectSubjectScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/subject/select_subject/SelectSubjectScreen.kt) | [02-talla-y-peso.md](02-talla-y-peso.md) |
| app_mobile | [subject/uploads/SubjectUploadsScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/subject/uploads/SubjectUploadsScreen.kt) | [02-talla-y-peso.md](02-talla-y-peso.md) |
| app_mobile | [survey/survey_list/SurveyListScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/survey/survey_list/SurveyListScreen.kt) | [03-encuestas.md](03-encuestas.md) |
| app_mobile | [survey/survey_response_detail/SurveyResponseDetailScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/survey/survey_response_detail/SurveyResponseDetailScreen.kt) | [03-encuestas.md](03-encuestas.md) |
| app_mobile | [survey/survey_response_edit/SurveyResponseEditScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/survey/survey_response_edit/SurveyResponseEditScreen.kt) | [03-encuestas.md](03-encuestas.md) |
| app_mobile | [survey/survey_response_form/SurveyResponseFormScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/survey/survey_response_form/SurveyResponseFormScreen.kt) | [03-encuestas.md](03-encuestas.md) |
| app_mobile | [survey/survey_response_number_fix/SurveyResponseNumberFixScreen.kt](https://github.com/IngenieriaParaLaAlimentacion/app_mobile/blob/b856633c35da5d452ef7a2dffb015bd6c55bf795/composeApp/src/commonMain/kotlin/ar/com/ingenieriaalimentacion/presentation/feature/survey/survey_response_number_fix/SurveyResponseNumberFixScreen.kt) | [03-encuestas.md](03-encuestas.md) |

## Verificaciones sobre datos persistidos

Ejecutadas: 2026-10-25T18:50:48.263475+00:00. Entorno local aislado; modelo de demostración.

| Recorrido | Resultado | Evidencia |
|---|---|---|
| Medición Android → backend | passed | 5 registros fuera del seed, visibles en el listado real |
| Encuesta Android → backend | passed | Respuesta 101 del relevamiento por sujeto persistida |
| Movimientos Android → backend | passed | 8 movimientos en el establecimiento |
| Elegir receta → salida | passed | Receta elegida persistida; el flujo usa la transacción real del backend |
| Permisos de administración | passed | Analista y relevador reciben 403 al listar usuarios administrativos |
| Exportación web | passed | CSV real descargado por Playwright, 14 filas de datos |
| Exportación de respuestas | passed | Archivo Excel descargado por Playwright con estructura XLSX válida |
| Análisis de recibo en Android | known_incompatibility | Respuesta 200 sin needs_review; el DTO Android lo exige. Captura y log de JsonConvertException conservados. |

## Capturas con comprobación de pantalla (91)

| Captura | Interfaz | Texto comprobado antes de capturar |
|---|---|---|
| [app-acceso](assets/app-acceso.png) | android | Iniciar sesión |
| [app-acceso-solicitar](assets/app-acceso-solicitar.png) | android | Buscar establecimiento |
| [app-alimentos](assets/app-alimentos.png) | android | Stock actual |
| [app-bienvenida](assets/app-bienvenida.png) | android | Gestioná tu establecimiento |
| [app-cerrar-sesion](assets/app-cerrar-sesion.png) | android | ¿Seguro que querés cerrar sesión? |
| [app-comedor-ficha](assets/app-comedor-ficha.png) | android | Ubicación |
| [app-comedor-notificar](assets/app-comedor-notificar.png) | android | Notificar comedor |
| [app-comedor-notificar-ficha](assets/app-comedor-notificar-ficha.png) | android | Ficha del comedor |
| [app-comedor-seleccionar](assets/app-comedor-seleccionar.png) | android | Elegí el establecimiento |
| [app-egreso](assets/app-egreso.png) | android | Registrar egreso |
| [app-egreso-completo](assets/app-egreso-completo.png) | android | Disponible: |
| [app-egreso-registrado](assets/app-egreso-registrado.png) | android | Stock actual |
| [app-encuesta-anonima](assets/app-encuesta-anonima.png) | android | Anónima |
| [app-encuesta-completa](assets/app-encuesta-completa.png) | android | Relevamiento de demostracion |
| [app-encuesta-detalle](assets/app-encuesta-detalle.png) | android | Relevamiento de demostracion |
| [app-encuesta-detalle-anonima](assets/app-encuesta-detalle-anonima.png) | android | Relevamiento de demostracion |
| [app-encuesta-editar](assets/app-encuesta-editar.png) | android | Guardar cambios |
| [app-encuesta-formulario](assets/app-encuesta-formulario.png) | android | Seguimiento alimentario |
| [app-encuestas](assets/app-encuestas.png) | android | Encuestas |
| [app-encuestas-historial](assets/app-encuestas-historial.png) | android | Opinión de la comunidad |
| [app-encuestas-sin-conexion](assets/app-encuestas-sin-conexion.png) | android | Mostrando encuestas guardadas |
| [app-historial](assets/app-historial.png) | android | Historial |
| [app-ingreso](assets/app-ingreso.png) | android | Registrar ingreso |
| [app-ingreso-completo](assets/app-ingreso-completo.png) | android | Arroz blanco, crudo |
| [app-ingreso-registrado](assets/app-ingreso-registrado.png) | android | Stock actual |
| [app-inicio](assets/app-inicio.png) | android | Hola, Ana |
| [app-inicio-comedor](assets/app-inicio-comedor.png) | android | Comedor Semillas del Sur |
| [app-medicion-completa](assets/app-medicion-completa.png) | android | Control de seguimiento |
| [app-medicion-confirmacion](assets/app-medicion-confirmacion.png) | android | Revisá las medidas |
| [app-medicion-formulario](assets/app-medicion-formulario.png) | android | Cargar medición |
| [app-medicion-guardada](assets/app-medicion-guardada.png) | android | Cargar medición |
| [app-mediciones-historial](assets/app-mediciones-historial.png) | android | Sincronizado |
| [app-mis-establecimientos](assets/app-mis-establecimientos.png) | android | Mis establecimientos |
| [app-movimiento-detalle](assets/app-movimiento-detalle.png) | android | Detalle del movimiento |
| [app-movimientos](assets/app-movimientos.png) | android | Movimientos |
| [app-pendiente-offline](assets/app-pendiente-offline.png) | android | se subirán al reconectar |
| [app-perfil](assets/app-perfil.png) | android | Mis establecimientos |
| [app-perfil-editar](assets/app-perfil-editar.png) | android | Guardar |
| [app-recetas-cantidades](assets/app-recetas-cantidades.png) | android | Cocinar esta receta |
| [app-recetas-confirmacion](assets/app-recetas-confirmacion.png) | android | Confirmar y registrar salida |
| [app-recetas-generar](assets/app-recetas-generar.png) | android | Buscar propuestas |
| [app-recetas-historial](assets/app-recetas-historial.png) | android | Ver receta |
| [app-recetas-ingredientes](assets/app-recetas-ingredientes.png) | android | Elegir esta receta |
| [app-recetas-propuesta](assets/app-recetas-propuesta.png) | android | Arroz para el comedor |
| [app-recetas-reutilizar](assets/app-recetas-reutilizar.png) | android | Cantidad de chicos de hoy |
| [app-recetas-reutilizar-confirmacion](assets/app-recetas-reutilizar-confirmacion.png) | android | Confirmar y registrar salida |
| [app-recibo-error](assets/app-recibo-error.png) | android | No se pudo completar. |
| [app-recibo-foto](assets/app-recibo-foto.png) | android | Procesar recibo |
| [app-recibo-listo](assets/app-recibo-listo.png) | android | Guardar ingreso |
| [app-recibo-manual](assets/app-recibo-manual.png) | android | Agregar alimento |
| [app-recibo-registrado](assets/app-recibo-registrado.png) | android | 28 kg |
| [app-registro](assets/app-registro.png) | android | Crear cuenta |
| [app-sin-conexion](assets/app-sin-conexion.png) | android | Sin conexión |
| [app-sincronizado](assets/app-sincronizado.png) | android | Todo sincronizado |
| [app-stock](assets/app-stock.png) | android | Stock |
| [app-sujeto-alta](assets/app-sujeto-alta.png) | android | Cargar sujeto |
| [app-sujeto-buscar](assets/app-sujeto-buscar.png) | android | Buscar por nombre o DNI |
| [web-acceso](assets/web-acceso.png) | backoffice | Iniciar sesión |
| [web-comedor](assets/web-comedor.png) | backoffice | Sujetos que asisten |
| [web-comedor-perfil](assets/web-comedor-perfil.png) | backoffice | Perfil |
| [web-comedor-perfil-editar](assets/web-comedor-perfil-editar.png) | backoffice | Guardar perfil |
| [web-comedor-relevadores](assets/web-comedor-relevadores.png) | backoffice | Relevadores |
| [web-comedor-solicitud-revisar](assets/web-comedor-solicitud-revisar.png) | backoffice | Aprobar |
| [web-encuesta-acciones](assets/web-encuesta-acciones.png) | backoffice | Duplicar |
| [web-encuesta-editar](assets/web-encuesta-editar.png) | backoffice | Editar encuesta |
| [web-encuesta-exportar](assets/web-encuesta-exportar.png) | backoffice | Exportar |
| [web-encuesta-nueva](assets/web-encuesta-nueva.png) | backoffice | Nueva encuesta |
| [web-encuesta-respuesta-detalle](assets/web-encuesta-respuesta-detalle.png) | backoffice | Detalle de respuesta |
| [web-encuesta-respuestas](assets/web-encuesta-respuestas.png) | backoffice | Respuestas |
| [web-encuestas](assets/web-encuestas.png) | backoffice | Relevamientos FIES |
| [web-establecimiento-alta](assets/web-establecimiento-alta.png) | backoffice | Nombre |
| [web-establecimientos](assets/web-establecimientos.png) | backoffice | Establecimientos registrados |
| [web-evolucion](assets/web-evolucion.png) | backoffice | Evolución de peso y talla |
| [web-fies-crear](assets/web-fies-crear.png) | backoffice | 8/30 |
| [web-fies-respuestas](assets/web-fies-respuestas.png) | backoffice | Respuestas |
| [web-inicio](assets/web-inicio.png) | backoffice | Accesos disponibles |
| [web-mediciones](assets/web-mediciones.png) | backoffice | Mediciones antropométricas |
| [web-movimiento-registrar](assets/web-movimiento-registrar.png) | backoffice | Guardar |
| [web-movimientos](assets/web-movimientos.png) | backoffice | Movimientos |
| [web-perfil](assets/web-perfil.png) | backoffice | Mi información personal |
| [web-perfil-editar](assets/web-perfil-editar.png) | backoffice | Editar perfil |
| [web-recuperar](assets/web-recuperar.png) | backoffice | Email |
| [web-solicitud-revisar](assets/web-solicitud-revisar.png) | backoffice | Aceptar solicitud |
| [web-solicitudes-acceso](assets/web-solicitudes-acceso.png) | backoffice | Solicitudes de establecimiento |
| [web-solicitudes-alta](assets/web-solicitudes-alta.png) | backoffice | Solicitudes |
| [web-solicitudes-registro](assets/web-solicitudes-registro.png) | backoffice | Solicitudes de usuario |
| [web-stock](assets/web-stock.png) | backoffice | Stock |
| [web-sujeto-detalle](assets/web-sujeto-detalle.png) | backoffice | Documento de identidad |
| [web-sujetos](assets/web-sujetos.png) | backoffice | Sujetos registrados |
| [web-usuario-invitar](assets/web-usuario-invitar.png) | backoffice | Enviar invitación |
| [web-usuarios](assets/web-usuarios.png) | backoffice | Usuarios |

Los datos de demostración, las capturas originales y las descargas se generan localmente. El inventario público no conserva URLs con parámetros de autenticación ni tokens.
