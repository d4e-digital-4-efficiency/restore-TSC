# -*- coding: utf-8 -*-

# from odoo import models, fields, api


# class d4e_companies_custom_reports(models.Model):
#     _name = 'd4e_companies_custom_reports.d4e_companies_custom_reports'
#     _description = 'd4e_companies_custom_reports.d4e_companies_custom_reports'

#     name = fields.Char()
#     value = fields.Integer()
#     value2 = fields.Float(compute="_value_pc", store=True)
#     description = fields.Text()
#
#     @api.depends('value')
#     def _value_pc(self):
#         for record in self:
#             record.value2 = float(record.value) / 100
