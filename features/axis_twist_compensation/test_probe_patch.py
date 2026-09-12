#!/usr/bin/env python3
"""Static regression checks for the K2 axis-twist probe patch."""

import ast
import pathlib
import unittest


PROBE_PATCH = pathlib.Path(__file__).with_name("probe.py")
COMPENSATION_PATCH = pathlib.Path(__file__).with_name(
    "axis_twist_compensation.py"
)


class ProbePatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(PROBE_PATCH.read_text(encoding="utf-8"))
        cls.classes = {
            node.name: node
            for node in cls.tree.body
            if isinstance(node, ast.ClassDef)
        }
        cls.functions = {
            node.name: node
            for node in cls.tree.body
            if isinstance(node, ast.FunctionDef)
        }

    def test_probe_does_not_reference_an_unbound_compensation_variable(self):
        printer_probe = self.classes["PrinterProbe"]
        probe_method = next(
            node for node in printer_probe.body
            if isinstance(node, ast.FunctionDef) and node.name == "_probe"
        )
        loaded_names = {
            node.id for node in ast.walk(probe_method)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        }
        self.assertNotIn("z_compensation", loaded_names)

    def test_single_probe_uses_the_legacy_probe_api(self):
        run_single_probe = self.functions["run_single_probe"]
        called_attributes = {
            node.func.attr for node in ast.walk(run_single_probe)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertEqual(called_attributes, {"run_probe"})

    def test_endstop_wrapper_has_no_orphaned_session_api(self):
        wrapper_methods = {
            node.name for node in self.classes["ProbeEndstopWrapper"].body
            if isinstance(node, ast.FunctionDef)
        }
        self.assertNotIn("start_probe_session", wrapper_methods)
        self.assertNotIn("end_probe_session", wrapper_methods)

    def test_zero_is_accepted_as_a_calibration_boundary(self):
        source = COMPENSATION_PATCH.read_text(encoding="utf-8")
        self.assertNotIn("if not all([", source)
        self.assertGreaterEqual(
            source.count("any(value is None for value in ("),
            3,
        )
        self.assertIn("self.y_end_point[1]", source)


if __name__ == "__main__":
    unittest.main()
