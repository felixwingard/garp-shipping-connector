# Bring-implementation

Integration med Bring Booking API för sändningar till Norge.

## Produkter

| srvid i GARP | Bring API-kod | Beskrivning |
|--------------|---------------|-------------|
| BRING:0342 | PICKUP_PARCEL_BULK | Ombudspaket (B2C) |
| BRING:0332 | BUSINESS_PARCEL_BULK | Företagspaket (B2B) |
| BRING:PICKUP_PARCEL_BULK | PICKUP_PARCEL_BULK | Samma som 0342 |
| BRING:BUSINESS_PARCEL_BULK | BUSINESS_PARCEL_BULK | Samma som 0332 |

## Konfiguration

I `config.yaml`:

```yaml
bring:
  api_uid: "din@email.se"        # Mybring API UID (e-post)
  api_key: "din-api-nyckel"      # Mybring API Key
  customer_number: "12345"        # Bring-kundnummer
  test_mode: true                 # true = sandbox, false = produktion
```

Alternativt kan `customer_number_bring` sättas under `sender:`.

## API

- **Endpoint:** `POST https://api.bring.com/booking/api/create`
- **Autentisering:** `X-Mybring-API-Uid` + `X-Mybring-API-Key`
- **Testläge:** `X-Bring-Test-Indicator: true` (sandbox)

Dokumentation: [developer.bring.com](https://developer.bring.com/api/booking/)

## Flöde (paket till pall i Oslo)

1. **Mybring:** Skapa pall i portalen → få bulk-ID (t.ex. CS059102945NO)
2. **GARP:** Exportera XML med `BRING:0342` eller `BRING:0332`
3. **Bulk-ID:** Sätt i `config.yaml` (`consolidated_shipment_id`) eller i srvid: `BRING:0342:CS059102945NO`
4. Connector bokar paket via Booking API med `consolidatedShipmentId`
5. Etikett skrivs ut via Zebra, spårningsmail skickas
6. Paketen läggs på pallen, CMR/routing för pallen görs i Mybring

## Tester

```bash
pytest tests/test_bring_client.py tests/test_xml_parser.py -v
```
