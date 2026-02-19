"""Parser för GARP:s XML-exportfiler.

GARP exporterar XML i ett format baserat på Unifaun OnlineConnect.
Tjänstekoder (srvid) har uppdaterats till formatet TRANSPORTÖR:PRODUKTKOD[:TILLÄGG]
istället för Unifauns egna koder.
"""

from __future__ import annotations

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
        tree = ET.parse(filepath)
        root = tree.getroot()  # <data>

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
        return Receiver(
            rcvid=elem.get("rcvid", "").strip(),
            name=vals.get("name", ""),
            address1=vals.get("address1", ""),
            address2=vals.get("address2", ""),
            zipcode=vals.get("zipcode", ""),
            city=vals.get("city", ""),
            country=vals.get("country", ""),
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
    def _parse_srvid(srvid: str) -> tuple[CarrierType, str, str]:
        """Parsar srvid i formatet TRANSPORTÖR:PRODUKTKOD[:TILLÄGG].

        Exempel:
            "DHL:104"       → (CarrierType.DHL, "104", "")
            "DHL:104:AVIS"  → (CarrierType.DHL, "104", "AVIS")
            "PN:19"         → (CarrierType.POSTNORD, "19", "")

        Raises:
            ValueError: Om srvid inte kan parsas.
        """
        parts = srvid.split(":")
        if len(parts) < 2:
            raise ValueError(
                f"Ogiltig srvid: '{srvid}'. "
                f"Förväntat format: TRANSPORTÖR:PRODUKTKOD[:TILLÄGG]"
            )

        carrier_str = parts[0].strip().upper()
        product_code = parts[1].strip()
        addon = parts[2].strip() if len(parts) > 2 else ""

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
        return Container(
            container_type=elem.get("type", "parcel"),
            measure=elem.get("measure", ""),
            copies=int(float(vals.get("copies", "1"))),
            package_code=vals.get("packagecode", "PC"),
            contents=vals.get("contents", ""),
            weight=float(vals.get("weight", "0")),
            volume=float(vals.get("volume", "0")),
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
    def _extract_vals(elem: Optional[ET.Element]) -> dict[str, str]:
        """Extraherar alla <val n="key">value</val> till dict.

        Hanterar GARP:s whitespace-padding genom att strippa alla värden.
        """
        if elem is None:
            return {}
        return {
            v.get("n", ""): (v.text or "").strip()
            for v in elem.findall("val")
        }
