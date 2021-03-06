import time

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SaleAdvancePaymentInv(models.TransientModel):
    _inherit = "sale.advance.payment.inv"


    advance_payment_method = fields.Selection(selection_add=[('situation', 'Situation')],
        string='Create Invoice', default='delivered', required=True,
        help="A standard invoice is issued with all the order lines ready for invoicing, \
        according to their invoicing policy (based on ordered or delivered quantity).")

    situation_amount = fields.Monetary('Situation Amount')


    @api.model
    def default_get(self,fields):
        res = super(SaleAdvancePaymentInv, self).default_get(fields)
        if self.env.context.get('is_solde'):
            cx_order = self.env.context.get('active_id')
            order = self.env['sale.order'].search([('id', '=', cx_order)])
            o_lines = order.order_line
            amount = 0
            for l in o_lines:
                if l.is_downpayment == True:
                    amount += l.price_unit
            solde = order.amount_untaxed - amount
            res['situation_amount'] = solde
            print('rec.situation_amount: ', res['situation_amount'])
        return res

    def _create_invoice(self, order, so_line, amount):
        if (self.advance_payment_method == 'percentage' and self.amount <= 0.00) or (self.advance_payment_method == 'fixed' and self.fixed_amount <= 0.00):
            raise UserError(_('The value of the down payment amount must be positive.'))
        if self.advance_payment_method == 'percentage':
            is_situation = False
            amount = order.amount_untaxed * self.amount / 100
            name = _("Down payment of %s%%") % (self.amount,)
            inv_lines = [(0,0, {
                'name': name,
                'price_unit': amount,
                'quantity': 1.0,
                'product_id': self.product_id.id,
                'product_uom_id': so_line.product_uom.id,
                'tax_ids': [(6, 0, so_line.tax_id.ids)],
                'sale_line_ids': [(6, 0, [so_line.id])],
                'analytic_tag_ids': [(6, 0, so_line.analytic_tag_ids.ids)],
                'analytic_account_id': order.analytic_account_id.id or False,
            })]
        if self.advance_payment_method == 'fixed':
            is_situation = False
            amount = self.fixed_amount
            name = _('Down Payment')
            inv_lines = [(0,0, {
                'name': name,
                'price_unit': amount,
                'quantity': 1.0,
                'product_id': self.product_id.id,
                'product_uom_id': so_line.product_uom.id,
                'tax_ids': [(6, 0, so_line.tax_id.ids)],
                'sale_line_ids': [(6, 0, [so_line.id])],
                'analytic_tag_ids': [(6, 0, so_line.analytic_tag_ids.ids)],
                'analytic_account_id': order.analytic_account_id.id or False,
            })]
        if self.advance_payment_method == 'situation' and self.situation_amount <= 0:
            raise UserError(_('The value of the situation amount must be positive.'))
        if self.advance_payment_method == 'situation':
            situation_invs = self.env['account.move'].search([('is_situation','=',True),('invoice_origin','=',order.name)])
            note_name = _('Market price TE : ') + str('{:,.2f}'.format(order.amount_untaxed).replace(',', '\''))+' CHF\n'
            for i,inv in enumerate(reversed(situation_invs)):
                note_name += 'Situation '+ str(i+1) + _(' of ') + str(inv.invoice_date.strftime('%d/%m/%Y')) + ' : ' + str('{:,.2f}'.format(inv.amount_untaxed).replace(',', '\''))+ ' CHF' +'\n'

            is_situation = True
            amount = self.situation_amount
            name = "Situation %s" %(len(situation_invs) + 1) + _(" depending on the progress of the done work")

            inv_lines = [(0,0, {'display_type': 'line_note','name': note_name}),
                         (0,0, {
                            'name': name,
                            'price_unit': amount,
                            'quantity': 1.0,
                            'product_id': self.product_id.id,
                            'product_uom_id': so_line.product_uom.id,
                            'tax_ids': [(6, 0, so_line.tax_id.ids)],
                            'sale_line_ids': [(6, 0, [so_line.id])],
                            'analytic_tag_ids': [(6, 0, so_line.analytic_tag_ids.ids)],
                            'analytic_account_id': order.analytic_account_id.id or False,
                            'account_id': int(self.env['ir.config_parameter'].sudo().get_param('d4e_invoice_situation.situation_account')) or False
                         })]


        invoice_vals = {
            'invoice_date': fields.Date.today(),
            'is_situation': is_situation,
            'type': 'out_invoice',
            'invoice_origin': order.name,
            'invoice_user_id': order.user_id.id,
            'narration': order.note,
            'partner_id': order.partner_invoice_id.id,
            'fiscal_position_id': order.fiscal_position_id.id or order.partner_id.property_account_position_id.id,
            'partner_shipping_id': order.partner_shipping_id.id,
            'currency_id': order.pricelist_id.currency_id.id,
            'invoice_payment_ref': order.client_order_ref,
            'invoice_payment_term_id': order.payment_term_id.id,
            'invoice_partner_bank_id': order.company_id.partner_id.bank_ids[:1],
            'team_id': order.team_id.id,
            'campaign_id': order.campaign_id.id,
            'medium_id': order.medium_id.id,
            'source_id': order.source_id.id,
            'invoice_line_ids': inv_lines,
        }
        if order.fiscal_position_id:
            invoice_vals['fiscal_position_id'] = order.fiscal_position_id.id
        invoice = self.env['account.move'].sudo().create(invoice_vals).with_user(self.env.uid)
        invoice.message_post_with_view('mail.message_origin_link',
                    values={'self': invoice, 'origin': order},
                    subtype_id=self.env.ref('mail.mt_note').id)
        return invoice

    def create_invoices(self):
        sale_orders = self.env['sale.order'].browse(self._context.get('active_ids', []))

        if self.advance_payment_method == 'delivered':
            sale_orders._create_invoices(final=self.deduct_down_payments)
        else:
            # Create deposit product if necessary
            if not self.product_id:
                vals = self._prepare_deposit_product()
                self.product_id = self.env['product.product'].create(vals)
                self.env['ir.config_parameter'].sudo().set_param('sale.default_deposit_product_id', self.product_id.id)

            sale_line_obj = self.env['sale.order.line']
            for order in sale_orders:
                if self.advance_payment_method == 'percentage':
                    amount = order.amount_untaxed * self.amount / 100
                elif self.advance_payment_method == 'fixed':
                    amount = self.fixed_amount
                elif self.advance_payment_method == 'situation':
                    amount = self.situation_amount
                if self.product_id.invoice_policy != 'order':
                    raise UserError(_('The product used to invoice a down payment should have an invoice policy set to "Ordered quantities". Please update your deposit product to be able to create a deposit invoice.'))
                if self.product_id.type != 'service':
                    raise UserError(_("The product used to invoice a down payment should be of type 'Service'. Please use another product or update this product."))
                taxes = self.product_id.taxes_id.filtered(lambda r: not order.company_id or r.company_id == order.company_id)
                if order.fiscal_position_id and taxes:
                    tax_ids = order.fiscal_position_id.map_tax(taxes, self.product_id, order.partner_shipping_id).ids
                else:
                    tax_ids = taxes.ids
                context = {'lang': order.partner_id.lang}
                analytic_tag_ids = []
                for line in order.order_line:
                    analytic_tag_ids = [(4, analytic_tag.id, None) for analytic_tag in line.analytic_tag_ids]
                so_line = sale_line_obj.create({
                    'name': _('Down Payment: %s') % (time.strftime('%m %Y'),),
                    'price_unit': amount,
                    'product_uom_qty': 0.0,
                    'order_id': order.id,
                    'discount': 0.0,
                    'product_uom': self.product_id.uom_id.id,
                    'product_id': self.product_id.id,
                    'analytic_tag_ids': analytic_tag_ids,
                    'tax_id': [(6, 0, tax_ids)],
                    'is_downpayment': True,
                })
                del context
                self._create_invoice(order, so_line, amount)
        if self._context.get('open_invoices', False):
            return sale_orders.action_view_invoice()
        return {'type': 'ir.actions.act_window_close'}
