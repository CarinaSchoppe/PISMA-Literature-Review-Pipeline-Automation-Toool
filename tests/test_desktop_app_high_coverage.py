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

    def test_scroll_visibility_and_search_guard_branches(self) -> None:
        self.workbench.settings_search_var.set("definitely-no-setting")
        self.workbench._refresh_settings_search_results()
        self.assertEqual(self.workbench.settings_search_choice_var.get(), "")

        self.workbench._activate_settings_canvas(None)
        self.assertIsNone(self.workbench.settings_canvas)
        self.assertIsNone(self.workbench._on_settings_mousewheel(SimpleNamespace(delta=120)))
        self.assertIsNone(self.workbench._on_settings_mousewheel(SimpleNamespace(delta=0, num=0)))

        canvas = Mock()
        self.workbench._activate_settings_canvas(canvas)
        self.assertEqual(self.workbench._on_settings_mousewheel(SimpleNamespace(delta=0, num=4)), "break")
        self.assertEqual(self.workbench._on_settings_mousewheel(SimpleNamespace(delta=0, num=5)), "break")
        self.assertIsNone(self.workbench._on_settings_mousewheel(SimpleNamespace(delta=0, num=0)))
        self.assertEqual(canvas.yview_scroll.call_count, 2)

        original_notebook = self.workbench.settings_pages_notebook
        self.workbench.settings_pages_notebook = None
        self.workbench._handle_settings_page_changed()
        self.workbench._apply_settings_page_visibility()
        self.workbench.settings_pages_notebook = original_notebook

        with patch.object(self.workbench.settings_pages_notebook, "select", return_value=""):
            self.workbench._handle_settings_page_changed()
        self.assertIsNone(self.workbench.settings_canvas)

        class FakeNotebook:
            def __init__(self, hidden_page):
                self.hidden_page = hidden_page
                self.selected = hidden_page
                self.states = {hidden_page: "hidden", "basic": "normal"}

            def tab(self, tab_id, option=None, **kwargs):
                if kwargs:
                    if "state" in kwargs:
                        self.states[tab_id] = kwargs["state"]
                    return None
                if option == "state":
                    return self.states[tab_id]
                if option == "text":
                    return tab_id
                return None

            def tabs(self):
                return ["basic", self.hidden_page]

            def select(self, tab_id=None):
                if tab_id is not None:
                    self.selected = tab_id
                return self.selected

        advanced_page = self.workbench.settings_page_frames["Advanced Runtime"]
        fake_notebook = FakeNotebook(advanced_page)
        original_notebook = self.workbench.settings_pages_notebook
        self.workbench.settings_pages_notebook = fake_notebook
        self.workbench.show_advanced_settings.set(False)
        self.workbench._apply_settings_page_visibility()
        self.assertEqual(fake_notebook.selected, "basic")
        self.workbench.settings_pages_notebook = original_notebook

    def test_scroll_and_output_guard_branches(self) -> None:
        widget = self.workbench.field_focus_widgets["database_path"]
        self.workbench.settings_canvas = None
        self.workbench._scroll_widget_into_view(widget)

        self.workbench.settings_canvas = Mock()
        self.workbench.settings_page_canvases = {}
        self.workbench.settings_page_content_frames = {}
        self.workbench._scroll_widget_into_view(widget)

        fake_canvas = Mock()
        fake_canvas.update_idletasks = Mock()
        fake_canvas.yview.return_value = (0.6, 0.8)
        fake_content = Mock()
        fake_content.update_idletasks = Mock()
        fake_content.winfo_height.return_value = 1000
        fake_content.winfo_rooty.return_value = 100
        fake_widget = Mock()
        fake_widget.update_idletasks = Mock()
        fake_widget.winfo_rooty.return_value = 200
        fake_widget.winfo_height.return_value = 40
        self.workbench.settings_canvas = fake_canvas
        self.workbench.settings_page_canvases = {"Storage and Output": fake_canvas}
        self.workbench.settings_page_content_frames = {"Storage and Output": fake_content}
        self.workbench._scroll_widget_into_view(fake_widget)
        fake_canvas.yview_moveto.assert_called_once()

        fake_canvas.reset_mock()
        fake_canvas.update_idletasks.side_effect = tk.TclError("bad canvas")
        self.workbench._scroll_widget_into_view(fake_widget)

        self.workbench.outputs_tree = None
        self.workbench._open_selected_output()

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "file.txt"
            path.write_text("x", encoding="utf-8")
            with patch("ui.desktop_app.subprocess.run") as run_mock, patch(
                "ui.desktop_app.os.name", "posix"
            ), patch("ui.desktop_app.sys.platform", "linux"):
                self.workbench._open_path(path)
            run_mock.assert_called_once()

    def test_new_inspector_picker_and_page_selection_branches(self) -> None:
        self.workbench.quick_destination_var.set("")
        with patch.object(self.workbench, "_focus_field") as focus_mock, patch.object(
            self.workbench, "_open_pass_builder"
        ) as pass_mock:
            self.workbench._open_selected_destination()
        focus_mock.assert_not_called()
        pass_mock.assert_not_called()

        self.workbench.quick_destination_var.set("Pass chain editor")
        with patch.object(self.workbench, "_focus_field") as focus_mock, patch.object(
            self.workbench, "_open_pass_builder"
        ) as pass_mock:
            self.workbench._open_selected_destination()
        focus_mock.assert_called_once_with("analysis_passes")
        pass_mock.assert_called_once()

        self.workbench.quick_destination_var.set("Verbose logging")
        with patch.object(self.workbench, "_focus_field") as focus_mock:
            self.workbench._open_selected_destination()
        focus_mock.assert_called_once_with("verbosity")
        self.workbench._focus_field("verbosity")
        self.assertEqual(
            self.workbench.active_settings_page_description_var.get(),
            self.workbench.SETTINGS_PAGE_DESCRIPTIONS["Advanced Runtime"],
        )

        self.workbench.guide_choice_var.set("")
        with patch.object(self.workbench, "_open_handbook_entry") as open_mock:
            self.workbench._open_selected_guide_shortcut()
        open_mock.assert_not_called()

        self.workbench.guide_choice_var.set("Model guide")
        with patch.object(self.workbench, "_open_handbook_entry") as open_mock:
            self.workbench._open_selected_guide_shortcut()
        open_mock.assert_called_once_with("guide:models")

        original_notebook = self.workbench.settings_pages_notebook
        self.workbench.settings_pages_notebook = None
        self.workbench._select_settings_page("Review Setup")
        self.workbench.settings_pages_notebook = original_notebook
        self.workbench._select_settings_page("Missing Page")

        self.workbench.show_advanced_settings.set(False)
        with patch.object(self.workbench, "_apply_settings_page_visibility") as apply_mock:
            self.workbench._select_settings_page("Advanced Runtime")
        apply_mock.assert_called_once()
        self.assertTrue(self.workbench.show_advanced_settings.get())

    def test_help_expansion_and_handbook_guard_branches(self) -> None:
        original_examples = dict(self.workbench.FIELD_HELP_EXAMPLES)
        try:
            self.workbench.FIELD_HELP_EXAMPLES["custom_enabled"] = "turn it on for this workflow"
            self.workbench.FIELD_HELP_EXAMPLES["llm_provider"] = "pick the provider that should handle screening"
            self.workbench.FIELD_HELP_EXAMPLES["relevance_threshold"] = "75 keeps only stronger matches"
            self.workbench.FIELD_HELP_EXAMPLES["custom_misc"] = "store a plain custom value here"

            self.assertIn("Example: turn it on", self.workbench._help_text_for_field("custom_enabled"))
            self.assertIn("Example: pick the provider", self.workbench._help_text_for_field("llm_provider"))
            self.assertIn("Example: 75 keeps", self.workbench._help_text_for_field("relevance_threshold"))
            self.assertIn("Example: store a plain custom value here", self.workbench._expand_help_text("custom_misc", "Base"))
        finally:
            self.workbench.FIELD_HELP_EXAMPLES.clear()
            self.workbench.FIELD_HELP_EXAMPLES.update(original_examples)

        handbook_tree = self.workbench.handbook_tree
        self.workbench.handbook_tree = None
        self.workbench._refresh_handbook_tree()
        self.workbench.handbook_tree = handbook_tree
        handbook_tree.selection_set(next(iter(self.workbench.handbook_entries.keys())))
        self.workbench._handle_handbook_selection(None)

    def test_handbook_path_and_analysis_pass_guard_branches(self) -> None:
        handbook_tree = self.workbench.handbook_tree
        handbook_text = self.workbench.handbook_text

        self.workbench.handbook_tree = None
        self.workbench._handle_handbook_selection(None)
        self.workbench.handbook_tree = handbook_tree
        self.workbench.handbook_tree.selection_remove(self.workbench.handbook_tree.selection())
        self.workbench._handle_handbook_selection(None)
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
        tree.selection_remove(tree.selection())
        tree.event_generate("<<TreeviewSelect>>")

        tree.selection_remove("0")
        _find_button(dialog, "Remove Pass").invoke()
        _find_button(dialog, "Move Down").invoke()
        tree.selection_set("0")
        _find_button(dialog, "Move Up").invoke()
        _find_button(dialog, "Apply").invoke()

        passes = self.workbench._current_analysis_passes()
        self.assertTrue(passes)

        self.workbench._open_pass_builder()
        validation_dialog = [
            widget for widget in self.workbench.root.winfo_children() if isinstance(widget, tk.Toplevel)
        ][-1]
        with patch("ui.desktop_app.messagebox.showerror") as showerror:
            self.assertFalse(self.workbench._validate_pass_builder_name("", validation_dialog))
        showerror.assert_called_once()
        validation_dialog.destroy()

        self.workbench._open_pass_builder()
        append_dialog = [widget for widget in self.workbench.root.winfo_children() if isinstance(widget, tk.Toplevel)][-1]
        tree = next(widget for widget in _walk_widgets(append_dialog) if widget.winfo_class() == "Treeview")
        tree.selection_set("0")
        tree.event_generate("<<TreeviewSelect>>")
        tree.selection_remove(tree.selection())
        before_count = len(self.workbench._current_analysis_passes())
        _find_button(append_dialog, "Update Pass").invoke()
        _find_button(append_dialog, "Apply").invoke()
        appended = self.workbench._current_analysis_passes()
        self.assertEqual(len(appended), before_count + 1)

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
        with patch.object(self.workbench, "_set_status") as set_status, patch("ui.desktop_app.PipelineController", BrokenController), patch(
            "ui.desktop_app.threading.Thread", FakeThread
        ), patch.object(self.workbench.root, "after", return_value=None):
            self.workbench._start_run(skip_discovery_override=True, run_mode_override="analyze")
        set_status.assert_any_call("Running analysis from stored records...")

        self.workbench.current_controller = controller
        with patch.object(self.workbench.root_logger, "removeHandler") as remove_handler, patch.object(
            self.workbench.root, "destroy"
        ) as destroy, patch.object(
            self.workbench.root, "unbind_all", side_effect=[tk.TclError("x"), tk.TclError("y"), tk.TclError("z")]
        ) as unbind_all:
            self.workbench._on_close()
        controller.request_stop.assert_called_once()
        remove_handler.assert_called_once()
        self.assertEqual(unbind_all.call_count, 3)
        destroy.assert_called_once()
        del self.workbench

    def test_launch_desktop_app_wrapper(self) -> None:
        with patch("ui.desktop_app.DesktopWorkbench") as workbench_cls:
            workbench_cls.return_value.run.return_value = 7
            self.assertEqual(launch_desktop_app(SimpleNamespace(config_file=None)), 7)


if __name__ == "__main__":  # pragma: no cover - direct module execution helper
    unittest.main()
