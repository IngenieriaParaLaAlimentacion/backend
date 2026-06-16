Talla, Peso y Georreferenciación

Descripción
Como Responsable de Comedor, quiero registrar mediciones antropométricas junto con la ubicación del relevamiento para monitorear el estado nutricional territorial de los sujetos.

Criterios de aceptación
CA 1 — Asociación obligatoria a sujeto


El sistema debe permitir seleccionar un sujeto previamente registrado antes de cargar una medición.
CA 2 — Registro antropométrico


El formulario debe permitir ingresar peso (kg), talla (cm), fecha del relevamiento.
CA 3 — Asociación a comedor


La medición debe quedar asociada al comedor desde el cual se realiza la carga.
CA 4 — Calculador de IMC


Una vez cargados los datos de talla y peso, se registrará un campo indicando el IMC del sujeto.
CA 5 — Trazabilidad de la carga


El sistema debe registrar automáticamente el usuario responsable de la carga.
CA 6 — Validación preventiva


El sistema debe advertir al usuario cuando los valores ingresados se encuentren fuera de rangos antropométricos razonables, incluso en modo offline.
CA 7 — Generación automática de alerta clínica


Al sincronizar o registrar la medición, el backend debe evaluar los datos antropométricos y generar una alerta cuando los valores indiquen posible riesgo nutricional.
CA 8 — Persistencia de alertas


Las alertas deben almacenarse en la base de datos y permanecer disponibles para visualización en el panel técnico.


Aclaraciones:
1. Si el niño no existe, debera crearse primero
2. La carga debe asociar el sujeto, su registro, la fecha, comedor y responsable
3. Consultar cualquier duda