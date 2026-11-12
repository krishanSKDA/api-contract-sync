package com.acme.erp.controller;

import com.acme.erp.model.Shift;
import com.acme.erp.repository.ShiftRepository;
import java.time.LocalDateTime;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/shifts")
@RequiredArgsConstructor
public class ShiftController {

    private final ShiftRepository repository;

    @GetMapping
    public List<Shift> list() {
        return repository.findAll();
    }

    @GetMapping("/{id}")
    public Shift get(@PathVariable Long id) {
        return repository.findById(id).orElseThrow();
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public Shift create(@RequestBody Shift shift) {
        return repository.save(shift);
    }

    @PutMapping("/{id}")
    public Shift update(@PathVariable Long id, @RequestBody Shift shift) {
        shift.setId(id);
        return repository.save(shift);
    }

    @DeleteMapping("/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@PathVariable Long id) {
        repository.deleteById(id);
    }

    @PutMapping("/{id}/close")
    public Shift close(@PathVariable Long id) {
        Shift shift = repository.findById(id).orElseThrow();
        shift.setClosedAt(LocalDateTime.now());
        return repository.save(shift);
    }
}
