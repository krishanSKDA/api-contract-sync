package com.acme.erp.controller;

import com.acme.erp.model.Invoice;
import com.acme.erp.repository.InvoiceRepository;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/invoices")
@RequiredArgsConstructor
public class InvoiceController {

    private final InvoiceRepository repository;

    @GetMapping
    public List<Invoice> list() {
        return repository.findAll();
    }

    @GetMapping("/{id}")
    public Invoice get(@PathVariable Long id) {
        return repository.findById(id).orElseThrow();
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public Invoice create(@RequestBody Invoice invoice) {
        return repository.save(invoice);
    }

    @PutMapping("/{id}")
    public Invoice update(@PathVariable Long id, @RequestBody Invoice invoice) {
        invoice.setId(id);
        return repository.save(invoice);
    }

    @DeleteMapping("/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@PathVariable Long id) {
        repository.deleteById(id);
    }

    /** Plain-text invoice for the receipt printer. */
    @GetMapping("/{id}/print")
    public String print(@PathVariable Long id) {
        return repository.findById(id).map(InvoiceText::render).orElseThrow();
    }
}
