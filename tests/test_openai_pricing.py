import unittest

from openai_pricing import PricingLookupError, parse_standard_prices


SAMPLE = """# Pricing
### Standard pricing data
| Model | Short context input | Short context output | Cached |
| --- | --- | --- | --- |
| gpt-6-luna | $0.10 | $0.50 | $0.01 |
| gpt-6.1-sol | $2.00 | $10.00 | $0.10 |
| gpt-5 | $1.25 | $10.00 | $0.125 |
Batch
| gpt-6-luna | $0.05 | $0.25 | $0.005 |
"""


class PricingTests(unittest.TestCase):
    def test_standard_only(self):
        prices = parse_standard_prices(SAMPLE)
        self.assertEqual(prices["gpt-6-luna"], {"input": "0.10", "output": "0.50"})
        self.assertEqual(prices["gpt-6.1-sol"]["output"], "10.00")

    def test_no_standard_table_fails_closed(self):
        with self.assertRaises(PricingLookupError):
            parse_standard_prices("| gpt-6-luna | $0.01 | $0.02 |")

    def test_duplicate_model_fails_closed(self):
        with self.assertRaises(PricingLookupError):
            parse_standard_prices(SAMPLE.replace(
                "Batch", "| gpt-6-luna | $0.11 | $0.51 | $0.01 |\nBatch"
            ))


if __name__ == "__main__":
    unittest.main()
