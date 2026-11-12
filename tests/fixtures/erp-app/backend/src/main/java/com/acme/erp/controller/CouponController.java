package com.acme.erp.controller;

import com.acme.erp.model.Coupon;
import com.acme.erp.repository.CouponRepository;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import java.time.LocalDate;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/coupons")
@RequiredArgsConstructor
public class CouponController {

    private final CouponRepository repository;

    @GetMapping
    public List<Coupon> list() {
        return repository.findAll();
    }

    @GetMapping("/{id}")
    public Coupon get(@PathVariable Long id) {
        return repository.findById(id).orElseThrow();
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public Coupon create(@Valid @RequestBody CreateCouponRequest request) {
        Coupon coupon = new Coupon();
        coupon.setCode(request.code());
        coupon.setExpiresAt(request.expiresAt());
        return repository.save(coupon);
    }

    @PutMapping("/{id}")
    public Coupon update(@PathVariable Long id, @RequestBody Coupon coupon) {
        coupon.setId(id);
        return repository.save(coupon);
    }

    @DeleteMapping("/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@PathVariable Long id) {
        repository.deleteById(id);
    }

    public record CreateCouponRequest(@NotBlank String code, @NotNull LocalDate expiresAt) { }
}
