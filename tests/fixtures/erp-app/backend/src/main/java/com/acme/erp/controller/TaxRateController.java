package com.acme.erp.controller;

import com.acme.erp.model.TaxRate;
import com.acme.erp.repository.TaxRateRepository;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/tax-rates")
@RequiredArgsConstructor
public class TaxRateController {

    private final TaxRateRepository repository;

    @GetMapping
    public List<TaxRate> list() {
        return repository.findAll();
    }

    @GetMapping("/{id}")
    public TaxRate get(@PathVariable Long id) {
        return repository.findById(id).orElseThrow();
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public TaxRate create(@RequestBody TaxRate taxRate) {
        return repository.save(taxRate);
    }

    @PutMapping("/{id}")
    public TaxRate update(@PathVariable Long id, @RequestBody TaxRate taxRate) {
        taxRate.setId(id);
        return repository.save(taxRate);
    }

    @DeleteMapping("/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@PathVariable Long id) {
        repository.deleteById(id);
    }
}
