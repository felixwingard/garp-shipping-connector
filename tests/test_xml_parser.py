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

    def test_postnord(self, parser):
        carrier, code, addon = parser._parse_srvid("PN:19")
        assert carrier == CarrierType.POSTNORD
        assert code == "19"
        assert addon == ""

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
