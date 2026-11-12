package com.acme.erp.controller;

import com.acme.erp.model.Invoice;

final class InvoiceText {
    private InvoiceText() { }

    static String render(Invoice invoice) {
        return "INVOICE " + invoice.getNumber() + "\nTOTAL " + invoice.getTotal();
    }
}
