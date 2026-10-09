"""SalesOS demo regressions; LIST-mode tests are excluded."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))

MODULES = ('test_commerce', 'test_admin_dashboard', 'test_telegram_bot',
           'test_product_search', 'test_product_parser', 'test_gemini',
           'test_prompts', 'test_agent', 'test_message_service', 'test_whatsapp_bot')
RETIRED = {
    'test_notifies_once_when_the_product_list_cycle_starts',
    'test_a_failed_list_notification_does_not_break_the_pipeline',
    'test_product_list_runs_a_full_pipeline_per_item',
    'test_product_list_rejects_an_invalid_count',
    'test_product_list_stops_on_budget_and_reports_processed_items',
    'test_product_list_notes_an_operator_item_and_continues',
    'test_product_list_keeps_going_after_a_broken_api_response',
}


def cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from cases(item)
        else:
            yield item


if __name__ == '__main__':
    suite = unittest.TestSuite()
    excluded = []
    for module in MODULES:
        for case in cases(unittest.defaultTestLoader.loadTestsFromName(module)):
            if case._testMethodName in RETIRED:
                excluded.append(case.id())
            else:
                suite.addTest(case)
    print('Retired LIST-mode cases retained and excluded:', len(excluded), flush=True)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
