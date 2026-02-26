# Bring-implementation

Integration med Bring Booking API + Bulksplit API för sändningar till Norge.

## Produkter

| srvid i GARP | Bring API-kod | Beskrivning |
|--------------|---------------|-------------|
| BRING:0342 | PICKUP_PARCEL_BULK | Ombudspaket (B2C) |
| BRING:0332 | BUSINESS_PARCEL_BULK | Företagspaket (B2B) |
| BRING:PICKUP_PARCEL_BULK | PICKUP_PARCEL_BULK | Samma som 0342 |
| BRING:BUSINESS_PARCEL_BULK | BUSINESS_PARCEL_BULK | Samma som 0332 |

## Social kontroll (1082)

Tilläggstjänsten "Sosial kontroll" (1082) är för Pickup Parcel — leverans till ombud/upphämtningsställen.
Stöds för 0340 (Pickup Parcel) och 0342 (Pickup Parcel Bulk), inte för 0332 (Business Parcel Bulk).

Ange via srvid: `BRING:0340:SOCIAL` eller `BRING:0342:SOCIAL`

## Begränsade kvantiteter (LQ / ADR)

För sändningar med begränsad mängd farligt gods, lägg till `LQ` i addon:

| srvid i GARP | Effekt |
|--------------|--------|
| BRING:0332:LQ | Business Parcel Bulk + begränsad mängd (additionalService 0003) |
| BRING:0332:0003 | Samma som LQ |
| BRING:0332:CS123:LQ | Bulk-ID CS123 + begränsad mängd |

Obs: Multimodal Dangerous Goods Form måste skickas till Bring före transport.

## Konfiguration

I `config.yaml`:

```yaml
bring:
  api_uid: "din@email.se"        # Mybring API UID (e-post)
  api_key: "din-api-nyckel"      # Mybring API Key
  customer_number: "12345"        # Bring-kundnummer
  consolidated_shipment_id: ""   # Fylls via "Bring Bulk" i tray
  test_mode: true                 # true = sandbox, false = produktion
```

## Flöde (paket till pall i Norge)

1. **Reservera bulk-ID:** Tray → "Bring Bulk (Norge)" → välj terminal → Reservera nummer
2. **GARP:** Exportera XML med `BRING:0332` (Business Parcel Bulk)
3. Connector bokar paket via Booking API med det reserverade bulk-ID:t
4. Etikett skrivs ut via Zebra, spårningsmail skickas
5. **Slutför pall:** Bring Bulk-fönstret → ange totalvikt → Registrera pall → CMR/waybill

## API:er

- **Booking API:** `POST https://api.bring.com/booking/api/create` — skapa paketbokningar
- **Bulksplit API:** `https://api.bring.com/bulksplit/v1` — reservera bulk-ID, registrera pall
  - `POST /bulk-shipment-ids` — reservera nummer
  - `GET /terminals` — lista terminaler
  - `POST /bulk-shipments/{id}` — registrera pall (kolli, vikt) → CMR

## Tester

```bash
pytest tests/test_bring_client.py tests/test_xml_parser.py -v
```
