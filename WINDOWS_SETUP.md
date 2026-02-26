# Steg-för-steg: GARP Shipping Connector på Windows

---

## Steg 1: Packa upp ZIP-filen

1. Öppna den nedladdade `garp-shipping-connector-main.zip`
2. **Extrahera** till t.ex. `C:\GARP-Shipping\` — du ska få mappen `C:\GARP-Shipping\garp-shipping-connector-main\`
3. Öppna mappen — du ska se filer som `INSTALL.bat`, `config\`, `src\`, `scripts\` m.fl.

---

## Steg 2: Installera Python (om du inte har det)

1. Gå till https://www.python.org/downloads/
2. Ladda ner Python 3.9 eller senare
3. **Viktigt:** Kryssa i **"Add Python to PATH"** vid installationen
4. Starta om datorn om Python inte fanns från början

---

## Steg 3: Kör installationen

1. Öppna Utforskaren och gå till projektmappen (t.ex. `C:\GARP-Shipping`)
2. **Dubbelklicka på `INSTALL.bat`**
3. Vänta tills det står "INSTALLATIONEN KLAR!"
4. Tryck på valfri tangent för att stänga

Detta har nu:
- Installerat Python-paket
- Skapat mappar under `C:\GARP\` (Outgoing, Done, Error, Logs, Labels)
- Kopierat `config.example.yaml` till `config.yaml`
- Skapat genväg "GARP Shipping" på skrivbordet

---

## Steg 4: Fyll i config.yaml

1. Öppna `config\config.yaml` i Notepad eller annan editor
2. Fyll i:

| Rad/avsnitt | Vad du skriver |
|-------------|----------------|
| `paths.watch_dir` | `C:\GARP\Unifaun\Outgoing` (ska matcha var GARP droppar filer) |
| `sender.name` | Ernst P AB |
| `sender.address1`, `zipcode`, `city`, `country` | Era uppgifter |
| `sender.email` | T.ex. order@ernstp.se |
| `sender.customer_number_dhl` | Er DHL-kundnummer |
| `sender.customer_number_dhl_international` | Er DHL utrikes-nummer |
| `dhl.base_url` | `https://api.freight-logistics.dhl.com` (produktion) |
| `dhl.api_key` | Er DHL client-key (GUID) |
| `dhl.eid_username` | Er eID-användare (från DHL, för avtalspris) |
| `dhl.eid_password` | Er eID-lösenord |
| `smtp.username` | E-postadress (t.ex. no-reply@ernstp.se) |
| `smtp.password` | E-postlösenord |
| `smtp.from_address` | Samma som username |
| `printers.label_printer_name` | Namnet på er Zebra-skrivare |
| `printers.document_printer_name` | A4-skrivare för fraktlistor (eller låt stå tomt) |

3. **Spara** filen

---

## Steg 5: Kontrollera att GARP-mapparna finns

Öppna Utforskaren och kolla att dessa mappar finns:

- `C:\GARP\Unifaun\Outgoing` — här droppar GARP sina .txt-filer
- `C:\GARP\Unifaun\Done` — klara filer hamnar här
- `C:\GARP\Unifaun\Error` — fel hamnar här

Om GARP använder en annan mapp (t.ex. via RDS/tsclient), justera `paths.watch_dir` i config så den pekar dit.

---

## Steg 6: SumatraPDF (för utskrift)

Connectorn skriver ut PDF-etiketter via SumatraPDF. Lägg `SumatraPDF.exe` i projektmappen och sätt sökvägen i config.

1. Ladda ner: https://www.sumatrapdfreader.org → 64-bit Portable → packa upp
2. Kopiera `SumatraPDF.exe` till `C:\GARP-Shipping\garp-shipping-connector-main\` (samma mapp som INSTALL.bat)
3. Öppna `config\config.yaml` och lägg till under `printers:`:
   ```yaml
   sumatra_exe: "C:\\GARP-Shipping\\garp-shipping-connector-main\\SumatraPDF.exe"
   ```
   Då hittas SumatraPDF alltid oavsett var programmet startas från.

---

## Steg 7: Starta programmet

**Alternativ A:** Dubbelklicka på "GARP Shipping" på skrivbordet

**Alternativ B:**
1. Öppna Kommandotolken eller PowerShell
2. Skriv: `cd C:\GARP-Shipping` (eller din projektmapp)
3. Skriv: `python -m src`

Du ska då se en grön cirkel i systemfältet (nere vid klockan).

---

## Steg 8: Välj skrivare

1. **Högerklicka** på den gröna cirkeln i systemfältet
2. Klicka **Inställningar**
3. Välj **Etikettskrivare** (Zebra)
4. Välj **Dokumentskrivare** (A4, om ni vill skriva ut fraktlistor)
5. Stäng

---

## Steg 9: Testa (valfritt)

För att se loggen i konsollen (bra vid felsökning):

```
cd C:\GARP-Shipping
python -m src --console
```

För att testa en sändning utan GARP:

```
python scripts\test_label.py --send-email
```

(Lägg en XML/testfil i `test_data\watch\` först, eller använd fixtures)

---

## Felsökning

| Problem | Lösning |
|--------|---------|
| "Python hittades inte" | Installera Python med "Add to PATH" |
| "Modulen X hittades inte" | Kör `INSTALL.bat` igen |
| Inget händer när fil droppas | Kolla att `watch_dir` pekar rätt. GARP skriver .txt — stöds nu. |
| Etikett skrivs inte ut | 1) Lägg SumatraPDF.exe i C:\GARP-Shipping\garp-shipping-connector-main\ och sätt sumatra_exe i config (se Steg 6). 2) Högerklick tray → Inställningar → välj rätt Zebra (namnet måste matcha exakt). |
| Mail skickas inte | Kontrollera smtp.username, smtp.password i config |
