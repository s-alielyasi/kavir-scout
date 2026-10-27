import logging
import tempfile
import unittest
from pathlib import Path

from config import Config
from kavirtire.text import normalize_text, matches_product, parse_quantity
from kavirtire.security import SecretFilter, gateway_url, InstanceLock


class CoreTests(unittest.TestCase):
    def test_defaults(self):
        c = Config.from_env({})
        self.assertEqual((c.poll_interval, c.target_quantity), (5, 4))
        self.assertFalse(c.headless)
        self.assertEqual(c.target_product, 'Perfect (R14) KB27')
        self.assertEqual(c.target_size, '185/65R14')
        self.assertEqual(c.national_id, '')

    def test_invalid_config(self):
        for values in ({'POLL_INTERVAL': '0'}, {'POLL_INTERVAL': 'nan'},
                       {'POLL_INTERVAL': 'inf'}, {'TARGET_QUANTITY': '0'},
                       {'TARGET_QUANTITY': 'four'}, {'HEADLESS': 'maybe'},
                       {'NATIONAL_ID': '123'}, {'TARGET_SIZE': ''},
                       {'MAX_RETRIES': '0'}, {'GATEWAY_HOSTS': '*'}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                Config.from_env(values)

    def test_national_id_and_relative_paths(self):
        c = Config.from_env({'NATIONAL_ID': '۰۰۱۲۳۴۵۶۷۸', 'USER_DATA_DIR': './custom'})
        self.assertEqual(c.national_id, '0012345678')
        self.assertTrue(c.user_data_dir.is_absolute())
        self.assertEqual(c.user_data_dir.name, 'custom')

    def test_text(self):
        self.assertEqual(normalize_text('  كد\u200c ملي  ۱۲۳  '), 'کد ملی 123')
        self.assertEqual(normalize_text('به\u200cروز\u200cرسانی'), 'به روز رسانی')

    def test_product_matching(self):
        self.assertTrue(matches_product('Perfect (R14) KB27 ۱۸۵/۶۵R۱۴',
                                        'Perfect (R14) KB27', '185/65R14'))
        self.assertFalse(matches_product('Perfect (R14) KB270 185/65R14',
                                         'Perfect (R14) KB27', '185/65R14'))
        self.assertFalse(matches_product('Perfect (R14) KB27 195/65R14',
                                         'Perfect (R14) KB27', '185/65R14'))
        self.assertTrue(matches_product('Perfect (R14) KB27 185/65R14تعداد',
                                        'Perfect (R14) KB27', '185/65R14'))

    def test_quantity(self):
        self.assertEqual(parse_quantity('۴ حلقه'), 4)
        self.assertIsNone(parse_quantity('۴ از ۶'))

    def test_gateway_boundaries(self):
        hosts = ('shaparak.ir',)
        self.assertTrue(gateway_url('https://bpm.shaparak.ir/pgw?token=abc', hosts))
        for url in ('http://bpm.shaparak.ir/pay', 'https://shaparak.ir.evil.test/',
                    'https://evilshaparak.ir/', 'https://kavirtire.ir/pay',
                    'https://user:pass@bpm.shaparak.ir/', 'https://bpm.shaparak.ir:444/'):
            self.assertFalse(gateway_url(url, hosts), url)

    def test_secret_filter(self):
        f = SecretFilter(['0012345678', '12345'])
        record = logging.LogRecord('x', 20, '', 1, 'ID=%s OTP=%s',
                                   ('0012345678', '12345'), None)
        f.filter(record)
        self.assertNotIn('0012345678', record.getMessage())
        self.assertNotIn('12345', record.getMessage())

    def test_lock_is_exclusive_and_released(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bot.lock'
            with InstanceLock(path):
                with self.assertRaises(RuntimeError):
                    with InstanceLock(path):
                        pass
            with InstanceLock(path):
                pass


if __name__ == '__main__':
    unittest.main()
