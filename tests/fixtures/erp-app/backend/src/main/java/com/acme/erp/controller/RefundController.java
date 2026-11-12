package com.acme.erp.controller;

import com.acme.erp.model.Refund;
import com.acme.erp.repository.RefundRepository;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/refunds")
@RequiredArgsConstructor
public class RefundController {

    private final RefundRepository repository;

    @GetMapping
    public List<Refund> list() {
        return repository.findAll();
    }

    @GetMapping("/{id}")
    public Refund get(@PathVariable Long id) {
        return repository.findById(id).orElseThrow();
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public Refund create(@RequestBody Refund refund) {
        return repository.save(refund);
    }

    @PutMapping("/{id}")
    public Refund update(@PathVariable Long id, @RequestBody Refund refund) {
        refund.setId(id);
        return repository.save(refund);
    }

    @DeleteMapping("/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@PathVariable Long id) {
        repository.deleteById(id);
    }
}
