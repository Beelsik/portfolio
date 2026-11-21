"""End-to-end reconciliation tests: traps quarantine, idempotency, hash chain tampering, and 60-doc benchmark."""

import unittest

from ledgerguard.benchmark import run_benchmark
from ledgerguard.engine import LedgerGuardEngine
from ledgerguard.fixtures import get_presets


class TestEngineAndBenchmark(unittest.TestCase):
    def test_traps_preset_caught_across_all_languages(self) -> None:
        for lang in ("ru", "uk", "en", "fr"):
            with self.subTest(lang=lang):
                eng = LedgerGuardEngine(lang=lang)
                traps = get_presets(lang)["traps"]["text"]
                rep = eng.process(raw_text=traps)
                codes = {d.code for d in rep.discrepancies}
                self.assertEqual(rep.status, "QUARANTINED_FOR_REVIEW")
                self.assertIn("BANK_ACCOUNT_CHANGED", codes)
                self.assertIn("PRICE_ABOVE_CONTRACT_CAP", codes)
                self.assertIn("LINE_MATH_MISMATCH", codes)
                self.assertTrue(rep.chain_verification["valid"])
                # Ensure look-alike 3x1.5 vs 3x2.5 did not confuse matcher
                skus = [ln.matched_sku for ln in rep.lines]
                self.assertEqual(len(set(skus)), 4)

    def test_clean_preset_auto_passes_and_blocks_duplicate_replay(self) -> None:
        eng = LedgerGuardEngine(lang="ru")
        clean_text = get_presets("ru")["clean_packs"]["text"]

        first = eng.process(raw_text=clean_text)
        self.assertEqual(first.status, "READY_FOR_ERP")
        self.assertIsNotNone(first.erp_payload)
        self.assertEqual(len(first.discrepancies), 0)

        second = eng.process(raw_text=clean_text)
        self.assertEqual(second.status, "DUPLICATE_BLOCKED")
        self.assertEqual(second.duplicate_of_batch_id, first.batch_id)
        self.assertIsNone(second.erp_payload)
        self.assertTrue(second.before.duplicate_created)
        self.assertTrue(second.chain_verification["valid"])

    def test_audit_chain_detects_sqlite_row_tampering(self) -> None:
        eng = LedgerGuardEngine(lang="ru")
        clean_text = get_presets("ru")["clean_packs"]["text"]
        eng.process(raw_text=clean_text)
        self.assertTrue(eng.storage.verify_audit_chain()["valid"])

        # Simulate silent malicious tampering of an audit row directly in SQLite
        eng.storage.conn.execute("UPDATE audit_log SET payload_json = '{\"tampered\":true}' WHERE seq = 1")
        tamper_res = eng.storage.verify_audit_chain()
        self.assertFalse(tamper_res["valid"])
        self.assertEqual(tamper_res["broken_at_seq"], 1)

    def test_benchmark_60_docs_zero_silent_errors(self) -> None:
        res = run_benchmark(lang="ru")
        self.assertEqual(res["total_docs"], 60)
        self.assertEqual(res["after_silent_error_docs"], 0)
        self.assertGreater(res["before_silent_error_docs"], 20)
        self.assertEqual(res["auto_passed_clean"], 36)
        self.assertTrue(res["audit_chain_valid"])


if __name__ == "__main__":
    unittest.main()
