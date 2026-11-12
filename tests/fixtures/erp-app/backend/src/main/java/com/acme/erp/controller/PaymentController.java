package com.acme.erp.controller;

import com.acme.erp.model.Payment;
import com.acme.erp.repository.PaymentRepository;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/payments")
@RequiredArgsConstructor
public class PaymentController {

    private final PaymentRepository repository;

    @GetMapping
    public List<Payment> list() {
        return repository.findAll();
    }

    @GetMapping("/{id}")
    public Payment get(@PathVariable Long id) {
        return repository.findById(id).orElseThrow();
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public Payment create(@RequestBody Payment payment) {
        return repository.save(payment);
    }

    @PutMapping("/{id}")
    public Payment update(@PathVariable Long id, @RequestBody Payment payment) {
        payment.setId(id);
        return repository.save(payment);
    }

    @DeleteMapping("/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@PathVariable Long id) {
        repository.deleteById(id);
    }
}
