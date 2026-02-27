"""Parser för GARP:s XML-exportfiler.

GARP exporterar XML i ett format baserat på Unifaun OnlineConnect.
Tjänstekoder (srvid) har uppdaterats till formatet TRANSPORTÖR:PRODUKTKOD[:TILLÄGG]
istället för Unifauns egna koder.

Hanterar kända GARP-exportproblem:
- Orfana </booking>-tagg innan </service> (saknad öppningstag) → tas bort.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import logging
from pathlib import Path
from typing import Optional

from .models import (
    Shipment, Receiver, Container, ServiceInfo, BookingInfo,
    Notification, CarrierType,
)

logger = logging.getLogger(__name__)


class GarpXMLParser:
    """Parsar XML-filer exporterade från GARP."""

    def parse_file(self, filepath: Path) -> list[Shipment]:
        """Parsar en XML-fil och returnerar lista med Shipment-objekt.

        En XML-fil kan innehålla flera shipments.
        Kodning: ISO-8859-1 (hanteras av ElementTree via XML-deklarationen).
        """
        # Använd deklarationens encoding, fallback UTF-8/ISO-8859-1
        raw_bytes = filepath.read_bytes()
        enc_match = re.search(rb'encoding\s*=\s*["\']([^"\']+)["\']', raw_bytes[:500])
        encoding = enc_match.group(1).decode("ascii", errors="ignore").upper() if enc_match else "UTF-8"
        if encoding == "ISO-8859-1":
            raw = raw_bytes.decode("iso-8859-1", errors="replace")
        else:
            raw = raw_bytes.decode("utf-8", errors="replace")
        raw = self._fix_garp_xml(raw)
        root = ET.fromstring(raw)
        # Receiver kan finnas på root-nivå (delad av alla shipments)
        receiver_elem = root.find("receiver")
        shared_receiver = self._parse_receiver(receiver_elem) if receiver_elem is not None else None

        shipments = []
        for ship_elem in root.findall("shipment"):
            # Varje shipment kan ha egen receiver, annars använd delad
            ship_recv_elem = ship_elem.find("receiver")
            if ship_recv_elem is not None:
                receiver = self._parse_receiver(ship_recv_elem)
            else:
                receiver = shared_receiver

            shipment = self._parse_shipment(ship_elem, receiver)
            shipments.append(shipment)

        logger.info(f"Parsade {len(shipments)} sändning(ar) från {filepath.name}")
        return shipments

    def parse_string(self, xml_string: str) -> list[Shipment]:
        """Parsar XML från en sträng (användbart för tester)."""
        xml_string = self._fix_garp_xml(xml_string)
        root = ET.fromstring(xml_string)

        receiver_elem = root.find("receiver")
        shared_receiver = self._parse_receiver(receiver_elem) if receiver_elem is not None else None

        shipments = []
        for ship_elem in root.findall("shipment"):
            ship_recv_elem = ship_elem.find("receiver")
            if ship_recv_elem is not None:
                receiver = self._parse_receiver(ship_recv_elem)
            else:
                receiver = shared_receiver

            shipment = self._parse_shipment(ship_elem, receiver)
            shipments.append(shipment)

        return shipments

    def _parse_receiver(self, elem: ET.Element) -> Receiver:
        vals = self._extract_vals(elem)
        addr1 = vals.get("address1", "").strip()
        addr2 = vals.get("address2", "").strip()
        # GARP kan lägga hela gatan i address2 — DHL använder bara address1 som street
        if not addr1 and addr2:
            addr1, addr2 = addr2, ""  # Flytta address2 till address1
        elif addr1 and addr2:
            addr1 = f"{addr1}, {addr2}"  # Båda har innehåll → kombinerat som street
            addr2 = ""
        country = vals.get("country", "").strip()
        zipcode_raw = vals.get("zipcode", "").strip()
        zipcode = zipcode_raw.replace(" ", "").upper()
        city = (vals.get("city", "") or "").strip()
        # GARP kolumnfel: zipcode "0582 O", city "SLO" — flytta O tillbaka till city → OSLO
        if re.match(r"^\d{4}\s+[A-Za-z]$", zipcode_raw):
            letter = zipcode_raw[-1].upper()
            city = (letter + city.lstrip()).strip() if city else letter
            zipcode_raw = zipcode_raw[:4].strip()
            zipcode = zipcode_raw
        # GARP kan lämna country tomt — gissa från postnummer (N-0582 = Norge, 4 siffror)
        z = zipcode.replace(" ", "")
        if not country and (zipcode.startswith("N-") or (len(z) == 4 and z.isdigit())):
            country = "NO"
        return Receiver(
            rcvid=elem.get("rcvid", "").strip(),
            name=vals.get("name", ""),
            address1=addr1,
            address2=addr2,
            zipcode=zipcode_raw,
            city=city,
            country=country,
            phone=vals.get("phone", ""),
            email=vals.get("email", ""),
            contact=vals.get("contact", ""),
            sms=vals.get("sms", ""),
        )

    def _parse_shipment(self, elem: ET.Element, receiver: Optional[Receiver]) -> Shipment:
        vals = self._extract_vals(elem)
        service = self._parse_service(elem.find("service"))
        containers = [self._parse_container(c) for c in elem.findall("container")]
        notifications = self._parse_notifications(elem.find("ufonline"))

        return Shipment(
            order_no=elem.get("orderno", "").strip(),
            sender_name=vals.get("from", ""),
            reference=vals.get("reference", ""),
            term_code=vals.get("termcode", ""),
            delivery_instruction=vals.get("deliveryinstruction", ""),
            service=service,
            receiver=receiver,
            containers=containers,
            notifications=notifications,
        )

    def _parse_service(self, elem: Optional[ET.Element]) -> ServiceInfo:
        if elem is None:
            logger.warning("Ingen <service>-tagg hittad i XML")
            return ServiceInfo()

        raw_srvid = elem.get("srvid", "").strip()
        carrier, product_code, addon = self._parse_srvid(raw_srvid)

        booking = None
        book_elem = elem.find("booking")
        if book_elem is not None:
            bvals = self._extract_vals(book_elem)
            booking = BookingInfo(
                pickup_booking=bvals.get("pickupbooking", "").upper() == "YES",
                pickup_date=bvals.get("pickupdate", ""),
            )

        return ServiceInfo(
            carrier=carrier,
            product_code=product_code,
            addon=addon,
            raw_srvid=raw_srvid,
            booking=booking,
        )

    @staticmethod
    def _fix_garp_xml(raw: str) -> str:
        """Åtgärdar kända GARP-exportproblem som ger mismatched tag."""
        # GARP exporterar ibland </addon></booking></service> utan <booking> — ta bort orfan </booking>
        # Endast när </booking> kommer direkt efter </addon> (för att undvika giltiga booking-block)
        raw = re.sub(r"(</addon>\s*)</booking>(\s*</service>)", r"\1\2", raw)
        return raw

    # GARP/Unifaun: Använd DHL:102 resp DHL:103 direkt (inte AEX, ASPO).

    @classmethod
    def _parse_srvid(cls, srvid: str) -> tuple[CarrierType, str, str]:
        """Parsar srvid i formatet TRANSPORTÖR:PRODUKTKOD[:TILLÄGG].

        Exempel:
            "DHL:102"       → (CarrierType.DHL, "102", "")  # Paket B2B
            "DHL:103"       → (CarrierType.DHL, "103", "")  # ServicePoint
            "DHL:104:AVIS"  → (CarrierType.DHL, "104", "AVIS")

        I GARP: sätt DHL:102 (AEX ersätts), DHL:103 (ASPO ersätts).

        Raises:
            ValueError: Om srvid inte kan parsas.
        """
        raw = srvid.strip()
        parts = raw.split(":")
        if len(parts) < 2:
            hint = ""
            if raw.upper() in ("AEX", "ASPO"):
                hint = f" Ange DHL:102 istället för AEX, DHL:103 istället för ASPO."
            raise ValueError(
                f"Ogiltig srvid: '{srvid}'. "
                f"Förväntat format: TRANSPORTÖR:PRODUKTKOD[:TILLÄGG] (t.ex. DHL:102, DHL:103).{hint}"
            )

        carrier_str = parts[0].strip().upper()
        product_code = parts[1].strip()
        # Flera addons: DHL:102:AVIS:LQ → addon = "AVIS:LQ"
        addon = ":".join(p.strip() for p in parts[2:]) if len(parts) > 2 else ""

        try:
            carrier = CarrierType(carrier_str)
        except ValueError:
            raise ValueError(
                f"Okänd transportör: '{carrier_str}' i srvid '{srvid}'. "
                f"Kända: {[c.value for c in CarrierType]}"
            )

        return carrier, product_code, addon

    def _parse_container(self, elem: ET.Element) -> Container:
        vals = self._extract_vals(elem)
        length = float(vals.get("length", "0"))
        width = float(vals.get("width", "0"))
        height = float(vals.get("height", "0"))
        volume = float(vals.get("volume", "0"))
        # Beräkna volym från mått om volume saknas men längd/bredd/höjd finns
        if volume <= 0 and length > 0 and width > 0 and height > 0:
            volume = (length * width * height) / 1_000_000  # cm³ → m³
        return Container(
            container_type=elem.get("type", "parcel"),
            measure=elem.get("measure", ""),
            copies=int(float(vals.get("copies", "1"))),
            package_code=vals.get("packagecode", "PC"),
            contents=vals.get("contents", ""),
            weight=float(vals.get("weight", "0")),
            volume=volume,
            length=length,
            width=width,
            height=height,
        )

    def _parse_notifications(self, elem: Optional[ET.Element]) -> list[Notification]:
        if elem is None:
            return []
        notifications = []
        for opt in elem.findall("option"):
            vals = self._extract_vals(opt)
            notifications.append(Notification(
                opt_id=opt.get("optid", "").strip(),
                message=vals.get("message", ""),
            ))
        return notifications

    @staticmethod
    def _fix_mojibake(text: str) -> str:
        """Reparera UTF-8-misread-as-Latin1 (t.ex. Ã¤ → ä).

        Uppstår när XML deklarerar ISO-8859-1 men filen är UTF-8.
        """
        if not text:
            return text
        try:
            return text.encode("latin-1").decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            return text

    @staticmethod
    def _extract_vals(elem: Optional[ET.Element]) -> dict[str, str]:
        """Extraherar alla <val n="key">value</val> till dict.

        Hanterar GARP:s whitespace-padding genom att strippa alla värden.
        Reparerar mojibake (UTF-8 felaktigt tolkat som Latin-1).
        """
        if elem is None:
            return {}
        result = {}
        for v in elem.findall("val"):
            raw = (v.text or "").strip()
            result[v.get("n", "")] = GarpXMLParser._fix_mojibake(raw)
        return result
