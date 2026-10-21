from dataclasses import replace
import unittest
from unittest.mock import Mock, patch

from installer.command import InstallError
from installer.config import Secrets
from installer.networking import ethernet, online, parse_networks
from installer.system import write_network
from main import demo_config


class NetworkTests(unittest.TestCase):
    def test_scan_preserves_ssid_spaces_and_security(self):
        text = "  Network name                    Security  Signal\n> Coffee Shop 5G                  psk       ****\n  Public                          open      **\n  Corporate                       8021x     ***\n"
        networks = parse_networks(text)
        self.assertEqual(networks[0]["ssid"], "Coffee Shop 5G")
        self.assertEqual(networks[2]["security"], "8021x")
        self.assertEqual(parse_networks("No networks available"), [])

    def test_https_outage(self):
        with patch("urllib.request.urlopen", side_effect=OSError):
            self.assertFalse(online())

    def test_invalid_static_address_never_executes_commands(self):
        r = Mock()
        with patch("installer.networking.valid_interface"):
            with self.assertRaises(ValueError):
                ethernet(r, "eth0", "invalid", "1.1.1.1", "8.8.8.8")
        r.run.assert_not_called()

    def test_wifi_target_profile_root_only_and_not_public(self):
        c = replace(demo_config(), net_interface="wlan0", wifi_ssid="Coffee Shop", wifi_security="sae", wifi_hidden=True)
        with patch("installer.system.write_target") as write:
            write_network(c, Secrets(wifi_password="my secret\\phrase"))
            path, content, mode = write.call_args.args
            self.assertEqual(mode, 0o600)
            self.assertIn("system-connections", path)
            self.assertIn("key-mgmt=sae", content)
            self.assertIn("hidden=true", content)
            self.assertIn("psk=my\\ssecret\\\\phrase", content)
            self.assertNotIn("my secret", str(c.public()))

    def test_wired_static_profile(self):
        c = replace(demo_config(), net_interface="enp1s0", net_address="192.168.1.3/24", net_gateway="192.168.1.1", net_dns="1.1.1.1 9.9.9.9")
        with patch("installer.system.write_target") as write:
            write_network(c, Secrets())
            self.assertIn("address1=192.168.1.3/24,192.168.1.1", write.call_args.args[1])

    def test_password_newline_rejected_before_writing(self):
        c = replace(demo_config(), net_interface="wlan0", wifi_ssid="SSID")
        with patch("installer.system.write_target") as write, self.assertRaises(InstallError):
            write_network(c, Secrets(wifi_password="evil\nkey=value"))
        write.assert_not_called()
