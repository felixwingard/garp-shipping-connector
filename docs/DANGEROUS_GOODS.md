# Farligt gods (ADR) och deklarationer

## Översikt

Connector stöder farligt gods på två nivåer:

- **LQ (begränsad mängd):** Endast flagga — `additionalServices.dangerousGoods` eller LQ-tjänst (Bring 0003)
- **Full ADR:** UN-nummer, ADR-klass, packningsgrupp etc. — kräver sidecar-fil med detaljer

GARP/Unifaun exporterar inte farligt gods-data i XML. Information måste anges vid bokning via sidecar-fil eller via dialog i tray-appen.

---

## LQ (begränsad mängd)

### DHL

**DHL Paket (102, 103) stöder inte farligt gods.** Enligt DHL Produktmanual v5.23 accepteras inte farligt gods (inkl. LQ) i paketprodukter. `DHL:102:LQ` och `DHL:103:DG` blockeras med felmeddelande.

**DHL Freight** (godstransport) stöder farligt gods enligt ADR. Använd t.ex.:
- **DHL:210:LQ** — Pall (EUR-pall)
- **DHL:211:LQ** — Styckegods
- **DHL:202** / **DHL:205** — Euroconnect/Euroline (utrikes) — verifiera mot produktmanual

För full ADR krävs sidecar-fil (`*_dg.json`) eller dialog med UN-nummer, ADR-klass etc. Kontakta DHL för ADR-krav (säkerhetsrådgivare, utbildning, deklaration).

### Bring

**GARP workaround:** Använd volume-fältet i containern. `volume > 0` (t.ex. 4 för 4 kg LQ) aktiverar LQ automatiskt. `volume = 0` = ej LQ. Ett leveranssätt (BRING:0332) räcker.

Alternativt: `BRING:0332:LQ` eller `BRING:0332:0003` i srvid.

**Obs:** Multimodal Dangerous Goods Form måste skickas till Bring före transport (manuellt).

---

## Full ADR med sidecar-fil

För sändningar som kräver UN-nummer, ADR-klass m.m. skapa en JSON-fil bredvid XML-filen med samma filnamn + suffix `_dg.json`:

**Exempel:** `20260227_091140_W66352-133291.xml` → `20260227_091140_W66352-133291_dg.json`

**Format:**

```json
{
  "unNumber": "1987",
  "adrClass": "3",
  "packingGroup": "II",
  "technicalName": "Alcohols, n.o.s.",
  "flashPoint": "23"
}
```

| Fält | Obligatorisk | Beskrivning |
|------|-------------|-------------|
| unNumber | Ja | UN-nummer (t.ex. 1987) |
| adrClass | Nej | ADR-klass 1–9 |
| packingGroup | Nej | I, II eller III |
| technicalName | Nej | Teknisk beteckning |
| flashPoint | Nej | Flashpunkt |

Connector letar automatiskt efter `*_dg.json` i samma mapp som XML:n när srvid innehåller DG/LQ/DANGER. Om filen finns och har giltigt unNumber används data för full ADR-payload.

### Dialog (tray-appen)

När en DHL-sändning har DG-addon men saknar sidecar-fil visas en dialog "Ange farligt gods — order X". Fyll i UN-nummer (obligatoriskt), ADR-klass, packningsgrupp, teknisk beteckning och flashpoint. Du kan välja att spara till sidecar-fil för framtida användning. Vid avbryt flyttas filen till Error.

---

## Deklarationsdokument

### ADR-godsdeklaration (DHL Freight)

Connector **genererar automatiskt** ADR-godsdeklaration som PDF vid farligt gods med DHL Pall (210), Stycke (211), Euroconnect (202) eller Euroline (205). Dokumentet skrivs ut till dokumentskrivaren (A4) och följer MSB/ADR 5.4.1. Avsändaren signerar utskriften manuellt.

Konfiguration: `printers.print_dg_declaration: true` (default). Sätt till `false` för att stänga av.

### Övriga dokument

- **Multimodal DG Form (Bring):** Måste skickas till Bring före transport enligt deras rutiner.
- **DHL paket (102/103):** Stöder inte farligt gods — se avsnitt LQ ovan.
