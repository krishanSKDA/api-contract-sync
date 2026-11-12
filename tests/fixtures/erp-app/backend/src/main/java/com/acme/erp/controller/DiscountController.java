package com.acme.erp.controller;

import com.acme.erp.model.Discount;
import com.acme.erp.repository.DiscountRepository;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/discounts")
@RequiredArgsConstructor
public class DiscountController {

    private final DiscountRepository repository;

    @GetMapping
    public List<Discount> list() {
        return repository.findAll();
    }

    @GetMapping("/{id}")
    public Discount get(@PathVariable Long id) {
        return repository.findById(id).orElseThrow();
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public Discount create(@RequestBody Discount discount) {
        return repository.save(discount);
    }

    @PutMapping("/{id}")
    public Discount update(@PathVariable Long id, @RequestBody Discount discount) {
        discount.setId(id);
        return repository.save(discount);
    }

    @DeleteMapping("/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@PathVariable Long id) {
        repository.deleteById(id);
    }
}
