# DHL PriceQuote — Exempelanrop till DHL support

Ett par exempelanrop att skicka till DHL (t.ex. se.dbi@dhl.com) för felsökning.

**Med riktiga uppgifter** (vi är okej med att DHL ser dem):
```bash
python3 scripts/dump_pricequote_request.py --product 202 --to-zip 74320 --to-country PL --halvpall --no-mask > pricequote_request.json
```
Skicka filen till DHL. Committa inte `pricequote_request.json` till git.

---

## 1. Avtalspris (quoteforprice)

**Endpoint:** `POST https://api.freight-logistics.dhl.com/pricequoteapi/v1/pricequote/quoteforprice`

**Headers:**
```
Content-Type: application/json
Accept: application/json
client-key: <ert-GUID-nyckel-från-DHL>
```

**Request body:**
```json
{
  "shipment": {
    "dhlProductCode": "DHLEuroconnect",
    "totalNumberOfPieces": 1,
    "totalWeight": 40,
    "totalVolume": 0.48,
    "totalLoadingMeters": 0.4,
    "totalPalletPlaces": 0.5,
    "numberOfEURPallets": 0,
    "numberOfFullPallets": 0,
    "numberOfHalfPallets": 1,
    "goodsValue": "",
    "payerCode": "DDP",
    "importExport": "E",
    "piece": [
      {
        "numberOfPieces": 1,
        "weight": 40,
        "volume": 0.48,
        "loadingMeters": 0.4,
        "palletPlaces": 0.5,
        "width": 80,
        "height": 75,
        "length": 60,
        "stackable": false,
        "packageType": "702"
      }
    ],
    "parties": [
      {
        "id": "<ert-kundnummer-utrikes>",
        "name": "Ernst P AB",
        "type": "Consignor",
        "address": {
          "street": "Möbelgatan 5",
          "streetNumber": "",
          "cityName": "Mölndal",
          "postalCode": "43133",
          "countryCode": "SE"
        }
      },
      {
        "id": "",
        "name": "Mottagare",
        "type": "Consignee",
        "address": {
          "street": "Adress 1",
          "streetNumber": "",
          "cityName": "Stockholm",
          "postalCode": "11122",
          "countryCode": "SE"
        }
      }
    ],
    "additionalServices": {
      "nonStackable": true
    }
  },
  "ownSurCharge": {"percentage": 0, "value": 0},
  "eid": {
    "userName": "<ert-eID-user>",
    "password": "<ert-eID-lösenord>"
  }
}
```

---

## 2. Listpris (quoteforgrossprice)

**Endpoint:** `POST https://api.freight-logistics.dhl.com/pricequoteapi/v1/pricequote/quoteforgrossprice`

**Headers:** Samma som ovan (client-key).

**Request body:** Samma `shipment`-objekt som ovan, men **utan** `eid`:
```json
{
  "shipment": { ... },
  "ownSurCharge": {"percentage": 0, "value": 0}
}
```

---

## 3. Halvpall till Polen (202) — det som blev konstigt

Scenario: 1 halvpall, 40 kg, 60×80×75 cm, ej stapelbar, till postnummer 74320 (Polen).

```json
{
  "shipment": {
    "dhlProductCode": "DHLEuroconnect",
    "totalNumberOfPieces": 1,
    "totalWeight": 40,
    "totalVolume": 0.36,
    "totalLoadingMeters": 0.2,
    "totalPalletPlaces": 0.5,
    "numberOfEURPallets": 0,
    "numberOfFullPallets": 0,
    "numberOfHalfPallets": 1,
    "goodsValue": "",
    "payerCode": "DDP",
    "importExport": "E",
    "piece": [
      {
        "numberOfPieces": 1,
        "weight": 40,
        "volume": 0.36,
        "loadingMeters": 0.2,
        "palletPlaces": 0.5,
        "width": 80,
        "height": 75,
        "length": 60,
        "stackable": false,
        "packageType": "702"
      }
    ],
    "parties": [
      {
        "id": "<ert-utrikes-nr>",
        "name": "Ernst P AB",
        "type": "Consignor",
        "address": {
          "street": "Möbelgatan 5",
          "streetNumber": "",
          "cityName": "Mölndal",
          "postalCode": "43133",
          "countryCode": "SE"
        }
      },
      {
        "id": "",
        "name": "Mottagare",
        "type": "Consignee",
        "address": {
          "street": "Adress 1",
          "streetNumber": "",
          "cityName": "Mottagarstad",
          "postalCode": "74320",
          "countryCode": "PL"
        }
      }
    ],
    "additionalServices": {
      "nonStackable": true
    }
  },
  "ownSurCharge": {"percentage": 0, "value": 0},
  "eid": {
    "userName": "<ert-eID>",
    "password": "<ert-eID>"
  }
}
```

---

## 4. cURL-exempel (ersätt placeholders)

```bash
# Avtalspris (quoteforprice) — halvpall till Polen
curl -X POST "https://api.freight-logistics.dhl.com/pricequoteapi/v1/pricequote/quoteforprice" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -H "client-key: ERT_CLIENT_KEY_GUID" \
  -d '{
    "shipment": {
      "dhlProductCode": "DHLEuroconnect",
      "totalNumberOfPieces": 1,
      "totalWeight": 40,
      "totalVolume": 0.36,
      "totalLoadingMeters": 0.2,
      "totalPalletPlaces": 0.5,
      "numberOfEURPallets": 0,
      "numberOfFullPallets": 0,
      "numberOfHalfPallets": 1,
      "goodsValue": "",
      "payerCode": "DDP",
      "importExport": "E",
      "piece": [{
        "numberOfPieces": 1,
        "weight": 40,
        "volume": 0.36,
        "loadingMeters": 0.2,
        "palletPlaces": 0.5,
        "width": 80,
        "height": 75,
        "length": 60,
        "stackable": false,
        "packageType": "702"
      }],
      "parties": [
        {"id": "ERT_KUNDNR", "name": "Ernst P AB", "type": "Consignor", "address": {"street": "Möbelgatan 5", "streetNumber": "", "cityName": "Mölndal", "postalCode": "43133", "countryCode": "SE"}},
        {"id": "", "name": "Mottagare", "type": "Consignee", "address": {"street": "Adress", "streetNumber": "", "cityName": "Stad", "postalCode": "74320", "countryCode": "PL"}}
      ],
      "additionalServices": {"nonStackable": true}
    },
    "ownSurCharge": {"percentage": 0, "value": 0},
    "eid": {"userName": "ERT_EID", "password": "ERT_EID_PASS"}
  }'
```

---

## Vad som hände (konstigt resultat igår)

Beskriv gärna för DHL vad ni såg — t.ex.:
- Felmeddelande (om något)
- Förväntat vs faktiskt pris
- Om quoteforgrossprice fungerade men quoteforprice inte (eller vice versa)
