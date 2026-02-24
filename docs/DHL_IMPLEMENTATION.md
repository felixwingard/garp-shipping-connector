# DHL API Farm — Implementationsdokumentation

Detta dokument beskriver GARP Shipping Connectors DHL-integration för godkännande av produktionsnyckel.

## Översikt

Vi använder **en** applikation i DHL API Farm för GARP Shipping Connector. Programmet:

1. Bevakar GARP XML-filer
2. För produkt 103 (ServicePoint): hämtar närmaste ombud via **ServicePointLocator API**
3. Skapar sändningar via **TransportInstruction API**
4. Hämtar etiketter via **Print API**
5. Bokar upphämtning via **PickupRequest API** (när `pickupbooking=YES` i XML)

## Produkter vi stödjer

| Produkt | Namn | TransportInstruction | Print | PickupRequest |
|---------|------|----------------------|-------|---------------|
| 102 | DHL Paket (B2B) | ✅ | ✅ | ✅ |
| 103 | DHL ServicePoint B2C | ✅ | ✅ | ✅* |
| 104 | DHL ServicePoint C2B (retur) | ❌ stöds ej | | |
| 109 | DHL Parcel Connect | ✅ | ✅ | ✅ |
| 210 | DHL Pall | ✅ | ✅ | ✅ |
| 211 | DHL Stycke | ✅ | ✅ | ✅ |

\* 103: AccessPoint hämtas automatiskt via ServicePointLocator (närmaste ombud).

## PickupRequest — full payload (IFTMBF)

DHL kräver **full pickup instruction** med samma struktur som TransportInstruction.
Vi skickar inte längre bara `transportInstructionId` + `pickupDate`.

Payload innehåller:
- `id` — transport instruction id
- `pickupDate` — önskat upphämtningsdatum
- `pickupInstruction` — instruktion till chaufför
- `parties` — Consignor, Consignee (och AccessPoint för 103/104)
- `pieces` — med DHL:s tilldelade barcode-id
- `totalWeight`, `totalVolume`, `totalNumberOfPieces`
- `payerCode`, `additionalServices`, etc.

Ref: [PickupRequest API](https://dhlpaket.se/dashboard/services/api-farm/pickuprequest/)

## Tester

### Enhetstester (pytest)

```bash
pytest tests/ -v
```

Täcker: TransportInstruction payload-bygge, Print API-svarsparsning, PickupRequest full payload, postnummer-rensning, etc.

### Produkttest mot sandbox

```bash
# Full test för DHL Paket (102)
python scripts/test_dhl_products.py

# Flera produkter
python scripts/test_dhl_products.py --product 102 210 211

# Utan PickupRequest
python scripts/test_dhl_products.py --no-pickup
```

Kör TransportInstruction → Print → PickupRequest för varje angiven produkt.

## Svar på DHL:s frågor

### "Ska ni använda alla tre applikationer?"

Vi använder **en** applikation: GARP Shipping Connector. Den hanterar alla produkter (102, 103, 104, 109, 210, 211) via samma API-nyckel.

### "Kompletta tester per produkt"

Vi har implementerat:
- TransportInstruction API — full payload med parties, pieces, additionalServices
- Print API — printdocuments med cachad TI-data
- PickupRequest API — full IFTMBF-payload (tidigare fel: skickade bara id+datum, nu komplett)

Kör `scripts/test_dhl_products.py` mot sandbox för att verifiera.

### "Pickup requests har genererat fel"

Det berodde på ofullständig payload. Vi skickar nu full pickup instruction enligt DHL-exemplet.

## Referenser

- [APIs per DHL Product](https://dhlpaket.se/dashboard/services/uncategorized/api-farm-2/)
- [Getting started](https://dhlpaket.se/dashboard/services/api-farm/get-started/)
- [PickupRequest API](https://dhlpaket.se/dashboard/services/api-farm/pickuprequest/)
- Postman-kollektioner (länkade på Getting started-sidan)
