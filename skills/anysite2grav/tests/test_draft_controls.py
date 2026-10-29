"""Unimplemented widgets must remain actionable omissions, not silently accepted losses."""
from collections import Counter
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from build_pages import Builder, main


class DraftControlTests(unittest.TestCase):
    def test_draft_records_the_route_and_original_control_target_without_mutating_input(self):
        builder = object.__new__(Builder)
        builder.current_text = ({}, {})
        builder.current_layout = {}
        builder.current_modals = set()
        builder.current_source_route = '/themes'
        builder.unresolved_controls = []
        builder.stats = Counter()
        control = {'type': 'button', 'label': 'Layout 0', 'action': 'layout-filters', '_target': 'dialog', '_path': 'main>div>button'}
        self.assertEqual(builder.rewrite_blocks([control], None), [])
        self.assertEqual(builder.unresolved_controls, [{
            'route': '/themes', 'label': 'Layout 0', 'action': 'layout-filters',
            'target': 'dialog', 'source_path': 'main>div>button',
        }])
        self.assertEqual(control['_path'], 'main>div>button')

    def test_resolved_dialog_controls_are_not_reported_as_omitted(self):
        builder = object.__new__(Builder)
        builder.current_text = ({}, {})
        builder.current_layout = {}
        builder.current_modals = {'filters'}
        builder.unresolved_controls = []
        builder.stats = Counter()
        controls = builder.rewrite_blocks([{'type': 'button', 'label': 'Filters', 'action': 'filters', '_target': 'dialog'}], None)
        self.assertEqual(controls, [{'type': 'button', 'label': 'Filters', 'modal': 'filters'}])
        self.assertEqual(builder.unresolved_controls, [])

    def test_content_toggles_remain_in_the_draft_but_are_not_mistaken_for_working_interactions(self):
        builder = object.__new__(Builder)
        builder.current_text = ({}, {})
        builder.current_layout = {}
        builder.current_modals = set()
        builder.current_source_route = '/examples'
        builder.unresolved_controls = []
        builder.stats = Counter()
        controls = builder.rewrite_blocks([{'type': 'button', 'label': 'Second tab', 'action': 'pane-2', '_target': 'content'}], None)
        self.assertEqual(controls, [{'type': 'button', 'label': 'Second tab', 'action': 'pane-2'}])
        self.assertEqual(builder.unresolved_controls[0]['action'], 'pane-2')

    def test_default_cli_fails_for_missing_functionality_but_explicit_draft_mode_can_continue(self):
        for draft, unresolved, expected in [(False, True, 1), (True, True, 0), (False, False, 0)]:
            with self.subTest(draft=draft, unresolved=unresolved):
                arguments = ['build_pages.py', 'migration', '--grav', 'grav'] + (['--allow-incomplete'] if draft else [])
                with patch('sys.argv', arguments), patch('build_pages.Builder') as builder_type:
                    builder_type.return_value.unresolved_controls = [{'label': 'Filter'}] if unresolved else []
                    self.assertEqual(main(), expected)
                    builder_type.return_value.run.assert_called_once()


if __name__ == '__main__':
    unittest.main()
