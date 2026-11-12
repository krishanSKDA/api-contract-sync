package com.acme.erp.controller;

import com.acme.erp.model.Delivery;
import com.acme.erp.repository.DeliveryRepository;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/deliveries")
@RequiredArgsConstructor
public class DeliveryController {

    private final DeliveryRepository repository;

    @GetMapping
    public List<Delivery> list() {
        return repository.findAll();
    }

    @GetMapping("/{id}")
    public Delivery get(@PathVariable Long id) {
        return repository.findById(id).orElseThrow();
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public Delivery create(@RequestBody Delivery delivery) {
        return repository.save(delivery);
    }

    @PutMapping("/{id}")
    public Delivery update(@PathVariable Long id, @RequestBody Delivery delivery) {
        delivery.setId(id);
        return repository.save(delivery);
    }

    @DeleteMapping("/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@PathVariable Long id) {
        repository.deleteById(id);
    }
}
