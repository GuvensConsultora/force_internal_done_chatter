# Internal Transfer Auto-Fix (Chatter) — Odoo 17

Este módulo agrega una corrección automática **solo al momento de validar** (pasar a *Hecho*) un **Traslado interno** en Inventario.

Su objetivo es evitar situaciones inconsistentes donde el **albarán (picking)** queda validado o avanzado, pero el **historial de movimientos** muestra líneas en estado *Disponible/Asignado* y el stock no queda correctamente registrado.

---

## Qué problema resuelve

En algunos escenarios (por ejemplo, con restricciones de permisos, Operating Units, reglas personalizadas o validaciones incompletas), puede ocurrir que:

- el usuario valida un traslado interno,
- el sistema deja movimientos/líneas sin cerrar,
- en *Historial de movimientos* (modelo `stock.move.line`) quedan registros en **Disponible**,
- y el movimiento de inventario no queda correctamente reflejado.

Este módulo intenta **cerrar el proceso de forma consistente** antes de que Odoo ejecute el cierre final.

---

## Qué hace exactamente

Al ejecutar la validación final del picking (`_action_done()`):

1. **Se ejecuta SOLO para pickings internos** (`picking_type_id.code == 'internal'`).
2. Fuerza una re-reserva previa si aplica (`action_assign()`), para asegurar que el movimiento tenga stock asignado.
3. Para cada `stock.move` del picking (no cancelado / no done):
   - Si **no existen líneas** (`stock.move.line`), crea una línea mínima con origen/destino correctos.
   - Si existen líneas y **`qty_done` está en 0**, completa `qty_done`:
     - prioriza `reserved_uom_qty` de la línea,
     - si no hay reservado, usa la demanda **solo si el move está en `assigned`**.
4. Si detecta productos con tracking (lote/serie) **sin lote/serie cargado**, **no inventa trazabilidad**:
   - postea un mensaje en chatter,
   - y bloquea la validación con `UserError`.
5. Registra todo lo que corrigió mediante un **mensaje en el chatter del albarán** (`message_post`).

---

## Qué NO hace

- No altera entregas (`OUT`) ni recepciones (`IN`), **solo traslados internos**.
- No modifica el comportamiento general del inventario fuera del momento de validación.
- No asigna lotes/series automáticamente.
- No crea “ubicaciones puente” ni reglas de abastecimiento.

---

## Por qué se engancha en `_action_done()` y no en `button_validate()`

`button_validate()` puede devolver wizards (backorder / immediate transfer) y no siempre ejecuta el cierre real en ese instante.

`_action_done()` es el punto en el que Odoo efectivamente intenta dejar el picking en **DONE**, por eso este módulo interviene **justo antes del cierre final**, asegurando consistencia.

---

## Archivos principales

- `models/stock_picking.py`
  - Override de `stock.picking._action_done()`
  - Método auxiliar `_auto_fix_internal_transfer_before_done()`

---

## Instalación

1. Copiar el módulo al `addons_path` custom.
2. Reiniciar el servicio de Odoo.
3. Actualizar el módulo desde Apps o por consola:
   ```bash
   ./odoo-bin -d TU_DB -u force_internal_done_chatter --stop-after-init
