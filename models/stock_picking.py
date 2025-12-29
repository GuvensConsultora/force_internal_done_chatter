from odoo import models, _
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _get_ml_done_field(self):
        """En tu Odoo 17 (según modelo) es 'quantity'. Lo dejo robusto."""
        ml_fields = self.env["stock.move.line"]._fields
        for fname in ("quantity", "quantity_done", "qty_done"):
            if fname in ml_fields:
                return fname
        raise UserError(_("No existe campo de cantidad hecha en stock.move.line."))

    def _get_ml_reserved_field(self):
        """Usar si existe; si no, fallback a demanda del move."""
        ml_fields = self.env["stock.move.line"]._fields
        for fname in ("reserved_uom_qty", "reserved_qty", "product_uom_qty"):
            if fname in ml_fields:
                return fname
        return None

    def _auto_fix_internal_transfer_before_done(self):
        self.ensure_one()
        if self.picking_type_id.code != "internal":
            return

        picking = self.sudo()
        done_field = picking._get_ml_done_field()
        reserved_field = picking._get_ml_reserved_field()

        # Intentar asignar antes (si corresponde)
        if picking.state in ("confirmed", "assigned"):
            picking.action_assign()

        fixes = []

        # Validación: si hay tracking, no inventamos lotes/series
        tracked_missing = picking.move_line_ids.filtered(
            lambda ml: ml.state != "done"
            and getattr(ml, "tracking", "none") != "none"
            and not ml.lot_id
            and not (ml.lot_name or "").strip()
        )
        if tracked_missing:
            picking.message_post(body=_(
                "<b>Auto-fix NO aplicado</b>: faltan lotes/series en líneas con tracking.<br/>"
                "Cargalos y volvé a validar."
            ))
            raise UserError(_("Faltan lotes/series. Revisá el chatter del albarán."))

        for move in picking.move_ids_without_package.filtered(lambda m: m.state not in ("done", "cancel")):
            move = move.sudo()

            # Si no hay líneas, crear al menos una mínima
            if not move.move_line_ids:
                self.env["stock.move.line"].sudo().create({
                    "move_id": move.id,
                    "picking_id": picking.id,
                    "product_id": move.product_id.id,
                    "product_uom_id": move.product_uom.id,
                    "location_id": move.location_id.id,
                    "location_dest_id": move.location_dest_id.id,
                    done_field: 0.0,
                })
                fixes.append(f"{move.product_id.display_name}: se creó move line faltante")

            # Completar quantity solo cuando está en 0
            for ml in move.move_line_ids.filtered(lambda x: x.state != "done"):
                ml = ml.sudo()
                current_done = getattr(ml, done_field) or 0.0
                if current_done:
                    continue

                qty = 0.0
                if reserved_field:
                    qty = getattr(ml, reserved_field) or 0.0

                # fallback: usar demanda del move
                if not qty:
                    qty = move.product_uom_qty

                setattr(ml, done_field, qty)
                fixes.append(f"{move.product_id.display_name}: {done_field}=0 → {qty}")

        if fixes:
            picking.message_post(body=_(
                "<b>Auto-fix aplicado</b> antes de validar el traslado interno.<br/>"
                "<br/><b>Detalle:</b><br/>%s"
            ) % "<br/>".join(f"- {x}" for x in fixes))

    def _action_done(self):
        for picking in self:
            if picking.picking_type_id.code == "internal":
                picking._auto_fix_internal_transfer_before_done()
        return super()._action_done()
