"""Replay manual capture scenarios on the isolated, authenticated IPA_Manual AVD."""

import argparse
import time

from android import back, fill, find, offline, scroll_to, shot, start, tap, wait_for


def talla():
    start()
    shot("app-inicio-comedor", "Comedor Semillas del Sur")
    tap("Sujeto")
    shot("app-sujeto-alta", "Cargar sujeto")
    tap("Atrás")
    tap("Medición")
    shot("app-medicion-formulario", "Cargar medición")
    tap("Seleccionar sujeto")
    time.sleep(1)
    shot("app-sujeto-buscar", "Buscar por nombre o DNI")
    tap("Mateo Demostración")
    fill(1, "23")
    fill(2, "135")
    # Leave the input using a non-editable form label, retaining keyboard state
    # only until the explicit Android back event.
    from android import back

    back()
    shot("app-medicion-completa", "Peso (kg)")
    try:
        offline(True)
        tap("Guardar")
        shot("app-medicion-confirmacion", "Revisá las medidas")
        tap("Confirmar y guardar")
        tap("Atrás")
        shot("app-pendiente-offline", "se subirán al reconectar")
    finally:
        offline(False)
    time.sleep(4)
    shot("app-sincronizado", "Todo sincronizado")
    tap("Historial")
    shot("app-historial", "Historial")


def encuestas():
    start()
    tap("Encuesta")
    shot("app-encuestas", "Encuestas")
    tap("Opinión de la comunidad")
    fill(0, "101")
    tap("Sí")
    fill(1, "Relevamiento de demostracion")
    back()
    shot("app-encuesta-anonima", "Anónima")
    tap("Guardar")
    time.sleep(1)
    tap("Atrás")
    tap("Atrás")
    tap("Historial")
    tap("Encuestas")
    shot("app-encuestas-historial", "Opinión de la comunidad")
    tap("Opinión de la comunidad")
    shot("app-encuesta-detalle-anonima", "Relevamiento de demostracion")
    tap("Editar")
    shot("app-encuesta-editar", "Guardar cambios")


def nutrir():
    start()
    tap("Alimentos")
    shot("app-alimentos", "Stock actual")
    tap("Registrar ingreso")
    shot("app-ingreso", "Registrar ingreso")
    tap("Seleccioná un origen")
    tap("Fundación / ONG")
    tap("Recurrente")
    fill(2, "Arroz")
    back()
    tap("Arroz blanco, crudo")
    fill(3, "2")
    back()
    shot("app-ingreso-completo", "Arroz blanco, crudo")
    tap("Registrar ingreso")
    time.sleep(1)
    shot("app-ingreso-registrado", "Stock actual")
    tap("Registrar egreso")
    tap("Elegí una opción")
    tap("Cocina")
    tap("Elegí del stock disponible")
    tap("Arroz blanco, crudo")
    fill(3, "1")
    back()
    shot("app-egreso-completo", "Disponible:")
    tap("Registrar egreso")
    time.sleep(1)
    shot("app-egreso-registrado", "Stock actual")
    tap("Ver todo el stock")
    shot("app-stock", "Stock")
    tap("Atrás")
    tap("Ver todo")
    shot("app-movimientos", "Movimientos")


def recibos():
    # Requires the fictional image prepared by make-receipt.py in the AVD gallery.
    start()
    tap("Alimentos")
    tap("Registrar con recibo")
    tap("Elegir de galería")
    tap("Photo taken on", contains=True)
    shot("app-recibo-foto", "Procesar recibo")
    tap("Procesar recibo")
    time.sleep(1)
    # This revision's real wire incompatibility must remain visible.
    shot("app-recibo-error", "No se pudo completar.")
    tap("Cargar manualmente con esta foto")
    tap("Seleccioná un origen")
    tap("Fundación / ONG")
    scroll_to("Recurrente")
    tap("Recurrente")
    scroll_to("Agregar alimento")
    shot("app-recibo-manual", "Agregar alimento")
    tap("Agregar alimento")
    fill(2, "Arroz")
    back()
    tap("Arroz blanco, crudo")
    fill(3, "2")
    back()
    tap("Marcar como revisado")
    scroll_to("Guardar ingreso")
    shot("app-recibo-listo", "Guardar ingreso")
    tap("Guardar ingreso")
    time.sleep(1)
    shot("app-recibo-registrado", "Stock actual")


def login():
    start()
    try:
        find("Hola, Ana")
    except RuntimeError:
        shot("app-bienvenida", "Gestioná tu establecimiento")
        tap("Crear cuenta")
        shot("app-registro", "Crear cuenta")
        tap("Atrás")
        tap("Iniciar sesión")
        shot("app-acceso", "Iniciar sesión")
        tap("¿Olvidaste tu contraseña?")
        shot("app-recuperar", "Email")
        tap("Atrás")
        fill(0, "field_worker@manual.example")
        fill(1, "Manual2026!")
        back()
        tap("Iniciar sesión")
        time.sleep(1)
        try:
            tap("Don’t allow")
        except RuntimeError:
            pass
    try:
        find("Comedor Semillas del Sur")
    except RuntimeError:
        tap("Elegí el establecimiento")
        tap("Comedor Semillas del Sur")
    shot("app-inicio-comedor", "Hola, Ana")


def recetas():
    start()
    tap("Recetas")
    shot("app-recetas-generar", "Buscar propuestas")
    fill(0, "10")
    back()
    tap("Almuerzo")
    tap("Buscar propuestas")
    time.sleep(1)
    shot("app-recetas-propuesta", "Arroz para el comedor")
    scroll_to("Elegir esta receta")
    shot("app-recetas-ingredientes", "Elegir esta receta")
    tap("Elegir esta receta")
    shot("app-recetas-confirmacion", "Confirmar y registrar salida")
    tap("Confirmar y registrar salida")
    from android import swipe

    swipe(False)
    swipe(False)
    tap("Historial")
    shot("app-recetas-historial", "Ver receta")
    tap("Ver receta")
    scroll_to("Cantidad de chicos de hoy")
    shot("app-recetas-reutilizar", "Cantidad de chicos de hoy")
    fill(0, "12")
    back()
    tap("Ver cantidades para hoy")
    scroll_to("Cocinar esta receta")
    shot("app-recetas-cantidades", "Cocinar esta receta")


def perfil():
    start()
    tap("Perfil")
    shot("app-perfil", "Mis establecimientos")
    tap("Editar perfil")
    shot("app-perfil-editar", "Guardar")
    tap("Atrás")
    tap("Mis establecimientos")
    shot("app-mis-establecimientos", "Mis establecimientos")
    tap("Comedor Semillas del Sur")
    shot("app-comedor-ficha", "Ubicación")
    tap("Atrás")
    tap("Solicitar acceso")
    shot("app-acceso-solicitar", "Buscar establecimiento")
    tap("¿No encontrás tu comedor? Notificar")
    shot("app-comedor-notificar", "Notificar comedor")
    fill(0, "Comedor Esperanza")
    fill(1, "Belgrano 2500")
    back()
    tap("Siguiente")
    shot("app-comedor-notificar-ficha", "Ficha del comedor")
    # Leave the request unsent: the fixture provides the matching review example.


def apoyos():
    """Capture selectors, offline guidance and confirmation dialogs without saving."""
    start()
    tap("Comedor Semillas del Sur", first=True)
    shot("app-comedor-seleccionar", "Elegí el establecimiento")
    tap("Comedor Semillas del Sur")
    tap("Encuesta")
    find("Seguimiento alimentario")
    try:
        offline(True)
        tap("Atrás")
        tap("Encuesta")
        wait_for("Mostrando encuestas guardadas")
        shot("app-encuestas-sin-conexion", "Mostrando encuestas guardadas")
    finally:
        offline(False)
    tap("Atrás")
    tap("Alimentos")
    tap("Ver todo")
    tap("Egreso")
    shot("app-movimiento-detalle", "Detalle del movimiento")
    start()
    tap("Perfil")
    tap("Cerrar sesión")
    shot("app-cerrar-sesion", "¿Seguro que querés cerrar sesión?")
    tap("Cancelar")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase",
        choices=[
            "login",
            "talla",
            "encuestas",
            "nutrir",
            "recibos",
            "recetas",
            "perfil",
            "apoyos",
        ],
    )
    args = parser.parse_args()
    {
        "login": login,
        "talla": talla,
        "encuestas": encuestas,
        "nutrir": nutrir,
        "recibos": recibos,
        "recetas": recetas,
        "perfil": perfil,
        "apoyos": apoyos,
    }[args.phase]()
