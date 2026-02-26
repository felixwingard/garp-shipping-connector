# GARP Shipping Connector

Bevakar en mapp för GARP XML-filer, skapar fraktsedlar via DHL/Bring API, skriver ut etiketter och skickar spårningsmail till kunder.

**Stödda transportörer:** DHL (Sverige), Bring (Norge — Pickup Parcel Bulk, Business Parcel Bulk)

---

## Snabbstart (Windows)

### 1. Förutsättningar

- Python 3.9+
- GARP med Unifaun-export som droppar XML-filer

### 2. Installation

Kör installationsskriptet:

```
INSTALL.bat
```

Detta:
- Installerar Python-paket (requests, watchdog, pyyaml, pywin32, pystray, Pillow)
- Skapar mappar under `C:\GARP\`
- Kopierar `config.example.yaml` till `config.yaml` med DHL sandbox-nyckel
- Skapar genväg på skrivbordet

### 3. Konfiguration

Öppna `config\config.yaml` och kontrollera:

| Variabel | Beskrivning |
|----------|--------------|
| `paths.watch_dir` | Mapp där GARP droppar XML |
| `sender.*` | Ert företags uppgifter |
| `sender.customer_number_dhl` | Ert DHL-kundnummer |
| `dhl.base_url` | Sandbox eller produktion |
| `dhl.api_key` | Eller miljövariabel `DHL_API_KEY` |
| `bring.*` | Bring Norge (api_uid, api_key, customer_number, consolidated_shipment_id) |

**Miljövariabler** (rekommenderas för hemligheter):

```batch
set DHL_API_KEY=din-client-key-guid
set SENDER_EMAIL=order@ertforetag.se
set SMTP_USERNAME=er-e-post
set SMTP_PASSWORD=ert-lösenord
set SMTP_FROM_ADDRESS=order@ertforetag.se
```

### 4. DHL API

**Sandbox (test):**
- URL: `https://test-api.freight-logistics.dhl.com`
- Kundnummer: `111111` (DHL:s test-kundnummer)
- Begär test-nyckel hos DHL

**Produktion:**
- URL: `https://api.freight-logistics.dhl.com`
- Använd era riktiga API-uppgifter

### 5. Starta programmet

**Tray-läge** (rekommenderas):
```
python -m src
```
Eller dubbelklicka på skrivbordsgenvägen.

**Konsolläge** (för felsökning):
```
python -m src --console
```
Visar logg i terminalen.

### 6. Skrivare

Välj skrivare via **Högerklick på tray-ikonen → Inställningar**:
- **Etikettskrivare:** Zebra för fraktetiketter (PDF)
- **Dokumentskrivare:** A4 för fraktlistor (valfritt)

På utvecklingsdator (ej Windows) sparas etiketter som PDF-filer i `%TEMP%\garp-labels\`.

---

## GARP XML-format

XML-filerna ska följa Unifaun OnlineConnect-format. Tjänstekod (`srvid`) i formatet:

```
TRANSPORTÖR:PRODUKTKOD[:TILLÄGG]
```

**GARP/Unifaun:** Använd DHL:102 och DHL:103 direkt (ersätt AEX → DHL:102, ASPO → DHL:103).

**Exempel:**
- `DHL:102` — DHL Paket (B2B, företagspaket)
- `DHL:102:AVIS` — Med aviserings-e-post
- `DHL:103` — DHL ServicePoint (ombud, B2C)
- `DHL:210` — DHL Pall
- `BRING:0340` — Bring Pickup Parcel (Norge, enskilda paket)
- `BRING:0342` — Bring Pickup Parcel Bulk (pall till Oslo, kräver bulk-ID)
- `BRING:0330` — Bring Business Parcel (företagspaket)
- `BRING:0332` — Bring Business Parcel Bulk

Se `config.example.yaml` för full produktlista.

---

## Mappar

| Mapp | Innehåll |
|------|----------|
| `watch_dir` | GARP droppar XML här — programmet bevakar denna |
| `done_dir` | Klara filer flyttas hit |
| `error_dir` | Felfiler + `.error.txt` med felmeddelande |
| `label_cache_dir` | Backup av utskrivna etiketter (PDF) |
| `log_dir` | `garp_shipping.log`, `garp_shipping_errors.log` |

**Bilagor i kundmail:** DHL:s fraktlista bifogas automatiskt. Om GARP exporterar en följesedel-PDF med samma namn som ordernumret (t.ex. `107739-132888.pdf`), eller med samma namn som XML-filen (t.ex. `order.xml` → `order.pdf`), i samma mapp som XML:en, bifogas den också.

---

## Testa

**Enhetstester:**
```
pytest tests/ -v
```

**DHL API-test** — testar alla endpoints (för DHLs godkännande):

1. ServicePointLocator — hitta ombud
2. TransportInstruction — skapa sändning
3. Print — etikett + fraktlista
4. PickupRequest — boka upphämtning

Sätt `DHL_API_KEY` i miljö eller config.yaml. Kundnummer `111111` för sandbox.

```
# Alla produkter (102, 103, 109, 210, 211)
python scripts/test_dhl_products.py --all

# Endast 102
python scripts/test_dhl_products.py

# Flera produkter
python scripts/test_dhl_products.py --product 102 103 210

# Utan PickupRequest (snabbare)
python scripts/test_dhl_products.py --no-pickup
```

**Produkt 103 (ServicePoint B2C):** Ombud hämtas automatiskt via ServicePointLocator.

**Bring API-test:**
```
python scripts/test_bring.py              # PICKUP_PARCEL (0340)
python scripts/test_bring.py --product 0342   # Bulk (kräver bulk-ID i config)
```

---

## Bygg och installera på lagerdatorer

### Steg 1: Bygg på en Windows-dator

**Krav:** Python 3.9+ på Windows. Bygget måste köras på Windows (pywin32, PyInstaller). Om du utvecklar på Mac: använd en Windows-dator, VM eller nätverksdisk för att bygga.

1. Kopiera projektet till Windows-datorn (eller öppna från delad mapp)
2. Öppna projektmappen i CMD eller Utforskaren
2. Kör bygget:
   ```batch
   build\build.bat
   ```
3. Klart! Du hittar paketet i `dist\GARP-Shipping-Connector\`

### Steg 2: Skapa distributionspaket

1. Zippa hela mappen `dist\GARP-Shipping-Connector\`:
   - Högerklicka på mappen → Skicka till → Komprimerad (zippad) mapp
   - Döp till t.ex. `GARP-Shipping-Connector-v1.zip`

2. **Valfritt:** Lägg in en färdig `config.yaml` i zip-filen (under `config\`) om ni vill förkonfigurera med era DHL/Bring-nycklar. Annars skapas den från exempel vid installation.

### Steg 3: Kopiera till lagerdatorer

- Skicka zip-filen via e-post, nätverksmapp, USB eller liknande
- Packa upp på lagerdatorn (t.ex. till `C:\GARP-Shipping\` eller på skrivbordet)

### Steg 4: Installation på varje lagerdator

1. Öppna den uppackade mappen
2. Dubbelklicka på **Install-GARP-Shipping.bat**
3. Detta skapar:
   - Mappar: `C:\GARP\Unifaun\Outgoing`, Done, Error, Logs, Labels
   - Genväg på skrivbordet: "GARP Shipping"
   - `config\config.yaml` (om den inte finns)
4. Redigera `config\config.yaml` med era uppgifter:
   - DHL API-nyckel (eller miljövariabel `DHL_API_KEY`)
   - Bring: api_uid, api_key, customer_number
   - SMTP för spårningsmail
   - Mappar om GARP använder andra sökvägar
5. **Inställningar:** Starta programmet (dubbelklicka genvägen), högerklick på tray-ikonen → välj skrivare

### Innehåll i distributionspaket

| Fil | Beskrivning |
|-----|-------------|
| GarpShippingConnector.exe | Själva programmet (ingen Python krävs) |
| config/config.example.yaml | Mall för konfiguration |
| Install-GARP-Shipping.bat | Skapar mappar + genväg |

---

## Windows-tjänst (valfritt)

För att köra som bakgrundstjänst:

```
pyinstaller build/build.spec
GarpShippingConnector.exe install
GarpShippingConnector.exe start
```

Stoppa: `GarpShippingConnector.exe stop`  
Avinstallera: `GarpShippingConnector.exe remove`

---

## Felsökning

- **"Konfigurationsfil saknas"** — Kör `INSTALL.bat` eller kopiera `config.example.yaml` till `config.yaml`
- **"DHL API fel 401"** — Kontrollera att `DHL_API_KEY` är korrekt
- **"Bring: Ingen bring-konfiguration"** — Lägg till `bring:`-sektion i config.yaml (api_uid, api_key, customer_number)
- **"BRING:0342 kräver bulk-ID"** — Skapa pall i Mybring, kopiera ID, sätt i Inställningar eller config
- **Etiketter skrivs inte ut** — Välj skrivare i Inställningar
- **Loggar** — Finns i `paths.log_dir` (default `C:\GARP\Logs\`)

---

## Felsökning från Mac när buggar uppstår på Windows

Du utvecklar på Mac, buggar uppstår på lagerdatorer i Windows. Så här får du information tillbaka:

### 1. Loggfiler (enklast)

På lagerdatorn:
1. Högerklick på tray-ikonen → **Status**
2. Klicka **Öppna loggmapp** → Utforskaren öppnar `C:\GARP\Logs\`
3. Skicka `garp_shipping.log` och `garp_shipping_errors.log` till dig (e-post, Teams, etc.)

### 2. "Kopiera fel till urklipp"

När något gått fel:
1. Högerklick på tray-ikonen → **Status**
2. Klicka **Kopiera fel till urklipp**
3. Öppna Outlook/e-post → klistra in (Ctrl+V) → skicka till dig

Du får då de senaste 80 raderna från feloggen.

### 3. Debug-exe (för större problem)

Bygg en debug-version som visar logg i ett konsolfönster:

```batch
build\build_debug.bat
```

Det skapas `GarpShippingConnector-debug.exe`. Kör den på lagerdatorn när något strular — du ser då loggen live i fönstret. Kan skickas till lager vid behov.

### 4. Reproducera lokalt

Om du har tillgång till en Windows-VM eller en Windows-dator: kör `python -m src --console` för att se logg direkt i terminalen medan du testar.
