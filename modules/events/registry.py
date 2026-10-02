"""Canonical event types ERP may produce or consume (Shared events/v1/event-registry.yaml, pinned
by contracts.lock.yaml), with the payload schema each carries.

ERP emits only registered types: there is no second event vocabulary. The registry is the contract;
this table is its ERP-side index and is checked against the pinned Shared registry by the conformance
suite (ERP-COMPAT-06). Producers are recorded as repository names, e.g. baobab-erp."""

CONTRACT_HOST = "https://contracts.baobab-platform.com/"
ERP_SOURCE = "urn:baobab-platform:service:baobab-erp"
SOURCE_PREFIX = "urn:baobab-platform:service:"


def _erp(schema: str) -> str:
    return f"{CONTRACT_HOST}erp/v1/{schema}.schema.json"


# type -> the immutable payload schema URI carried in dataschema
PRODUCED = {
    "com.baobab-platform.erp.business-partner.changed.v1": _erp("business-partner-projection"),
    "com.baobab-platform.erp.inventory.availability-changed.v1": _erp("inventory-availability"),
    "com.baobab-platform.erp.invoice.changed.v1": _erp("invoice-outcome"),
    "com.baobab-platform.erp.order.consequence-changed.v1": _erp("order-consequence-status"),
    "com.baobab-platform.erp.payment.accounting-changed.v1": _erp("payment-outcome"),
    "com.baobab-platform.erp.provisioning.changed.v1": _erp("provisioning-state"),
    "com.baobab-platform.erp.warehouse.changed.v1": _erp("warehouse-projection"),
    # Registered to baobab-erp in the buyer-organisation contract (ERP owns authoritative credit).
    "com.baobab-platform.customer.buyer-commercial-profile.changed.v1": (
        f"{CONTRACT_HOST}buyer-organisation/v1/events.schema.json#/$defs/buyerCommercialProfileChangedEventData"
    ),
}

# type -> (payload schema URI, producing repository)
CONSUMED = {
    "com.baobab-platform.trade.order.placed.v1": (_erp("commerce-order-consequence"), "baobab-trade"),
    "com.baobab-platform.trade.customer.projected.v1": (_erp("customer-projection"), "baobab-trade"),
}


def dataschema_for(event_type: str) -> str:
    if event_type in PRODUCED:
        return PRODUCED[event_type]
    if event_type in CONSUMED:
        return CONSUMED[event_type][0]
    raise KeyError(event_type)


def accepted_sources(producer_repository: str) -> frozenset[str]:
    """A producer is identified by its repository name or the bare service name (the Shared examples use
    both forms, e.g. urn:baobab-platform:service:trade for baobab-trade)."""
    bare = producer_repository.removeprefix("baobab-")
    return frozenset({SOURCE_PREFIX + producer_repository, SOURCE_PREFIX + bare})
