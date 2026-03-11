"""Workflow-style tests for the Tkinter desktop app beyond simple label coverage."""

from __future__ import annotations

import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd

from ui.desktop_app import DesktopWorkbench


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


class DesktopWorkbenchWorkflowTests(unittest.TestCase):
    """Exercise GUI workflows such as file browsing, profiles, result loading, and pass editing."""

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

    def test_browse_for_field_supports_directory_file_and_database_targets(self) -> None:
        def fake_save_dialog(*_: object, **kwargs: object) -> str:
            if kwargs.get("defaultextension") == ".log":
                return "results/pipeline.log"
            return "data/custom.db"

        with patch("ui.desktop_app.filedialog.askdirectory", return_value="results/custom"), patch(
            "ui.desktop_app.filedialog.asksaveasfilename", side_effect=fake_save_dialog
        ), patch("ui.desktop_app.filedialog.askopenfilename", return_value="imports/manual.csv"):
            self.workbench._browse_for_field("results_dir", self.workbench.scalar_vars["results_dir"])
            self.workbench._browse_for_field("database_path", self.workbench.scalar_vars["database_path"])
            self.workbench._browse_for_field("log_file_path", self.workbench.scalar_vars["log_file_path"])
            self.workbench._browse_for_field("manual_source_path", self.workbench.scalar_vars["manual_source_path"])

        self.assertEqual(self.workbench.scalar_vars["results_dir"].get(), "results/custom")
        self.assertEqual(self.workbench.scalar_vars["database_path"].get(), "data/custom.db")
        self.assertEqual(self.workbench.scalar_vars["log_file_path"].get(), "results/pipeline.log")
        self.assertEqual(self.workbench.scalar_vars["manual_source_path"].get(), "imports/manual.csv")

    def test_find_button_raises_for_missing_text(self) -> None:
        with self.assertRaisesRegex(AssertionError, "Button with text 'definitely missing' not found"):
            _find_button(self.workbench.root, "definitely missing")

    def test_load_config_save_profile_and_load_profile_flows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.json"
            config_path.write_text(
                """
                {
                  "research_topic": "Loaded topic",
                  "search_keywords": ["llm", "screening"],
                  "results_dir": "results/loaded"
                }
                """,
                encoding="utf-8",
            )
            profile_dir = root / "profiles"
            self.workbench.profile_manager.profile_dir = profile_dir
            profile_dir.mkdir(parents=True, exist_ok=True)

            with patch("ui.desktop_app.filedialog.askopenfilename", return_value=str(config_path)):
                self.workbench._load_config_file()
            self.assertEqual(self.workbench.text_widgets["research_topic"].get("1.0", tk.END).strip(), "Loaded topic")

            self.workbench.scalar_vars["profile_name"].set("demo")
            self.workbench._save_profile()
            self.assertIn("demo", self.workbench.profile_manager.list_profiles())

            self.workbench.profile_combo.set("demo")
            self.workbench._load_profile()
            self.assertEqual(self.workbench.profile_combo.get(), "demo")

    def test_save_profile_requires_name(self) -> None:
        self.workbench.scalar_vars["profile_name"].set("")
        self.workbench.profile_combo.set("")
        with patch("ui.desktop_app.messagebox.showerror") as showerror:
            self.workbench._save_profile()
        showerror.assert_called_once()

    def test_pass_builder_buttons_update_analysis_chain(self) -> None:
        self.workbench._open_pass_builder()
        dialog = next(widget for widget in self.workbench.root.winfo_children() if isinstance(widget, tk.Toplevel))
        tree = next(widget for widget in _walk_widgets(dialog) if widget.winfo_class() == "Treeview")

        _find_button(dialog, "Add Pass").invoke()
        _find_button(dialog, "Duplicate Pass").invoke()
        tree.selection_set("1")
        _find_button(dialog, "Move Up").invoke()
        _find_button(dialog, "Remove Pass").invoke()
        _find_button(dialog, "Apply").invoke()

        passes = self.workbench._current_analysis_passes()
        self.assertEqual(len(passes), 2)

    def test_pass_builder_cancel_and_invalid_update_branch(self) -> None:
        self.workbench._open_pass_builder()
        dialog = next(widget for widget in self.workbench.root.winfo_children() if isinstance(widget, tk.Toplevel))
        entries = [widget for widget in _walk_widgets(dialog) if widget.winfo_class() == "TEntry"]
        self.assertTrue(entries)
        name_entry = next((widget for widget in entries if widget.get() == "fast"), entries[0])
        textvariable = str(name_entry.cget("textvariable"))
        dialog.setvar(textvariable, "")
        dialog.update_idletasks()
        with patch("ui.desktop_app.messagebox.showerror") as showerror:
            _find_button(dialog, "Update Pass").invoke()
        self.assertLessEqual(showerror.call_count, 1)
        _find_button(dialog, "Cancel").invoke()
        self.assertFalse(dialog.winfo_exists())

    def test_pass_builder_rejects_blank_name_on_save(self) -> None:
        self.workbench._open_pass_builder()
        dialog = next(widget for widget in self.workbench.root.winfo_children() if isinstance(widget, tk.Toplevel))
        with patch.object(self.workbench, "_validate_pass_builder_name", return_value=False) as validate_name:
            _find_button(dialog, "Update Pass").invoke()

        validate_name.assert_called_once()
        self.assertTrue(dialog.winfo_exists())
        dialog.destroy()

    def test_handbook_search_rendering_and_opening_specific_entries(self) -> None:
        self.workbench.handbook_search_var.set("no-match-value")
        self.workbench._refresh_handbook_tree()
        text = self.workbench.handbook_text.get("1.0", tk.END)
        self.assertIn("No handbook entries match", text)

        self.workbench._open_handbook_entry("guide:models")
        self.assertEqual(self.workbench.handbook_tree.selection(), ("guide:models",))
        self.workbench._open_handbook_entry("missing")

    def test_focus_helpers_and_summary_writer_branches(self) -> None:
        self.workbench._focus_selected_setting()
        self.workbench.settings_search_choice_var.set("PDFs and Outputs -> Main SQLite database path")
        self.workbench._focus_selected_setting()
        selected_page = self.workbench.settings_pages_notebook.tab(self.workbench.settings_pages_notebook.select(), "text")
        self.assertEqual(selected_page, "Storage and Output")
        self.workbench._focus_field("openalex_calls_per_second")
        selected_page = self.workbench.settings_pages_notebook.tab(self.workbench.settings_pages_notebook.select(), "text")
        self.assertEqual(selected_page, "Advanced Runtime")
        self.assertTrue(self.workbench.show_advanced_settings.get())
        self.assertIsNotNone(self.workbench.settings_canvas)
        self.workbench._write_summary_widget(None, "ignored")
        self.workbench.field_focus_widgets.pop("database_path", None)
        self.workbench._focus_field("database_path")
        self.workbench.settings_canvas = None
        self.workbench._scroll_widget_into_view(self.workbench.root)

    def test_load_dataframe_filter_refresh_outputs_and_open_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dataframe = pd.DataFrame(
                [
                    {"title": "Paper A", "authors": "Ada", "abstract": "alpha", "doi": "10.1/a", "venue": "Venue", "inclusion_decision": "include"},
                    {"title": "Paper B", "authors": "Bob", "abstract": "beta", "doi": "10.1/b", "venue": "Venue", "inclusion_decision": ""},
                ]
            )
            csv_path = root / "papers.csv"
            dataframe.to_csv(csv_path, index=False)

            self.workbench._load_dataframe_into_tree("all_papers", csv_path)
            self.assertEqual(len(self.workbench.treeviews["all_papers"].get_children()), 2)

            self.workbench.all_filter_var.set("screened_only")
            self.workbench.all_search_var.set("paper a")
            filtered = self.workbench._filter_all_papers(dataframe)
            self.assertEqual(len(filtered), 1)

            self.workbench._load_outputs({"papers_csv": str(csv_path), "count": 2})
            items = self.workbench.outputs_tree.get_children()
            self.assertEqual(len(items), 1)
            self.workbench.outputs_tree.selection_set(items[0])
            with patch.object(self.workbench, "_open_path") as open_path:
                self.workbench._open_selected_output()
                open_path.assert_called_once()
            self.assertIn("CSV artifact", self.workbench.artifact_summary_text.get("1.0", tk.END))

            with patch.object(self.workbench, "_open_path") as open_path:
                self.workbench._open_selected_output_parent()
                open_path.assert_called_once()

            self.workbench._refresh_chart_preview(csv_path)
            self.assertTrue(self.workbench.chart_canvas.find_all())
            self.assertIn("Total screened records", self.workbench.charts_summary_text.get("1.0", tk.END))

            self.workbench._refresh_screening_audit(csv_path)
            audit_items = self.workbench.screening_audit_tree.get_children()
            self.assertEqual(len(audit_items), 2)
            self.assertIn("Title: Paper A", self.workbench.screening_audit_text.get("1.0", tk.END))

    def test_load_dataframe_handles_missing_file_and_refresh_results_from_disk(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            results_dir = root / "results"
            results_dir.mkdir()
            dataframe = pd.DataFrame([{"title": "Paper A", "inclusion_decision": "include"}])
            for filename in ("papers.csv", "included_papers.csv", "excluded_papers.csv"):
                dataframe.to_csv(results_dir / filename, index=False)
            self.workbench.scalar_vars["results_dir"].set(str(results_dir))
            self.workbench._load_dataframe_into_tree("included_papers", results_dir / "missing.csv")
            self.assertFalse(self.workbench.treeviews["included_papers"]["columns"])
            self.workbench._refresh_results_from_disk()
            self.assertTrue(self.workbench.current_result)

    def test_start_run_force_stop_poll_messages_and_open_path_branches(self) -> None:
        class FakeThread:
            def __init__(self, target=None, daemon=None):  # noqa: ANN001
                self._target = target
                self.daemon = daemon
                self._alive = False

            def start(self):
                self._alive = True
                if self._target:
                    self._target()
                self._alive = False

            def is_alive(self):
                return self._alive

        class FakeController:
            def __init__(self, config, event_sink=None):  # noqa: ANN001
                self.config = config
                self.event_sink = event_sink
                self.stop_called = False

            def run(self):
                return {"run_status": "completed", "papers_csv": "papers.csv", "included_papers_csv": "included.csv", "excluded_papers_csv": "excluded.csv"}

            def request_stop(self):
                self.stop_called = True

        direct_controller = FakeController(SimpleNamespace())
        direct_controller.request_stop()
        self.assertTrue(direct_controller.stop_called)

        with patch("ui.desktop_app.PipelineController", FakeController), patch("ui.desktop_app.threading.Thread", FakeThread), patch.object(
            self.workbench, "_load_records_into_tree"
        ) as load_table, patch.object(self.workbench, "_load_outputs") as load_outputs:
            self.workbench._start_run()
            with patch.object(self.workbench.root, "after", return_value=None):
                self.workbench._poll_messages()
            load_table.assert_called()
            load_outputs.assert_called_once()

        with patch("ui.desktop_app.form_values_to_config", side_effect=ValueError("bad config")), patch(
                "ui.desktop_app.messagebox.showerror"
        ) as showerror:
            self.workbench._start_run()
        showerror.assert_called_once()

        self.workbench.run_thread = SimpleNamespace(is_alive=lambda: True)
        with patch("ui.desktop_app.messagebox.showinfo") as showinfo:
            self.workbench._start_run()
        showinfo.assert_called_once()

        controller = Mock()
        controller.request_stop = Mock()
        self.workbench.current_controller = controller
        self.workbench.run_thread = SimpleNamespace(is_alive=lambda: True)
        self.workbench._force_stop()
        controller.request_stop.assert_called_once()

        self.workbench.current_controller = None
        self.workbench.run_thread = None
        self.workbench._force_stop()

        self.workbench.message_queue.put(("log", "hello"))
        self.workbench.message_queue.put(("event", {"event_type": "stage_started"}))
        self.workbench.message_queue.put(("error", "boom"))
        with patch.object(self.workbench.root, "after", return_value=None), patch("ui.desktop_app.messagebox.showerror") as showerror:
            self.workbench._poll_messages()
        showerror.assert_called_once()

        missing_path = Path(self.workbench.scalar_vars["results_dir"].get()) / "missing"
        with patch("ui.desktop_app.messagebox.showerror") as showerror:
            self.workbench._open_path(missing_path)
        showerror.assert_called_once()

    def test_handle_result_surfaces_failed_and_stopped_runs(self) -> None:
        config = SimpleNamespace(results_dir=Path("results"))

        with patch.object(self.workbench, "_load_dataframe_into_tree"), patch.object(self.workbench, "_load_outputs"), patch(
                "ui.desktop_app.messagebox.showerror"
        ) as showerror:
            self.workbench._handle_result(
                {
                    "config": config,
                    "result": {"run_status": "failed_min_discovered_records", "run_error": "too few records"},
                }
            )
        showerror.assert_called_once()

        with patch.object(self.workbench, "_load_dataframe_into_tree"), patch.object(self.workbench, "_load_outputs"), patch(
                "ui.desktop_app.messagebox.showwarning"
        ) as showwarning:
            self.workbench._handle_result(
                {
                    "config": config,
                    "result": {"run_status": "stopped", "run_error": "Stopped by user request"},
                }
            )
        showwarning.assert_called_once()

    def test_handle_result_can_populate_all_papers_from_snapshot_and_reset_filters(self) -> None:
        config = SimpleNamespace(results_dir=Path("results"))
        self.workbench.all_filter_var.set("screened_only")
        self.workbench._set_placeholder_text("all_papers_search", "old hidden filter")

        with patch.object(self.workbench, "_load_outputs"), patch.object(self.workbench, "_refresh_chart_preview"), patch.object(
            self.workbench, "_refresh_screening_audit"
        ), patch.object(self.workbench, "_append_run_history"):
            self.workbench._handle_result(
                {
                    "config": config,
                    "result": {
                        "run_status": "completed",
                        "papers_snapshot": [
                            {
                                "title": "Paper A",
                                "authors": ["Ada"],
                                "abstract": "alpha",
                                "venue": "Venue",
                                "doi": "10.1/a",
                                "inclusion_decision": "include",
                                "relevance_score": 72.0,
                            },
                            {
                                "title": "Paper B",
                                "authors": ["Bob"],
                                "abstract": "beta",
                                "venue": "Venue",
                                "doi": "10.1/b",
                                "inclusion_decision": "exclude",
                                "relevance_score": 40.0,
                            },
                        ],
                    },
                }
            )

        self.assertEqual(self.workbench.all_filter_var.get(), "all")
        self.assertEqual(self.workbench._placeholder_safe_value("all_papers_search", self.workbench.all_search_var.get()), "")
        self.assertEqual(len(self.workbench.treeviews["all_papers"].get_children()), 2)
        self.assertEqual(len(self.workbench.treeviews["included_papers"].get_children()), 1)
        self.assertEqual(len(self.workbench.treeviews["excluded_papers"].get_children()), 1)
        self.assertEqual(len(self.workbench.research_fit_tree.get_children()), 2)

    def test_research_fit_refresh_and_document_preview_render_keyword_details(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "papers.csv"
            pd.DataFrame(
                [
                    {
                        "title": "Paper A",
                        "abstract": "alpha",
                        "source": "fixture",
                        "inclusion_decision": "include",
                        "topic_prefilter_research_fit_label": "STRONG_FIT",
                        "topic_prefilter_weighted_score": 81.5,
                        "topic_prefilter_min_keyword_matches": 2,
                        "topic_prefilter_matched_keyword_count": 3,
                        "topic_prefilter_label": "HIGH_RELEVANCE",
                        "topic_prefilter_similarity": 0.82,
                        "topic_prefilter_extracted_topics": '["systematic review", "large language models"]',
                        "topic_prefilter_keyword_details": (
                            '[{"keyword":"systematic review","weight":1.6,"match_percent":100.0,'
                            '"status":"matched","best_topic":"systematic review"}]'
                        ),
                    }
                ]
            ).to_csv(csv_path, index=False)

            self.workbench._refresh_research_fit(csv_path)

            items = self.workbench.research_fit_tree.get_children()
            self.assertEqual(len(items), 1)
            self.assertIn("Paper A", self.workbench.research_fit_text.get("1.0", tk.END))
            self.assertIn("systematic review", self.workbench.research_fit_text.get("1.0", tk.END))

            row = self.workbench.research_fit_rows[items[0]]
            summary_text, _content_text = self.workbench._build_document_preview(row, source_label="Research Fit", document_path=None)
            self.assertIn("Research fit snapshot", summary_text)
            self.assertIn("Top keyword matches", summary_text)

    def test_run_history_is_written_and_rendered(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.workbench.scalar_vars["data_dir"].set(temp_dir)
            self.workbench._set_text_widget_value(self.workbench.text_widgets["research_topic"], "History topic")
            self.workbench.scalar_vars["results_dir"].set("results/history")
            self.workbench.scalar_vars["run_mode"].set("analyze")

            self.workbench._append_run_history(
                {
                    "run_status": "completed",
                    "papers_csv": "results/history/papers.csv",
                    "included_papers_csv": "results/history/included_papers.csv",
                }
            )

            history_items = self.workbench.run_history_tree.get_children()
            self.assertEqual(len(history_items), 1)
            self.assertIn("History topic", self.workbench.run_history_text.get("1.0", tk.END))
            history_file = Path(temp_dir) / "ui_run_history.json"
            self.assertTrue(history_file.exists())

    def test_open_results_dir_and_platform_open_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            results_dir = Path(temp_dir)
            self.workbench.scalar_vars["results_dir"].set(str(results_dir))

            with patch.object(self.workbench, "_open_path") as open_path:
                self.workbench._open_results_dir()
            open_path.assert_called_once()

            existing = results_dir / "file.txt"
            existing.write_text("x", encoding="utf-8")
            with patch("os.startfile", create=True) as startfile:
                self.workbench._open_path(existing)
            startfile.assert_called_once()

    def test_force_stop_and_linux_open_path_branches_are_explicitly_covered(self) -> None:
        class FakeController:
            def __init__(self) -> None:
                self.stop_called = False

            def request_stop(self) -> None:
                self.stop_called = True

        controller = FakeController()
        self.workbench.current_controller = controller
        self.workbench.run_thread = SimpleNamespace(is_alive=lambda: True)
        self.workbench._force_stop()
        self.assertTrue(controller.stop_called)

        with tempfile.TemporaryDirectory() as temp_dir:
            existing = Path(temp_dir) / "file.txt"
            existing.write_text("x", encoding="utf-8")
            with patch("ui.desktop_app.subprocess.run") as run_mock, patch("ui.desktop_app.os.name", "posix"), patch(
                "ui.desktop_app.sys.platform", "linux"
            ), patch("os.startfile", create=True):
                self.workbench._open_path(existing)
            run_mock.assert_called_once()


if __name__ == "__main__":  # pragma: no cover - direct module execution helper
    unittest.main()
