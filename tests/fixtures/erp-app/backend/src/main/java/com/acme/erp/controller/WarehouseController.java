package com.acme.erp.controller;

import com.acme.erp.model.Warehouse;
import com.acme.erp.repository.WarehouseRepository;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/warehouses")
@RequiredArgsConstructor
public class WarehouseController {

    private final WarehouseRepository repository;

    @GetMapping
    public List<Warehouse> list() {
        return repository.findAll();
    }

    @GetMapping("/{id}")
    public Warehouse get(@PathVariable Long id) {
        return repository.findById(id).orElseThrow();
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public Warehouse create(@RequestBody Warehouse warehouse) {
        return repository.save(warehouse);
    }

    @PutMapping("/{id}")
    public Warehouse update(@PathVariable Long id, @RequestBody Warehouse warehouse) {
        warehouse.setId(id);
        return repository.save(warehouse);
    }

    @DeleteMapping("/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@PathVariable Long id) {
        repository.deleteById(id);
    }
}
