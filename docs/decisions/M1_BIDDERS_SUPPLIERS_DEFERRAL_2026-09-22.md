# M1 decision — bidder/supplier identity resolution deferral

## Observed evidence

M1 measured the direct Bronze hypothesis:

```text
bidders.codigo_proveedor -> suppliers.codigo
```

at **0% left-row coverage**. The failure is therefore known and quantified; it is not an untested assumption.

The official SECOP II metadata describes both fields as platform supplier identifiers, so the zero overlap is treated as a representation/identity-resolution problem that requires further diagnosis rather than as permission to coerce or arbitrarily rewrite identifiers.

## Scope decision

This relationship does **not** block the first contract-level addition-risk Silver layer because:

- `contracts.id_contrato` is the V1 contract key;
- `additions -> contracts` has near-complete direct coverage;
- `contracts -> suppliers` already has high direct coverage;
- bidder/supplier linkage is not required to materialize the initial contract/event canonical tables or to establish `y_addition_180d` feasibility.

M1 therefore keeps the failed direct join visible as a **non-blocking deferred relationship** and adds a blocking requirement that the deferral itself is explicit.

## Silver obligation

`13_entity_resolution.ipynb` must resolve bidder identity before bidder/supplier historical features are admitted. At minimum it should evaluate:

1. raw representation differences in `Codigo Proveedor` versus `Codigo`;
2. deterministic normalization that does not merge distinct provider identities;
3. `NIT Proveedor -> NIT` after documented normalization;
4. one-to-many/many-to-one conflicts and ambiguous NITs;
5. coverage gained at each identity-resolution tier;
6. unmatched-population characteristics.

No fuzzy match should be introduced before deterministic identifiers are exhausted and quantified.

## Target semantic obligation

The M1 target uses every parsable row in the dedicated Adiciones source only as a feasibility scope. Before Gold/model training, ARGOS must either justify that event scope and rename the target to match it, or explicitly freeze the `Tipo` values that constitute the intended outcome.
