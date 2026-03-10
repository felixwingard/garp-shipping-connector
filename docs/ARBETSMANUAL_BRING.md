# Arbetsmanual: Skicka till Norge med Bring

Steg-för-steg från packning till färdig pall.

---

## Innan du börjar (en gång per vecka / per pall)

### 1. Reservera bulk-nummer

1. Högerklicka på **GARP Shipping Connector** i systemfältet (tray-ikonen)
2. Välj **"Bring Bulk (Norge)"**
3. Välj terminal i listan (t.ex. **Oslo**)
4. Klicka **"Reservera nummer"**
5. Ett bulk-ID visas (t.ex. `CL311693164NO`) — det sparas automatiskt

> Du behöver bara göra detta **en gång** per pall/vecka. Alla paket som bokas efteråt hamnar på samma pall.

---

## Packa och skicka ordrar

### 2. Skapa sändning i GARP

1. Öppna ordern i GARP
2. Välj rätt Bring-tjänst som **srvid**:

| srvid | Typ | Används för |
|-------|-----|-------------|
| `BRING:0332` | Business Parcel Bulk | Företagsleverans (B2B) |
| `BRING:0342` | Pickup Parcel Bulk | Ombud/utlämningsställe (B2C) |

3. Exportera sändningen (XML hamnar i Outgoing-mappen)

#### LQ — Farligt gods (begränsad mängd)

Om paketet innehåller LQ-gods finns två sätt:
- **Volume-fältet i GARP:** Sätt volym till ett värde > 0 (t.ex. `4.00`) — systemet lägger automatiskt till LQ-märkning
- **Srvid:** Skriv `BRING:0332:LQ` istället för `BRING:0332`

> OBS: Den fysiska Multimodal Dangerous Goods-blanketten måste skickas till Bring separat före transport.

### 3. Etiketten skrivs ut automatiskt

När XML-filen hamnar i Outgoing-mappen händer detta automatiskt:
1. Systemet läser ordern och bokar paketet hos Bring
2. **Etiketten skrivs ut på Zebra-skrivaren** (ZDesigner GK420t)
3. Spårningsmail skickas till kunden (om e-post finns på ordern)
4. XML-filen flyttas till Done-mappen

**Klistra etiketten på paketet och lägg det på pallen.**

### 4. Upprepa för alla ordrar

Upprepa steg 2–3 för varje order. Alla paket hamnar på samma pall (samma bulk-ID).

> Både 0332 (företag) och 0342 (ombud) kan packas på **samma pall** — kryssa i "Blandad pall" vid registrering.

---

## Avsluta pallen

### 5. Registrera pall — hämta CMR

När alla paket är packade och klara för upphämtning:

1. Öppna **"Bring Bulk (Norge)"** i tray-menyn
2. Kontrollera att **antal kolli** och **totalvikt** stämmer (räknas automatiskt — kan ändras manuellt)
3. Ange **antal fakturakopior** (standard 3 för SE→NO)
4. Om du har blandade tjänster (0332 + 0342) på pallen: kryssa i **"Blandad pall"**
5. Klicka **"Registrera pall → hämta CMR"**
6. **CMR/waybill** och **routing labels** öppnas i webbläsaren — skriv ut dem
7. Lägg CMR-dokumenten med pallen

### 6. Avsluta bulk

1. I Bring Bulk-fönstret, klicka **"Avsluta bulk (starta nytt nästa vecka)"**
2. En Excel-backup sparas automatiskt i `bulk_exports/`
3. Bulk-ID:t nollställs — nästa gång du skickar reserverar du ett nytt

---

## Sammanfattning — Checklista

| # | Steg | Var |
|---|------|-----|
| 1 | Reservera bulk-nummer | Tray → Bring Bulk |
| 2 | Skapa sändning per order i GARP | GARP (srvid: BRING:0332 / 0342) |
| 3 | Etikett skrivs ut automatiskt → klistra på paketet | Zebra-skrivare |
| 4 | Upprepa för alla ordrar | — |
| 5 | Registrera pall → skriv ut CMR | Tray → Bring Bulk |
| 6 | Avsluta bulk | Tray → Bring Bulk |

---

## Felsökning

| Problem | Lösning |
|---------|---------|
| "kräver bulk-ID" | Du har inte reserverat bulk-nummer — gör steg 1 |
| Etikett skrivs inte ut | Kontrollera att Zebra-skrivaren (ZDesigner GK420t) är på och ansluten |
| Inga terminaler i listan | Kontrollera internetanslutning och API-nycklar i inställningar |
| Testetiketter istället för skarpa | Ändra `test_mode` till `false` under Bring i config.yaml |
| Fel postnummer / stad | Kontrollera att norskt postnummer är 4 siffror i GARP |
