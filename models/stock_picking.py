from odoo import models, _
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = "stock.picking"


    def _auto_fix_internal_transfer_before_done(self):
        """Auto-fix SOLO para pickings internos, justo antes del _action_done().
        - Intenta reservar (action_assign)
        - Completa qty_done usando reservado si existe; si no, usa la demanda (solo si hay stock asignable)
        - Crea move lines faltantes
        - Postea en chatter lo que corrigió
        """
        self.ensure_one()

        if self.picking_type_id.code != "internal":
            return

        picking = self.sudo()

        # Re-reservar por si quedó a mitad de camino
        if picking.state in ("confirmed", "assigned"):
            picking.action_assign()


        # Si hay tracking y faltan lotes/series, NO inventamos trazabilidad.
        tracked_missing_lot = picking.move_line_ids.filtered(
            lambda ml: ml.state != "done"
            and ml.product_id.tracking != "none"
            and not ml.lot_id
        )
        if tracked_missing_lot:
            body = _(
                "<b>Auto-fix NO aplicado</b>: faltan lotes/series en productos con tracking.<br/>"
                "Cargalos y volvé a validar.<br/><br/>%s"
            ) % "<br/>".join(
                f"- {ml.product_id.display_name} (Desde: {ml.location_id.display_name} → A: {ml.location_dest_id.display_name})"
                for ml in tracked_missing_lot
            )
            picking.message_post(body=body)
            raise UserError(_("Faltan lotes/series. Revisá el chatter del albarán."))

        fixes = []

        for move in picking.move_ids_without_package.filtered(lambda m: m.state not in ("done", "cancel")):
            move = move.sudo()

            # A) Si no hay move lines, crear una base (sin qty_done todavía)
            if not move.move_line_ids:
                self.env["stock.move.line"].sudo().create({
                    "move_id": move.id,
                    "picking_id": picking.id,
                    "product_id": move.product_id.id,
                    "product_uom_id": move.product_uom.id,
                    "location_id": move.location_id.id,
                    "location_dest_id": move.location_dest_id.id,
                    "qty_done": 0.0,
                })
                fixes.append(f"{move.product_id.display_name}: se creó stock.move.line faltante")

            # B) Completar qty_done en líneas no done
            for ml in move.move_line_ids.filtered(lambda x: x.state != "done"):
                ml = ml.sudo()
                if ml.qty_done:
                    continue

                # Usamos reservado si existe. Si no hay reservado, NO forzamos a ciegas:
                # intentamos usar la demanda solo si el move está assigned (reservado a nivel move).
                qty = ml.reserved_uom_qty
                if not qty:
                    if move.state == "assigned":
                        qty = move.product_uom_qty
                    else:
                        # No hay reserva → mejor cortar con mensaje y no dejar un "hecho" mentiroso.
                        fixes.append(
                            f"{move.product_id.display_name}: sin reserva, no se pudo completar qty_done automáticamente"
                        )
                        continue

                ml.qty_done = qty
                fixes.append(f"{move.product_id.display_name}: qty_done=0 → {qty}")

        # Si quedó algo sin poder completar, mejor frenar: te evita inconsistencias.
        if any("sin reserva" in x for x in fixes):
            picking.message_post(body=_(
                "<b>Auto-fix parcialmente aplicado</b> pero se detectaron líneas sin reserva. "
                "No se validó para evitar inconsistencias.<br/><br/><b>Detalle:</b><br/>%s"
            ) % "<br/>".join(f"- {x}" for x in fixes))
            raise UserError(_("Hay líneas sin reserva. Revisá el chatter del albarán."))

        if fixes:
            picking.message_post(body=_(
                "<b>Auto-fix aplicado</b> antes de validar el traslado interno para asegurar consistencia.<br/>"
                "<br/><b>Acciones:</b><br/>%s"
            ) % "<br/>".join(f"- {x}" for x in fixes))

    def _action_done(self):
        # Se ejecuta justo cuando Odoo intenta dejar en DONE, incluso si hubo wizard.
        for picking in self:
            if picking.picking_type_id.code == "internal":
                picking._auto_fix_internal_transfer_before_done()
        return super()._action_done()
