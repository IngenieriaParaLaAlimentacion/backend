### Épica

Aplicación Mobile

### Descripción

Como **usuario autenticado** (admin, manager o profesional), quiero poder ver mi perfil para revisar mi información personal y el estado de mis establecimientos asociados (si aplica).

### Criterios de aceptación

**CA 1: Vista del perfil propio**

- [ ] Dado que un usuario tiene una cuenta activa, cuando accede a su perfil, entonces puede ver su nombre, apellido, email, rol y un listado de los establecimientos asociados (si aplica), cada uno con su estado actual (Aceptado, Pendiente, Rechazado).

**CA 2: Acceso directo a edición**

- [ ] Dado que un usuario está viendo su propio perfil, cuando quiere editarlo, entonces tiene acceso directo a la pantalla de edición.

**CA 3: Estado vacío de establecimientos**

- [ ] Dado que un usuario con rol manager no tiene ningún establecimiento asociado, cuando accede a su perfil, entonces se muestra un mensaje indicando que aún no tiene establecimientos y una opción para solicitar acceso.

### Puntos de historia

1

### Tipo de historia

⭐ Obligatoria

### Notas

Aplica para los tres roles (admin, manager y profesional). Solo el rol manager muestra la sección de establecimientos asociados.
