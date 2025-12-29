from odoo import models, _
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _get_ml_done_field(self):
        ml_fields = self.env["stock.move.line"]._fields
        for fname in ("quantity", "quantity_done", "qty_done"):
            if fname in ml_fields:
                return fname
        raise UserError(_("No existe campo de cantidad hecha en stock.move.line."))

    def _get_ml_reserved_field(self):
        ml_fields = self.env["stock.move.line"]._fields
        for fname in ("reserved_uom_qty", "reserved_qty"):
            if fname in ml_fields:
                return fname
        return None

    def _prepare_move_line_vals(self, picking, move, done_field):
        vals = {
            "move_id": move.id,
            "picking_id": picking.id,
            "company_id": picking.company_id.id,
            "product_id": move.product_id.id,
            "product_uom_id": move.product_uom.id,
            "location_id": move.location_id.id,
            "location_dest_id": move.location_dest_id.id,
            done_field: 0.0,
        }

        ml_model = self.env["stock.move.line"]
        if "operating_unit_id" in ml_model._fields and "operating_unit_id" in picking._fields:
            vals["operating_unit_id"] = picking.operating_unit_id.id

        for fname in ("owner_id", "package_id", "result_package_id", "lot_id"):
            if fname in ml_model._fields and fname in move._fields and getattr(move, fname, False):
                vals[fname] = getattr(move, fname).id

        return vals

    def _auto_fix_internal_transfer_before_done(self):
        self.ensure_one()
        if self.picking_type_id.code != "internal":
            return

        picking = self.sudo()
        done_field = picking._get_ml_done_field()
        reserved_field = picking._get_ml_reserved_field()

        if picking.state in ("confirmed", "assigned"):
            picking.action_assign()

        fixes = []

        tracked_missing = picking.move_line_ids.filtered(
            lambda ml: ml.state != "done"
            and ml.product_id.tracking != "none"
            and not ml.lot_id
            and not (ml.lot_name or "").strip()
        )
        if tracked_missing:
            picking.message_post(body=_(
                "<b>Auto-fix NO aplicado</b>: faltan lotes/series.<br/>Cargalos y volvé a validar."
            ))
            raise UserError(_("Faltan lotes/series. Revisá el chatter del albarán."))

        for move in picking.move_ids_without_package.filtered(lambda m: m.state not in ("done", "cancel")):
            move = move.sudo()

            if not move.move_line_ids:
                self.env["stock.move.line"].sudo().create(
                    self._prepare_move_line_vals(picking, move, done_field)
                )
                fixes.append(f"{move.product_id.display_name}: se creó move line faltante")

            for ml in move.move_line_ids.filtered(lambda x: x.state != "done"):
                ml = ml.sudo()
                current_done = getattr(ml, done_field) or 0.0
                if current_done:
                    continue

                # Opción B: si no hay reserva, no inventar quantity_done/quantity
                if reserved_field and not (getattr(ml, reserved_field) or 0.0):
                    fixes.append(f"{move.product_id.display_name}: sin reserva, no se completa cantidad")
                    continue

                qty = (getattr(ml, reserved_field) or 0.0) if reserved_field else 0.0
                if not qty:
                    qty = move.product_uom_qty

                setattr(ml, done_field, qty)
                fixes.append(f"{move.product_id.display_name}: {done_field}=0 → {qty}")

        if any("sin reserva" in x for x in fixes):
            picking.message_post(body=_(
                "<b>Auto-fix NO aplicado</b>: hay líneas sin reserva, no se completa cantidad para evitar inconsistencias.<br/>"
                "<br/><b>Detalle:</b><br/>%s"
            ) % "<br/>".join(f"- {x}" for x in fixes))
            raise UserError(_("Hay líneas sin reserva. Revisá el chatter del albarán."))

        if fixes:
            picking.message_post(body=_(
                "<b>Auto-fix aplicado</b> antes de validar el traslado interno.<br/>"
                "<br/><b>Detalle:</b><br/>%s"
            ) % "<br/>".join(f"- {x}" for x in fixes))
