package com.acme.erp.controller;

import com.acme.erp.model.Supplier;
import com.acme.erp.repository.SupplierRepository;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/suppliers")
@RequiredArgsConstructor
public class SupplierController {

    private final SupplierRepository repository;

    @GetMapping
    public List<Supplier> list() {
        return repository.findAll();
    }

    @GetMapping("/{id}")
    public Supplier get(@PathVariable Long id) {
        return repository.findById(id).orElseThrow();
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public Supplier create(@RequestBody Supplier supplier) {
        return repository.save(supplier);
    }

    @PutMapping("/{id}")
    public Supplier update(@PathVariable Long id, @RequestBody Supplier supplier) {
        supplier.setId(id);
        return repository.save(supplier);
    }

    @DeleteMapping("/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@PathVariable Long id) {
        repository.deleteById(id);
    }
}
