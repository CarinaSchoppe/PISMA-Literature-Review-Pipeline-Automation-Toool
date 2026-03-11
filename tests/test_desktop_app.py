"""Tests for guided desktop UI helpers such as hover help and field explanations."""

from __future__ import annotations

import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace

from config import ApiSettings, ResearchConfig
from ui.desktop_app import DesktopWorkbench


def _walk_widgets(widget: tk.Misc):
    """Yield one widget and all descendants for Tkinter lookup assertions."""

    yield widget
    for child in widget.winfo_children():
        yield from _walk_widgets(child)


class DesktopWorkbenchTests(unittest.TestCase):
    """Verify the guided desktop UI exposes contextual help for key settings."""

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

    def test_hover_help_is_enabled_by_default(self) -> None:
        self.assertTrue(self.workbench.hover_help_enabled.get())

    def test_source_fields_have_descriptive_help_text(self) -> None:
        self.assertIn("OpenAlex", self.workbench._help_text_for_field("openalex_enabled"))
        self.assertIn("Crossref", self.workbench._help_text_for_field("crossref_enabled"))
        self.assertIn("Springer", self.workbench._help_text_for_field("springer_enabled"))
        self.assertIn("Semantic Scholar", self.workbench._help_text_for_field("semantic_scholar_enabled"))
        self.assertIn("temperature", self.workbench._help_text_for_field("llm_temperature").lower())
        self.assertIn("Gemini", self.workbench._help_text_for_field("gemini_model"))
        self.assertIn("rate", self.workbench._help_text_for_field("semantic_scholar_calls_per_second").lower())
        self.assertIn("cache", self.workbench._help_text_for_field("clear_screening_cache").lower())
        self.assertIn("partial rerun", self.workbench._help_text_for_field("partial_rerun_mode").lower())
        self.assertIn("cache", self.workbench._help_text_for_field("http_cache_enabled").lower())
        self.assertIn("Retry-After", self.workbench._help_text_for_field("http_retry_base_delay_seconds"))
        self.assertIn("If you set this to Yes", self.workbench._help_text_for_field("download_pdfs"))
        self.assertIn("If you set this to No", self.workbench._help_text_for_field("download_pdfs"))
        self.assertIn("Available choices", self.workbench._help_text_for_field("llm_provider"))
        self.assertIn("Example path", self.workbench._help_text_for_field("database_path"))
        self.assertIn("What higher values do", self.workbench._help_text_for_field("relevance_threshold"))

    def test_core_user_facing_files_are_english_only(self) -> None:
        paths = (
            Path("README.md"),
            Path("HANDBOOK.md"),
            Path("config.py"),
            Path("main.py"),
            Path("ui/desktop_app.py"),
            Path("ui/view_model.py"),
        )
        forbidden_terms = (" beispiel", " erklaer", " erklär", " deutsch", " englisch", " ja ", " nein ")
        for path in paths:
            text = path.read_text(encoding="utf-8-sig").lower()
            self.assertEqual([term for term in forbidden_terms if term in text], [], str(path))

    def test_output_labels_are_explicit_in_settings_ui(self) -> None:
        self.assertEqual(self.workbench.LABELS["boolean_operators"], "Boolean operators")
        self.assertEqual(self.workbench.LABELS["discovery_strategy"], "Discovery strategy")
        self.assertEqual(self.workbench.LABELS["llm_provider"], "LLM provider")
        self.assertEqual(self.workbench.LABELS["download_pdfs"], "Download paper PDFs")
        self.assertEqual(self.workbench.LABELS["output_sqlite_exports"], "Write SQLite exports")
        self.assertEqual(self.workbench.LABELS["database_path"], "Main SQLite database path")
        self.assertEqual(self.workbench.LABELS["results_dir"], "Results directory")
        self.assertEqual(self.workbench.LABELS["gemini_model"], "Gemini model")
        self.assertEqual(self.workbench.LABELS["discovery_workers"], "Discovery workers")
        self.assertEqual(self.workbench.LABELS["reset_query_records"], "Reset stored query records")
        self.assertEqual(self.workbench.LABELS["openalex_calls_per_second"], "OpenAlex calls / second")
        self.assertEqual(self.workbench.LABELS["partial_rerun_mode"], "Partial rerun mode")
        self.assertEqual(self.workbench.LABELS["http_cache_enabled"], "Enable HTTP source cache")
        self.assertEqual(self.workbench.LABELS["http_cache_dir"], "HTTP cache directory")
        self.assertEqual(self.workbench.LABELS["pdf_batch_size"], "PDF batch size")

    def test_gui_covers_all_runtime_fields_and_toolbar_actions(self) -> None:
        config_fields = set(ResearchConfig.model_fields.keys()) - {"api_settings", "query_key"}
        api_fields = set(ApiSettings.model_fields.keys())
        grouped_fields = set()
        for _, fields in self.workbench.GROUPS:
            grouped_fields.update(fields)
        widget_fields = set(self.workbench.text_widgets.keys()) | set(self.workbench.scalar_vars.keys())

        self.assertTrue((config_fields | api_fields).issubset(grouped_fields))
        self.assertTrue(grouped_fields.issubset(widget_fields))
        self.assertIn("analysis_passes", self.workbench.text_widgets)

        toolbar_texts: list[str] = []
        for widget in _walk_widgets(self.workbench.root):
            try:
                text = widget.cget("text")
            except tk.TclError:
                continue
            if text:
                toolbar_texts.append(text)

        self.assertIn("Analyze Stored Results", toolbar_texts)
        self.assertIn("Force Stop", toolbar_texts)

    def test_slider_fields_exist_for_threshold_controls(self) -> None:
        for field_name in ("relevance_threshold", "maybe_threshold_margin", "llm_temperature", "title_similarity_threshold"):
            self.assertIn(field_name, self.workbench.slider_value_labels)
            self.assertIn(field_name, self.workbench.scalar_vars)

    def test_settings_are_split_into_multiple_pages(self) -> None:
        notebook = self.workbench.settings_pages_notebook
        self.assertIsNotNone(notebook)

        labels = [notebook.tab(tab_id, "text") for tab_id in notebook.tabs()]

        self.assertEqual(
            labels,
            [
                "Review Setup",
                "Discovery",
                "AI Screening",
                "Connections and Keys",
                "Storage and Output",
                "Advanced Runtime",
            ],
        )

    def test_settings_layout_uses_navigation_and_inspector_tabs(self) -> None:
        self.assertEqual(set(self.workbench.settings_nav_buttons.keys()), {name for name, _ in self.workbench.SETTINGS_PAGES})
        self.assertIsNotNone(self.workbench.settings_tools_notebook)
        self.assertIsNotNone(self.workbench.settings_panedwindow)
        self.assertIsNotNone(self.workbench.quick_destination_combo)
        self.assertIsNotNone(self.workbench.guide_choice_combo)

        inspector_labels = [
            self.workbench.settings_tools_notebook.tab(tab_id, "text") for tab_id in self.workbench.settings_tools_notebook.tabs()
        ]
        self.assertEqual(inspector_labels, ["Find", "Quick Edit", "Guides", "Summary"])
        self.assertEqual(self.workbench.active_settings_page_var.get(), "Review Setup")
        self.assertEqual(
            self.workbench.active_settings_page_description_var.get(),
            self.workbench.SETTINGS_PAGE_DESCRIPTIONS["Review Setup"],
        )
        self.assertIn("Model provider and pass chain", tuple(self.workbench.quick_destination_combo["values"]))
        self.assertIn("Output guide", tuple(self.workbench.guide_choice_combo["values"]))

    def test_workbench_includes_charts_history_audit_and_artifact_browser_widgets(self) -> None:
        notebook_labels = [self.workbench.notebook.tab(tab_id, "text") for tab_id in self.workbench.notebook.tabs()]
        self.assertIn("Charts", notebook_labels)
        self.assertIn("Run History", notebook_labels)
        self.assertIn("Screening Audit", notebook_labels)
        self.assertIsNotNone(self.workbench.outputs_preview_text)
        self.assertIsNotNone(self.workbench.artifact_summary_text)
        self.assertIsNotNone(self.workbench.provider_health_tree)
        self.assertIsNotNone(self.workbench.chart_canvas)
        self.assertIsNotNone(self.workbench.run_history_tree)
        self.assertIsNotNone(self.workbench.screening_audit_tree)

    def test_compact_and_advanced_settings_modes_toggle_helper_density(self) -> None:
        intro_label = self.workbench.settings_page_intro_labels["Review Setup"]
        summary_label = self.workbench.settings_section_summary_labels["Review Brief"]

        self.assertEqual(intro_label.winfo_manager(), "")
        self.assertEqual(summary_label.winfo_manager(), "")

        self.workbench.settings_mode_var.set("advanced")
        self.workbench._apply_settings_mode()

        self.assertEqual(intro_label.winfo_manager(), "grid")
        self.assertEqual(summary_label.winfo_manager(), "grid")

    def test_advanced_settings_page_is_hidden_until_requested(self) -> None:
        notebook = self.workbench.settings_pages_notebook
        advanced_page = self.workbench.settings_page_frames["Advanced Runtime"]

        self.assertFalse(self.workbench.show_advanced_settings.get())
        self.assertEqual(notebook.tab(advanced_page, "state"), "hidden")

        self.workbench.show_advanced_settings.set(True)
        self.workbench._apply_settings_page_visibility()

        self.assertEqual(notebook.tab(advanced_page, "state"), "normal")

    def test_structured_widget_types_are_used_for_common_settings(self) -> None:
        self.assertEqual(self.workbench.field_widget_types["llm_provider"], "combobox")
        self.assertEqual(self.workbench.field_widget_types["openai_model"], "combobox")
        self.assertEqual(self.workbench.field_widget_types["gemini_model"], "combobox")
        self.assertEqual(self.workbench.field_widget_types["ollama_model"], "combobox")
        self.assertEqual(self.workbench.field_widget_types["huggingface_model"], "combobox")
        self.assertEqual(self.workbench.field_widget_types["pdf_download_mode"], "radiogroup")
        self.assertEqual(self.workbench.field_widget_types["run_mode"], "radiogroup")
        self.assertEqual(self.workbench.field_widget_types["verbosity"], "radiogroup")
        self.assertEqual(self.workbench.field_widget_types["partial_rerun_mode"], "combobox")
        self.assertEqual(self.workbench.field_widget_types["pages_to_retrieve"], "spinbox")
        self.assertEqual(self.workbench.field_widget_types["discovery_workers"], "spinbox")
        self.assertEqual(self.workbench.field_widget_types["io_workers"], "spinbox")
        self.assertEqual(self.workbench.field_widget_types["screening_workers"], "spinbox")
        self.assertEqual(self.workbench.field_widget_types["http_cache_ttl_seconds"], "spinbox")
        self.assertEqual(self.workbench.field_widget_types["pdf_batch_size"], "spinbox")
        self.assertEqual(self.workbench.field_widget_types["openalex_calls_per_second"], "float_spinbox")
        self.assertEqual(self.workbench.field_widget_types["semantic_scholar_calls_per_second"], "float_spinbox")
        self.assertEqual(self.workbench.field_widget_types["http_retry_base_delay_seconds"], "float_spinbox")
        self.assertEqual(self.workbench.field_widget_types["database_path"], "path")
        self.assertEqual(self.workbench.field_widget_types["http_cache_dir"], "path")
        self.assertEqual(self.workbench.field_widget_types["download_pdfs"], "checkbutton")
        self.assertEqual(self.workbench.field_widget_types["http_cache_enabled"], "checkbutton")
        self.assertEqual(self.workbench.field_widget_types["reset_query_records"], "checkbutton")
        self.assertEqual(self.workbench.field_widget_types["clear_screening_cache"], "checkbutton")
        self.assertEqual(self.workbench.field_widget_types["incremental_report_regeneration"], "checkbutton")
        self.assertEqual(self.workbench.field_widget_types["enable_async_network_stages"], "checkbutton")
        self.assertEqual(self.workbench.field_widget_types["analysis_passes"], "pass_builder")
        self.assertEqual(str(self.workbench.text_widgets["analysis_passes"].cget("state")), "disabled")

    def test_theme_styles_are_configured_for_modern_toolbar_and_tabs(self) -> None:
        self.assertEqual(self.workbench.active_theme, "clam")
        self.assertEqual(self.workbench.root.cget("bg"), self.workbench.PALETTE["shell_bg"])
        self.assertEqual(self.workbench.toolbar_buttons["Start Run"].cget("style"), "Accent.TButton")
        self.assertEqual(self.workbench.toolbar_buttons["Analyze Stored Results"].cget("style"), "Secondary.TButton")
        self.assertEqual(self.workbench.toolbar_buttons["Force Stop"].cget("style"), "Danger.TButton")
        self.assertEqual(self.workbench.notebook.cget("style"), "Workbench.TNotebook")
        self.assertEqual(self.workbench.status_label.cget("style"), "Status.TLabel")
        self.assertEqual(
            self.workbench.style.lookup("Workbench.TNotebook.Tab", "background", ("selected",)),
            self.workbench.PALETTE["surface_bg"],
        )

    def test_analysis_pass_builder_helpers_round_trip(self) -> None:
        passes = [
            {
                "name": "fast",
                "provider": "huggingface_local",
                "threshold": 72,
                "decision_mode": "strict",
                "margin": 8,
                "model_name": "Qwen/Qwen3-14B",
                "min_input_score": 0,
            },
            {
                "name": "deep",
                "provider": "openai_compatible",
                "threshold": 85,
                "decision_mode": "triage",
                "margin": 12,
                "model_name": "gpt-5.4",
                "min_input_score": 70,
            },
        ]

        self.workbench._write_analysis_passes(passes)
        round_trip = self.workbench._current_analysis_passes()

        self.assertEqual(len(round_trip), 2)
        self.assertEqual(round_trip[0]["provider"], "huggingface_local")
        self.assertEqual(round_trip[1]["provider"], "openai_compatible")
        self.assertEqual(round_trip[1]["threshold"], 85.0)
        self.assertEqual(round_trip[0]["model_name"], "Qwen/Qwen3-14B")
        self.assertEqual(round_trip[1]["min_input_score"], 70.0)

    def test_quick_access_summaries_show_model_and_output_details(self) -> None:
        self.assertIsNotNone(self.workbench.model_summary_text)
        self.assertIsNotNone(self.workbench.output_summary_text)

        model_text = self.workbench.model_summary_text.get("1.0", tk.END)
        output_text = self.workbench.output_summary_text.get("1.0", tk.END)

        self.assertIn("Primary provider", model_text)
        self.assertIn("Gemini model", model_text)
        self.assertIn("HF model", model_text)
        self.assertIn("Main SQLite DB", output_text)
        self.assertIn("CSV exports", output_text)

        self.workbench._write_analysis_passes(
            [
                {
                    "name": "deep",
                    "provider": "ollama",
                    "threshold": 80,
                    "decision_mode": "triage",
                    "margin": 10,
                    "model_name": "gpt-oss:20b",
                    "min_input_score": 70,
                }
            ]
        )
        self.workbench._refresh_settings_overview()
        updated_model_text = self.workbench.model_summary_text.get("1.0", tk.END)
        self.assertIn("gpt-oss:20b", updated_model_text)
        self.assertIn("start if previous >= 70", updated_model_text)

    def test_settings_search_can_find_output_controls(self) -> None:
        self.workbench.settings_search_var.set("sqlite")
        self.workbench._refresh_settings_search_results()
        values = tuple(self.workbench.settings_search_combo["values"])

        self.assertTrue(any("SQLite" in value for value in values))

    def test_hover_help_updates_and_restores_status_bar(self) -> None:
        original_status = self.workbench.status_var.get()

        self.workbench._show_hover_help("Explain this option.")
        self.assertEqual(self.workbench.status_var.get(), "Explain this option.")

        self.workbench._clear_hover_help()
        self.assertEqual(self.workbench.status_var.get(), original_status)

    def test_disabling_hover_help_prevents_status_override(self) -> None:
        self.workbench.hover_help_enabled.set(False)
        original_status = self.workbench.status_var.get()

        self.workbench._show_hover_help("This should not appear.")

        self.assertEqual(self.workbench.status_var.get(), original_status)

    def test_hover_help_tolerates_focus_events_with_non_numeric_root_coordinates(self) -> None:
        event = SimpleNamespace(x_root="??", y_root="??")

        self.workbench._show_hover_help("Explain this option.", event)

        self.assertEqual(self.workbench.status_var.get(), "Explain this option.")

    def test_handbook_contains_output_and_verbose_guides(self) -> None:
        guide_titles = {entry["title"] for entry in self.workbench.handbook_entries.values()}

        self.assertIn("Where CSV, JSON, SQLite, and PDFs go", guide_titles)
        self.assertIn("Where API keys and endpoint settings go", guide_titles)
        self.assertIn("How to make the run fully verbose", guide_titles)
        self.assertIn("How worker threads, cache resets, and reruns work", guide_titles)
        self.assertIn("What Start Run, Analyze Stored Results, and Force Stop do", guide_titles)
        self.assertIsNotNone(self.workbench.handbook_tree)

    def test_quick_access_contains_direct_model_and_storage_controls(self) -> None:
        frame = self.workbench.quick_access_controls_frame
        self.assertIsNotNone(frame)
        self.assertEqual(frame.master.winfo_class(), "Canvas")

        visible_texts: list[str] = []
        for child in _walk_widgets(frame):
            try:
                text = child.cget("text")
            except tk.TclError:
                continue
            if text:
                visible_texts.append(text)

        joined = " ".join(visible_texts)
        self.assertIn("Edit Pass Chain", joined)
        self.assertIn("Thresholds and decisions", joined)
        self.assertIn("Download paper PDFs", joined)
        self.assertIn("Write SQLite exports", joined)
        self.assertIn("Write JSON exports", joined)
        self.assertIn("Write Markdown summary", joined)
        self.assertNotIn("Jump to Thresholds", joined)
        self.assertNotIn("Open Connections and Keys", joined)
        self.assertIn("provider keys stay on Connections and Keys", joined)

    def test_inspector_does_not_render_navigation_button_wall(self) -> None:
        visible_texts: list[str] = []
        for child in _walk_widgets(self.workbench.settings_tab):
            try:
                text = child.cget("text")
            except tk.TclError:
                continue
            if text:
                visible_texts.append(text)

        joined = " ".join(visible_texts)
        self.assertNotIn("Jump to Models", joined)
        self.assertNotIn("Jump to Thresholds", joined)
        self.assertNotIn("Jump to Outputs", joined)
        self.assertNotIn("Open Model Guide", joined)
        self.assertNotIn("Open Output Guide", joined)


if __name__ == "__main__":  # pragma: no cover - direct module execution helper
    unittest.main()
