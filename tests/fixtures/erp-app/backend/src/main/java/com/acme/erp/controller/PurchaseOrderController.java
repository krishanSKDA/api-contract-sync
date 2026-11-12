package com.acme.erp.controller;

import com.acme.erp.model.PoStatus;
import com.acme.erp.model.PurchaseOrder;
import com.acme.erp.repository.PurchaseOrderRepository;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/purchase-orders")
@RequiredArgsConstructor
public class PurchaseOrderController {

    private final PurchaseOrderRepository repository;

    @GetMapping
    public List<PurchaseOrder> list() {
        return repository.findAll();
    }

    @GetMapping("/{id}")
    public PurchaseOrder get(@PathVariable Long id) {
        return repository.findById(id).orElseThrow();
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public PurchaseOrder create(@RequestBody PurchaseOrder purchaseOrder) {
        return repository.save(purchaseOrder);
    }

    @PutMapping("/{id}")
    public PurchaseOrder update(@PathVariable Long id, @RequestBody PurchaseOrder purchaseOrder) {
        purchaseOrder.setId(id);
        return repository.save(purchaseOrder);
    }

    @DeleteMapping("/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@PathVariable Long id) {
        repository.deleteById(id);
    }

    @PostMapping("/{id}/approval")
    public PurchaseOrder approve(@PathVariable Long id) {
        PurchaseOrder po = repository.findById(id).orElseThrow();
        po.setStatus(PoStatus.APPROVED);
        return repository.save(po);
    }
}
