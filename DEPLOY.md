# Deployment till lagerdatorn

## 1. Hämta koden

**Om ni har Git på lagerdatorn:**
```
git clone <er-repo-url>
cd garp-shipping-connector
```

**Alternativ (USB/OneDrive/etc):** Zippa projektmappen (utan `config/config.yaml`) och kopiera till lagerdatorn.

## 2. Installation

```
INSTALL.bat
```

## 3. Skapa config med era uppgifter

Kopiera `config/config.example.yaml` till `config/config.yaml` och fyll i:

- **paths:** watch_dir, done_dir, error_dir, label_cache_dir, log_dir
- **sender:** era företagsuppgifter + DHL-kundnummer
- **dhl:** base_url, api_key
- **smtp:** username (hela e-postadressen), password, from_address
- **printers:** label_printer_name (Zebra), document_printer_name (A4)

⚠️ **config.yaml committas inte till Git** — den skapas lokalt på varje dator med era hemliga uppgifter.

## 4. Starta

```
python -m src
```

eller dubbelklicka på skrivbordsgenvägen.
