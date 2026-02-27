# Flöde: Skicka till Norge (Bring)

Beskrivning av hela flödet när ni skickar paket till Norge via Bring Business Parcel Bulk (0332) eller Pickup Parcel Bulk (0342).

---

## Översikt

```
┌─────────────┐    ┌──────────────┐    ┌─────────────────┐    ┌──────────────┐
│ Tray:       │    │ GARP/Unifaun │    │ Connector       │    │ Bring        │
│ Bring Bulk  │───▶│ XML-export   │───▶│ XML → API       │───▶│ Etikett      │
│ Reservera   │    │ BRING:0332   │    │ Etikett → Zebra │    │ Kundmail     │
└─────────────┘    └──────────────┘    └─────────────────┘    └──────────────┘
       │                    │                    │
       │                    │                    └── Slutför pall (Tray)
       │                    └── watch_dir (Outgoing)
       └── consolidated_shipment_id → config.yaml
```

---

## Steg-för-steg

### 1. Reservera bulk-ID (före packning)

1. Öppna **GARP Shipping Connector** (tray-ikonen i systemfältet)
2. Klicka **"Bring Bulk (Norge)"**
3. Välj terminal (t.ex. **Oslo**)
4. Klicka **"Reservera nummer"**
5. Bulk-ID sparas automatiskt i `config.yaml` (t.ex. `CL311693164NO`)

**Alternativ:** Skapa pall manuellt i Mybring och ange bulk-ID i Inställningar → Bring.

---

### 2. GARP exporterar XML

1. I GARP/Unifaun, skapa sändning till Norge
2. Välj tjänst: **BRING:0332** (Business Parcel Bulk) eller **BRING:0342** (Pickup Parcel Bulk)
3. Exportera till **Outgoing-mappen** (konfigurerad som `paths.watch_dir`)

**Exempel srvid i GARP:**
- `BRING:0332` — Företagspaket, pall till Oslo
- `BRING:0342` — Ombudspaket, pall till Oslo
- `BRING:0332:LQ` — Med begränsad mängd farligt gods (LQ)

---

### 3. Connector bearbetar automatiskt

Mappbevakaren ser den nya XML-filen och kör:

1. **Parsa XML** — läser order, mottagare, produkt
2. **Bring Booking API** — boka paket med bulk-ID → får etikett-PDF
3. **Utskrift** — skickar etikett till Zebra (ZDesigner GK420t)
4. **Kundmail** — skickar spårningslänk (om `enot` är aktiv)
5. **Flytta** — XML tas bort från Outgoing (klar)

---

### 4. Slutför pall (när alla paket är packade)

1. Öppna **"Bring Bulk (Norge)"** i tray
2. Kontrollera att antal paket stämmer (uppdateras automatiskt)
3. Ange **totalvikt** (kg) för pallen
4. Klicka **"Registrera pall"**
5. Bring returnerar CMR/waybill — pallen är bokad för transport

Efter registrering töms bulk-ID så att nästa vecka kan starta ny pall.

---

## Konfiguration

| Nyckel | Beskrivning |
|--------|-------------|
| `bring.api_uid` | Mybring API UID (e-post) |
| `bring.api_key` | Mybring API Key |
| `bring.customer_number` | Bring-kundnummer |
| `bring.consolidated_shipment_id` | Fylls via Tray (Bring Bulk) |
| `bring.test_mode` | `true` = sandbox, `false` = produktion |
| `paths.watch_dir` | GARP droppar XML här |
| `printers.label_printer_name` | Zebra för etiketter |

---

## Produkter

| srvid | Bring API | Beskrivning |
|-------|-----------|-------------|
| BRING:0332 | BUSINESS_PARCEL_BULK | Företagspaket (B2B), pall |
| BRING:0342 | PICKUP_PARCEL_BULK | Ombudspaket (B2C), pall |
| BRING:0330 | BUSINESS_PARCEL | Enstaka företagspaket (list-avtal) |
| BRING:0340 | PICKUP_PARCEL | Enstaka ombudspaket (list-avtal) |

**0332 och 0342 kräver bulk-ID.** 0330 och 0340 fungerar utan pall.

---

## Felsökning

| Fel | Lösning |
|-----|---------|
| "kräver bulk-ID" | Reservera bulk i Tray → Bring Bulk |
| Inga terminaler | Kontrollera customer_number och API-nycklar |
| Etikett skrivs inte ut | Kontrollera `label_printer_name` i config |
| Test vs prod | `test_mode: true` = sandbox, `false` = produktion |

---

## API-flöde (intern)

1. **Bulksplit: reserve_bulk_id** — vid klick "Reservera nummer" i Tray
2. **Booking: create** — per XML/sändning (använder bulk-ID)
3. **Bulksplit: register_bulk_shipment** — vid "Registrera pall"
