"""Additional Tkinter workflow tests aimed at high branch coverage in the desktop workbench."""

from __future__ import annotations

import json
import logging
import queue
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd

from ui.desktop_app import DesktopWorkbench, HoverTooltip, UILogHandler, launch_desktop_app


def _walk_widgets(widget: tk.Misc):
    """Yield a widget and all descendants for simple Tk test lookups."""

    yield widget
    for child in widget.winfo_children():
        yield from _walk_widgets(child)


def _find_button(root: tk.Misc, text: str):
    """Find the first Tk button whose visible text matches the requested label."""

    for widget in _walk_widgets(root):
        try:
            if widget.cget("text") == text:
                return widget
        except tk.TclError:
            continue
    raise AssertionError(f"Button with text {text!r} not found")


class DesktopWorkbenchHighCoverageTests(unittest.TestCase):
    """Cover UI guard clauses and small callback branches not exercised by the core workflow tests."""

    def setUp(self) -> None:
        try:
            self.workbench = DesktopWorkbench(SimpleNamespace(config_file=None))
        except tk.TclError as exc:  # pragma: no cover - depends on local Tk availability
            self.skipTest(f"Tkinter is unavailable in this environment: {exc}")
        self.workbench.root.withdraw()

    def tearDown(self) -> None:
        if hasattr(self, "workbench"):
            try:
                self.workbench._on_close()
            except tk.TclError:  # pragma: no cover - teardown fallback for already-destroyed Tk roots
                pass

    def test_log_handler_tooltip_and_run_wrapper_branches(self) -> None:
        message_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        handler = UILogHandler(message_queue)
        record = logging.LogRecord("test", logging.INFO, __file__, 0, "hello", (), None)
        handler.emit(record)
        self.assertEqual(message_queue.get_nowait()[0], "log")

        tooltip = HoverTooltip(self.workbench.root)
        with patch.object(tk.Toplevel, "attributes", side_effect=tk.TclError("unsupported")):
            tooltip.show("Helpful text", x=10, y=20)
            tooltip.hide()

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "ui_config.json"
            config_path.write_text(json.dumps({"research_topic": "Loaded", "search_keywords": ["llm"]}), encoding="utf-8")
            extra = DesktopWorkbench(SimpleNamespace(config_file=str(config_path)))
            extra.root.withdraw()
            with patch.object(extra.root, "mainloop", return_value=None):
                self.assertEqual(extra.run(), 0)
            extra._on_close()

    def test_help_text_and_quick_access_guard_branches(self) -> None:
        self.assertIn("Filesystem location", self.workbench._help_text_for_field("unknown_path"))
        self.assertIn("Credential used", self.workbench._help_text_for_field("custom_api_key"))
        self.assertIn("artifacts are written", self.workbench._help_text_for_field("output_demo"))
        self.assertIn("verbose or debug", self.workbench._help_text_for_field("log_demo"))
        self.assertIn("on or off", self.workbench._help_text_for_field("custom_enabled"))
        self.assertIn("saved into profiles", self.workbench._help_text_for_field("some_misc_value"))

        original_frame = self.workbench.quick_access_controls_frame
        self.workbench.quick_access_controls_frame = None
        self.workbench._populate_quick_access_controls()
        self.workbench.quick_access_controls_frame = original_frame
        ttk_label = tk.Label(original_frame, text="temporary")
        ttk_label.grid(row=99, column=0)
        self.workbench._populate_quick_access_controls()
        texts: list[str] = []
        for child in original_frame.winfo_children():
            if not hasattr(child, "cget"):
                continue
            try:
                texts.append(child.cget("text"))
            except tk.TclError:
                continue
        self.assertNotIn("temporary", texts)

    def test_settings_focus_slider_and_summary_branches(self) -> None:
        original_combo = self.workbench.settings_search_combo
        self.workbench.settings_search_combo = None
        self.workbench._refresh_settings_search_results()
        self.workbench.settings_search_combo = original_combo

        self.workbench.settings_search_choice_var.set("")
        self.workbench._focus_selected_setting()

        widget = self.workbench.field_focus_widgets["database_path"]
        with patch.object(widget, "focus_set", side_effect=tk.TclError("no focus")):
            self.workbench._focus_field("database_path")

        with patch.object(widget, "update_idletasks", side_effect=tk.TclError("broken")):
            self.workbench._scroll_widget_into_view(widget)

        original_label = self.workbench.slider_value_labels.pop("relevance_threshold")
        self.workbench._sync_slider_label("relevance_threshold")
        self.workbench.slider_value_labels["relevance_threshold"] = original_label
        original_var = self.workbench.scalar_vars["relevance_threshold"]
        self.workbench.scalar_vars["relevance_threshold"] = tk.StringVar(value="bad")
        self.workbench._sync_slider_label("relevance_threshold")
        self.workbench.scalar_vars["relevance_threshold"] = original_var

        self.workbench.scalar_vars["pdf_download_mode"].set("relevant_only")
        self.workbench.scalar_vars["papers_dir"].set("papers/shared")
        self.workbench.scalar_vars["relevant_pdfs_dir"].set("papers/shared")
        self.workbench._refresh_settings_overview()
        output_text = self.workbench.output_summary_text.get("1.0", tk.END)
        self.assertIn("same folder", output_text)

        self.workbench.hover_help_enabled.set(False)
        self.workbench._toggle_hover_help()
        self.workbench.hover_help_enabled.set(True)
        self.workbench._toggle_hover_help()
        self.assertIn("Hover help enabled", self.workbench.status_var.get())

    def test_handbook_path_and_analysis_pass_guard_branches(self) -> None:
        handbook_tree = self.workbench.handbook_tree
        handbook_text = self.workbench.handbook_text

        self.workbench.handbook_tree = None
        self.workbench._handle_handbook_selection(None)
        self.workbench.handbook_tree = handbook_tree
        self.workbench._handle_handbook_selection(None)
        self.workbench._render_handbook_entry("missing")
        self.assertIn("No handbook content", self.workbench.handbook_text.get("1.0", tk.END))

        self.workbench.handbook_tree = None
        self.workbench._open_handbook_entry("guide:models")
        self.workbench.handbook_tree = handbook_tree

        self.workbench.handbook_text = None
        self.workbench._render_handbook_text("ignored")
        self.workbench.handbook_text = handbook_text

        with patch("ui.desktop_app.filedialog.askdirectory", return_value=""), patch(
            "ui.desktop_app.filedialog.asksaveasfilename", return_value=""
        ), patch("ui.desktop_app.filedialog.askopenfilename", return_value=""):
            self.workbench._browse_for_field("results_dir", self.workbench.scalar_vars["results_dir"])
            self.workbench._browse_for_field("database_path", self.workbench.scalar_vars["database_path"])
            self.workbench._browse_for_field("manual_source_path", self.workbench.scalar_vars["manual_source_path"])

        analysis_widget = self.workbench.text_widgets.pop("analysis_passes")
        self.assertEqual(self.workbench._current_analysis_passes(), [])
        self.workbench._write_analysis_passes([])
        self.workbench.text_widgets["analysis_passes"] = analysis_widget

    def test_pass_builder_remaining_branches(self) -> None:
        self.workbench._write_analysis_passes(
            [
                {
                    "name": "deep",
                    "provider": "gemini",
                    "threshold": 82,
                    "decision_mode": "triage",
                    "margin": 10,
                    "model_name": "gemini-2.5-flash",
                    "min_input_score": 70,
                }
            ]
        )
        self.workbench._open_pass_builder()
        dialog = next(widget for widget in self.workbench.root.winfo_children() if isinstance(widget, tk.Toplevel))
        tree = next(widget for widget in _walk_widgets(dialog) if widget.winfo_class() == "Treeview")

        tree.selection_set("0")
        tree.event_generate("<<TreeviewSelect>>")
        _find_button(dialog, "Update Pass").invoke()

        tree.selection_remove("0")
        _find_button(dialog, "Remove Pass").invoke()
        _find_button(dialog, "Move Down").invoke()

        _find_button(dialog, "Add Pass").invoke()
        tree.selection_set("0")
        _find_button(dialog, "Move Up").invoke()
        _find_button(dialog, "Apply").invoke()

        passes = self.workbench._current_analysis_passes()
        self.assertTrue(passes)

    def test_collection_start_poll_tables_outputs_and_close_branches(self) -> None:
        self.workbench.profile_combo.set("combo-profile")
        self.workbench.scalar_vars["profile_name"].set("")
        collected = self.workbench._collect_form_values()
        self.assertEqual(collected["profile_name"], "combo-profile")

        text_widget = self.workbench.text_widgets["analysis_passes"]
        self.workbench._set_text_widget_value(text_widget, "fast|heuristic|70|strict|10||")
        self.assertEqual(text_widget.get("1.0", tk.END).strip(), "fast|heuristic|70|strict|10||")

        with patch("ui.desktop_app.filedialog.askopenfilename", return_value=""):
            self.workbench._load_config_file()

        self.workbench.profile_combo.set("")
        self.workbench.scalar_vars["profile_name"].set("")
        self.workbench._load_profile()

        class FakeThread:
            def __init__(self, target=None, daemon=None):  # noqa: ANN001
                self._target = target
                self._alive = False

            def start(self):
                self._alive = True
                if self._target:
                    self._target()
                self._alive = False

            def is_alive(self):
                return self._alive

        class BrokenController:
            def __init__(self, config, event_sink=None):  # noqa: ANN001
                self.config = config
                self.event_sink = event_sink

            def run(self):
                raise RuntimeError("worker boom")

            def request_stop(self):
                return None

        with patch("ui.desktop_app.PipelineController", BrokenController), patch(
            "ui.desktop_app.threading.Thread", FakeThread
        ), patch("ui.desktop_app.messagebox.showerror") as showerror, patch.object(self.workbench.root, "after", return_value=None):
            self.workbench._start_run(skip_discovery_override=True, run_mode_override="collect")
            self.workbench._poll_messages()
        showerror.assert_called_once()
        self.assertTrue(self.workbench.status_var.get().startswith("Run failed:"))

        self.workbench._emit_worker_event({"event_type": "custom"})
        self.assertEqual(self.workbench.message_queue.get_nowait()[0], "event")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "papers.csv"
            pd.DataFrame([{"title": "Paper A"}]).to_csv(csv_path, index=False)
            tree = self.workbench.treeviews["all_papers"]
            tree["columns"] = ("dummy",)
            tree.insert("", tk.END, values=["old"])
            self.workbench._load_dataframe_into_tree("all_papers", csv_path)
            self.assertNotIn("old", str(tree.item(tree.get_children()[0]).get("values")))

        with patch("ui.desktop_app.form_values_to_config", return_value=SimpleNamespace(results_dir=Path("results/mock"))), patch.object(
            self.workbench, "_load_dataframe_into_tree"
        ) as load_tree:
            self.workbench._refresh_all_table()
        load_tree.assert_called_once()

        outputs_tree = self.workbench.outputs_tree
        outputs_tree.insert("", tk.END, values=["old", "value"])
        self.workbench._load_outputs({"ignored": 1})
        self.assertEqual(outputs_tree.get_children(), ())
        self.workbench.outputs_tree = None
        self.workbench._load_outputs({"a": "b"})
        self.workbench.outputs_tree = outputs_tree

        self.workbench.outputs_tree.selection_remove(self.workbench.outputs_tree.selection())
        self.workbench._open_selected_output()
        self.workbench.outputs_tree.insert("", tk.END, values=["only-one"])
        item = self.workbench.outputs_tree.get_children()[-1]
        self.workbench.outputs_tree.selection_set(item)
        self.workbench._open_selected_output()

        with patch("ui.desktop_app.subprocess.run") as run_mock, patch("ui.desktop_app.os.name", "posix"), patch(
            "ui.desktop_app.sys.platform", "darwin"
        ):
            temp_file = str(self.workbench.root.tk.call("info", "nameofexecutable"))
            path = Path(temp_file)
            self.workbench._open_path(path)
        run_mock.assert_called_once()

        controller = Mock()
        self.workbench.current_controller = controller
        with patch.object(self.workbench.root_logger, "removeHandler") as remove_handler, patch.object(
            self.workbench.root, "destroy"
        ) as destroy:
            self.workbench._on_close()
        controller.request_stop.assert_called_once()
        remove_handler.assert_called_once()
        destroy.assert_called_once()
        del self.workbench

    def test_launch_desktop_app_wrapper(self) -> None:
        with patch("ui.desktop_app.DesktopWorkbench") as workbench_cls:
            workbench_cls.return_value.run.return_value = 7
            self.assertEqual(launch_desktop_app(SimpleNamespace(config_file=None)), 7)


if __name__ == "__main__":  # pragma: no cover - direct module execution helper
    unittest.main()
