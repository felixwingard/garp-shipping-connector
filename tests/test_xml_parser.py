"""Tester för GARP XML-parser."""

import pytest
from pathlib import Path

from src.parsers.xml_parser import GarpXMLParser
from src.parsers.models import CarrierType


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def parser():
    return GarpXMLParser()


class TestParseFile:
    """Tester med riktig XML-fil."""

    def test_parse_dhl_foretag(self, parser):
        filepath = FIXTURES_DIR / "sample_dhl_foretag.xml"
        shipments = parser.parse_file(filepath)

        assert len(shipments) == 1
        s = shipments[0]

        # Order
        assert s.order_no == "107739-132888"
        assert s.reference == "107739-132888"
        assert s.sender_name == "Ernst P AB"
        assert s.term_code == "S"

        # Mottagare
        assert s.receiver.name == "Testbutiken AB"
        assert s.receiver.address1 == "Storgatan 10"
        assert s.receiver.zipcode == "11122"
        assert s.receiver.city == "STOCKHOLM"
        assert s.receiver.country == "SE"
        assert s.receiver.rcvid == "7631"
        assert s.receiver.email == "anna@testbutiken.se"

        # Service
        assert s.service.carrier == CarrierType.DHL
        assert s.service.product_code == "102"
        assert s.service.addon == ""

        # Bokning
        assert s.service.booking is not None
        assert s.service.booking.pickup_booking is True
        assert s.service.booking.pickup_date == "2026-02-19"

        # Container
        assert len(s.containers) == 1
        c = s.containers[0]
        assert c.copies == 1
        assert c.weight == 5.5
        assert c.package_code == "PKT"
        assert c.contents == "material"

        # Notifieringar
        assert len(s.notifications) == 1
        assert s.notifications[0].opt_id == "enot"
        assert "107739" in s.notifications[0].message

    def test_parse_bring_norge(self, parser):
        filepath = FIXTURES_DIR / "sample_bring_norge.xml"
        shipments = parser.parse_file(filepath)

        assert len(shipments) == 1
        s = shipments[0]
        assert s.order_no == "107740-132889"
        assert s.service.carrier == CarrierType.BRING
        assert s.service.product_code == "0340"
        assert s.receiver.country == "NO"
        assert s.receiver.city == "OSLO"
        assert s.containers[0].weight == 8.2

    def test_parse_garp_format(self, parser):
        """Format från GARP-export med srvid DHL:103 (ServicePoint)."""
        filepath = FIXTURES_DIR / "sample_garp_format.xml"
        shipments = parser.parse_file(filepath)

        assert len(shipments) == 1
        s = shipments[0]

        # Order
        assert s.order_no == "W66344-133251"
        assert s.reference == "W66344-133251"
        assert s.sender_name == "ERNSTP"
        assert s.term_code == "S"

        # Mottagare
        assert s.receiver.rcvid == "WEB"
        assert s.receiver.name == "Niklas Persson"
        assert s.receiver.address1 == "Boarps backar 149"
        assert s.receiver.zipcode == "264 94"
        assert s.receiver.city == "Klippan"
        assert s.receiver.phone == "+46700322585"
        assert s.receiver.sms == "+46700322585"
        assert s.receiver.email == "felix@ernstp.se"

        # DHL:103 = ServicePoint
        assert s.service.carrier == CarrierType.DHL
        assert s.service.product_code == "103"
        assert s.service.raw_srvid == "DHL:103"

        # Bokning
        assert s.service.booking is not None
        assert s.service.booking.pickup_booking is True
        assert s.service.booking.pickup_date == "2026-02-25"

        # Container (PC mappas till PKT i DHL-klienten)
        assert len(s.containers) == 1
        c = s.containers[0]
        assert c.copies == 1
        assert c.weight == 1.0
        assert c.package_code == "PC"
        assert c.contents == "material"
        assert c.volume == 0.0

        # E-postnotifiering
        assert len(s.notifications) == 1
        assert s.notifications[0].opt_id == "enot"
        assert "W66344" in s.notifications[0].message

    def test_address2_fallback_when_address1_empty(self, parser):
        """GARP lägger ibland hela gatan i address2 — ska flyttas till address1."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <data>
         <receiver rcvid="X">
          <val n="name">Test AB</val>
          <val n="address1"></val>
          <val n="address2">Storgatan 42</val>
          <val n="zipcode">11122</val>
          <val n="city">Stockholm</val>
          <val n="country">SE</val>
         </receiver>
         <shipment orderno="T1">
          <val n="from">S</val>
          <service srvid="DHL:102"></service>
         </shipment>
        </data>"""
        shipments = parser.parse_string(xml)
        assert shipments[0].receiver.address1 == "Storgatan 42"
        assert shipments[0].receiver.address2 == ""

    def test_address1_and_address2_combined(self, parser):
        """När båda har innehåll ska de kombineras i address1 (DHL använder bara street)."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <data>
         <receiver rcvid="X">
          <val n="name">Test</val>
          <val n="address1">Storgatan 10</val>
          <val n="address2">Lgh 5</val>
          <val n="zipcode">11122</val>
          <val n="city">Stockholm</val>
          <val n="country">SE</val>
         </receiver>
         <shipment orderno="T1"><val n="from">S</val><service srvid="DHL:102"></service></shipment>
        </data>"""
        shipments = parser.parse_string(xml)
        assert shipments[0].receiver.address1 == "Storgatan 10, Lgh 5"
        assert shipments[0].receiver.address2 == ""


class TestParseSrvid:
    """Tester för srvid-parsning."""

    def test_dhl_basic(self, parser):
        carrier, code, addon = parser._parse_srvid("DHL:104")
        assert carrier == CarrierType.DHL
        assert code == "104"
        assert addon == ""

    def test_dhl_with_addon(self, parser):
        carrier, code, addon = parser._parse_srvid("DHL:104:AVIS")
        assert carrier == CarrierType.DHL
        assert code == "104"
        assert addon == "AVIS"

    def test_dhl_with_multiple_addons(self, parser):
        carrier, code, addon = parser._parse_srvid("DHL:102:AVIS:LQ")
        assert carrier == CarrierType.DHL
        assert code == "102"
        assert addon == "AVIS:LQ"

    def test_postnord(self, parser):
        carrier, code, addon = parser._parse_srvid("PN:19")
        assert carrier == CarrierType.POSTNORD
        assert code == "19"
        assert addon == ""

    def test_bring(self, parser):
        carrier, code, addon = parser._parse_srvid("BRING:0342")
        assert carrier == CarrierType.BRING
        assert code == "0342"
        assert addon == ""

    def test_bring_business_parcel(self, parser):
        carrier, code, addon = parser._parse_srvid("BRING:BUSINESS_PARCEL_BULK")
        assert carrier == CarrierType.BRING
        assert code == "BUSINESS_PARCEL_BULK"
        assert addon == ""

    def test_aex_rejected_with_hint(self, parser):
        """AEX (Unifaun) accepteras ej — använd DHL:102 i GARP."""
        with pytest.raises(ValueError, match="DHL:102 istället för AEX"):
            parser._parse_srvid("AEX")

    def test_aspo_rejected_with_hint(self, parser):
        """ASPO (Unifaun) accepteras ej — använd DHL:103 i GARP."""
        with pytest.raises(ValueError, match="DHL:103 istället för ASPO"):
            parser._parse_srvid("ASPO")

    def test_container_dimensions(self, parser):
        """Container length, width, height parsas från XML; volume beräknas om saknas."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<data>
 <receiver rcvid="X"><val n="name">K</val><val n="address1">A</val><val n="zipcode">5220</val><val n="city">Odense</val><val n="country">DK</val></receiver>
 <shipment orderno="T1">
  <val n="from">X</val><val n="reference">T1</val>
  <service srvid="DHL:112"/>
  <container type="parcel">
   <val n="copies">1</val><val n="weight">15</val>
   <val n="length">46</val><val n="width">36</val><val n="height">30</val>
  </container>
 </shipment>
</data>"""
        shipments = parser.parse_string(xml)
        c = shipments[0].containers[0]
        assert c.length == 46
        assert c.width == 36
        assert c.height == 30
        assert c.weight == 15
        # Volume beräknas: 46*36*30 / 1e6 = 0.04968
        assert 0.049 < c.volume < 0.050

    def test_mojibake_fix(self, parser):
        """UTF-8 felaktigt tolkat som Latin-1 repareras (Ã¤ → ä)."""
        assert parser._fix_mojibake("Ã¤r") == "är"
        assert parser._fix_mojibake("Stockholm") == "Stockholm"
        assert parser._fix_mojibake("") == ""

    def test_invalid_format(self, parser):
        with pytest.raises(ValueError, match="Ogiltig srvid"):
            parser._parse_srvid("INVALID")

    def test_unknown_carrier(self, parser):
        with pytest.raises(ValueError, match="Okänd transportör"):
            parser._parse_srvid("UPS:100")

    def test_whitespace_handling(self, parser):
        """GARP paddar fält med whitespace."""
        carrier, code, addon = parser._parse_srvid("DHL:104                          ")
        assert carrier == CarrierType.DHL
        assert code == "104"


class TestParseString:
    """Tester med inline XML."""

    def test_minimal_xml(self, parser):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <data>
         <receiver rcvid="1">
          <val n="name">Test AB</val>
          <val n="address1">Testgatan 1</val>
          <val n="zipcode">11122</val>
          <val n="city">Stockholm</val>
          <val n="country">SE</val>
          <val n="phone"></val>
          <val n="email">test@test.se</val>
         </receiver>
         <shipment orderno="ORD-001">
          <val n="from">Avsändare</val>
          <val n="reference">REF-001</val>
          <val n="termcode">S</val>
          <service srvid="DHL:104">
          </service>
          <container type="parcel">
           <val n="copies">1</val>
           <val n="weight">2.50</val>
          </container>
         </shipment>
        </data>"""

        shipments = parser.parse_string(xml)
        assert len(shipments) == 1
        assert shipments[0].order_no == "ORD-001"
        assert shipments[0].service.carrier == CarrierType.DHL
        assert shipments[0].service.product_code == "104"
        assert shipments[0].containers[0].weight == 2.5

    def test_postnord_xml(self, parser):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <data>
         <receiver rcvid="2">
          <val n="name">Kund AB</val>
          <val n="address1">Kungsgatan 5</val>
          <val n="zipcode">41101</val>
          <val n="city">Göteborg</val>
          <val n="country">SE</val>
          <val n="phone">0701234567</val>
          <val n="email">kund@example.com</val>
         </receiver>
         <shipment orderno="ORD-002">
          <val n="from">Climbing247</val>
          <val n="reference">REF-002</val>
          <val n="termcode">S</val>
          <service srvid="PN:19">
          </service>
          <container type="parcel">
           <val n="copies">2</val>
           <val n="weight">5.00</val>
          </container>
         </shipment>
        </data>"""

        shipments = parser.parse_string(xml)
        s = shipments[0]
        assert s.service.carrier == CarrierType.POSTNORD
        assert s.service.product_code == "19"
        assert s.containers[0].copies == 2

    def test_whitespace_stripping(self, parser):
        """GARP paddar alla fält med whitespace."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <data>
         <receiver rcvid="123       ">
          <val n="name">  Företag AB         </val>
          <val n="zipcode">  11122   </val>
          <val n="city">  Stockholm     </val>
          <val n="country">SE</val>
         </receiver>
         <shipment orderno="  ORD-003  ">
          <val n="reference">  REF-003   </val>
          <service srvid="  DHL:103   ">
          </service>
         </shipment>
        </data>"""

        shipments = parser.parse_string(xml)
        s = shipments[0]
        assert s.receiver.name == "Företag AB"
        assert s.receiver.zipcode == "11122"
        assert s.receiver.city == "Stockholm"
        assert s.receiver.rcvid == "123"
        assert s.service.carrier == CarrierType.DHL
        assert s.service.product_code == "103"

    def test_no_notifications(self, parser):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <data>
         <receiver rcvid="1">
          <val n="name">Test</val>
          <val n="country">SE</val>
         </receiver>
         <shipment orderno="ORD-004">
          <service srvid="DHL:104">
          </service>
         </shipment>
        </data>"""

        shipments = parser.parse_string(xml)
        assert len(shipments[0].notifications) == 0

    def test_multiple_shipments(self, parser):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <data>
         <receiver rcvid="1">
          <val n="name">Kund</val>
          <val n="country">SE</val>
         </receiver>
         <shipment orderno="ORD-A">
          <service srvid="DHL:104"></service>
         </shipment>
         <shipment orderno="ORD-B">
          <service srvid="PN:17"></service>
         </shipment>
        </data>"""

        shipments = parser.parse_string(xml)
        assert len(shipments) == 2
        assert shipments[0].order_no == "ORD-A"
        assert shipments[0].service.carrier == CarrierType.DHL
        assert shipments[1].order_no == "ORD-B"
        assert shipments[1].service.carrier == CarrierType.POSTNORD
