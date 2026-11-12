package com.acme.erp.controller;

import com.acme.erp.model.StockMovement;
import com.acme.erp.repository.StockMovementRepository;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/stock-movements")
@RequiredArgsConstructor
public class StockMovementController {

    private final StockMovementRepository repository;

    @GetMapping
    public Page<StockMovement> list(Pageable pageable) {
        return repository.findAll(pageable);
    }

    @GetMapping("/{id}")
    public StockMovement get(@PathVariable Long id) {
        return repository.findById(id).orElseThrow();
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public StockMovement create(@RequestBody StockMovement stockMovement) {
        return repository.save(stockMovement);
    }

    @PutMapping("/{id}")
    public StockMovement update(@PathVariable Long id, @RequestBody StockMovement stockMovement) {
        stockMovement.setId(id);
        return repository.save(stockMovement);
    }

    @DeleteMapping("/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@PathVariable Long id) {
        repository.deleteById(id);
    }
}
