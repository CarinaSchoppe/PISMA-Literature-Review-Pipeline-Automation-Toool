"""Tests for guided desktop UI helpers such as hover help and field explanations."""

from __future__ import annotations

import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from config import ApiSettings, ResearchConfig
from ui.desktop_app import DesktopWorkbench, WorkbenchRoot


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

    def test_workbench_uses_custom_root_for_callback_exception_routing(self) -> None:
        self.assertIsInstance(self.workbench.root, WorkbenchRoot)

    def test_source_fields_have_descriptive_help_text(self) -> None:
        self.assertIn("OpenAlex", self.workbench._help_text_for_field("openalex_enabled"))
        self.assertIn("Crossref", self.workbench._help_text_for_field("crossref_enabled"))
        self.assertIn("Springer", self.workbench._help_text_for_field("springer_enabled"))
        self.assertIn("Semantic Scholar", self.workbench._help_text_for_field("semantic_scholar_enabled"))
        self.assertIn("Europe PMC", self.workbench._help_text_for_field("europe_pmc_enabled"))
        self.assertIn("CORE", self.workbench._help_text_for_field("core_enabled"))
        self.assertIn("temperature", self.workbench._help_text_for_field("llm_temperature").lower())
        self.assertIn("Gemini", self.workbench._help_text_for_field("gemini_model"))
        self.assertIn("rate", self.workbench._help_text_for_field("semantic_scholar_calls_per_second").lower())
        self.assertIn("biomedical", self.workbench._help_text_for_field("europe_pmc_calls_per_second").lower())
        self.assertIn("repository", self.workbench._help_text_for_field("core_calls_per_second").lower())
        self.assertIn("cache", self.workbench._help_text_for_field("clear_screening_cache").lower())
        self.assertIn("partial rerun", self.workbench._help_text_for_field("partial_rerun_mode").lower())
        self.assertIn("cache", self.workbench._help_text_for_field("http_cache_enabled").lower())
        self.assertIn("Retry-After", self.workbench._help_text_for_field("http_retry_base_delay_seconds"))
        self.assertIn("If you set this to Yes", self.workbench._help_text_for_field("download_pdfs"))
        self.assertIn("If you set this to No", self.workbench._help_text_for_field("download_pdfs"))
        self.assertIn("Available choices", self.workbench._help_text_for_field("llm_provider"))
        self.assertIn("Example path", self.workbench._help_text_for_field("database_path"))
        self.assertIn("What higher values do", self.workbench._help_text_for_field("relevance_threshold"))
        self.assertIn("commas, semicolons, or line breaks", self.workbench._help_text_for_field("search_keywords"))

    def test_output_labels_are_explicit_in_settings_ui(self) -> None:
        self.assertEqual(self.workbench.LABELS["boolean_operators"], "Boolean operators")
        self.assertEqual(self.workbench.LABELS["discovery_strategy"], "Discovery strategy")
        self.assertEqual(self.workbench.LABELS["llm_provider"], "LLM provider")
        self.assertEqual(self.workbench.LABELS["download_pdfs"], "Download paper PDFs")
        self.assertEqual(self.workbench.LABELS["output_sqlite_exports"], "Write SQLite exports")
        self.assertEqual(self.workbench.LABELS["database_path"], "Main SQLite database path")
        self.assertEqual(self.workbench.LABELS["results_dir"], "Results directory")
        self.assertEqual(self.workbench.LABELS["google_scholar_page_min"], "Google Scholar page minimum")
        self.assertEqual(self.workbench.LABELS["google_scholar_page_max"], "Google Scholar page maximum")
        self.assertEqual(self.workbench.LABELS["gemini_model"], "Gemini model")
        self.assertEqual(self.workbench.LABELS["europe_pmc_enabled"], "Use Europe PMC")
        self.assertEqual(self.workbench.LABELS["core_enabled"], "Use CORE")
        self.assertEqual(self.workbench.LABELS["core_api_key"], "CORE API key")
        self.assertEqual(self.workbench.LABELS["discovery_workers"], "Discovery workers")
        self.assertEqual(self.workbench.LABELS["reset_query_records"], "Reset stored query records")
        self.assertEqual(self.workbench.LABELS["openalex_calls_per_second"], "OpenAlex calls / second")
        self.assertEqual(self.workbench.LABELS["europe_pmc_calls_per_second"], "Europe PMC calls / second")
        self.assertEqual(self.workbench.LABELS["core_calls_per_second"], "CORE calls / second")
        self.assertEqual(self.workbench.LABELS["partial_rerun_mode"], "Partial rerun mode")
        self.assertEqual(self.workbench.LABELS["http_cache_enabled"], "Enable HTTP source cache")
        self.assertEqual(self.workbench.LABELS["http_cache_dir"], "HTTP cache directory")
        self.assertEqual(self.workbench.LABELS["pdf_batch_size"], "PDF batch size")
        self.assertEqual(self.workbench.LABELS["topic_prefilter_weighted_keywords"], "Weighted research keywords")
        self.assertEqual(self.workbench.LABELS["topic_prefilter_match_threshold"], "Research-fit strong threshold")

    def test_keyword_and_filter_fields_have_placeholders_and_guidance(self) -> None:
        expected_fields = {
            "research_topic",
            "research_question",
            "review_objective",
            "search_keywords",
            "inclusion_criteria",
            "exclusion_criteria",
            "banned_topics",
            "excluded_title_terms",
            "topic_prefilter_weighted_keywords",
        }
        self.assertTrue(expected_fields.issubset(set(self.workbench.FIELD_PLACEHOLDERS.keys())))
        self.assertIn("search_keywords", self.workbench.placeholder_widgets)
        self.assertIn("settings_search", self.workbench.placeholder_widgets)
        self.assertIn("handbook_search", self.workbench.placeholder_widgets)
        self.assertIn("all_papers_search", self.workbench.placeholder_widgets)
        self.assertIn("commas, semicolons, or line breaks", self.workbench.FIELD_INPUT_GUIDANCE["search_keywords"])

    def test_collect_form_values_ignores_placeholder_text(self) -> None:
        question_widget = self.workbench.text_widgets["research_question"]
        self.assertIn("Describe the exact review question", question_widget.get("1.0", "end"))

        values = self.workbench._collect_form_values()

        self.assertEqual(values["research_question"], "")
        self.assertEqual(values["settings_search"], "")

    def test_review_setup_defaults_are_empty_until_user_enters_values(self) -> None:
        values = self.workbench._collect_form_values()

        self.assertEqual(values["research_topic"], "")
        self.assertEqual(values["research_question"], "")
        self.assertEqual(values["review_objective"], "")
        self.assertEqual(values["search_keywords"], "")
        self.assertEqual(values["inclusion_criteria"], "")
        self.assertEqual(values["exclusion_criteria"], "")
        self.assertEqual(values["banned_topics"], "")
        self.assertEqual(values["excluded_title_terms"], "")
        self.assertEqual(values["topic_prefilter_weighted_keywords"], "")

    def test_guided_text_validation_reports_missing_topic_and_empty_keyword_list(self) -> None:
        messages = self.workbench._validate_guided_text_inputs(
            {
                "research_topic": "   ",
                "search_keywords": " , ; \n ",
                "inclusion_criteria": "empirical study; benchmark",
                "exclusion_criteria": "",
                "banned_topics": "",
                "excluded_title_terms": "correction; erratum",
            }
        )

        self.assertEqual(len(messages), 2)
        self.assertIn("Research topic is required", messages[0])
        self.assertIn("Search keywords must contain at least one meaningful term", messages[1])

    def test_settings_search_placeholder_does_not_hide_results(self) -> None:
        self.workbench._refresh_settings_search_results()
        self.assertGreater(len(tuple(self.workbench.settings_search_combo["values"])), 0)

    def test_gui_covers_all_runtime_fields_and_toolbar_actions(self) -> None:
        shell_control_fields = {"ui_settings_mode", "ui_show_advanced_settings"}
        config_fields = set(ResearchConfig.model_fields.keys()) - {"api_settings", "query_key"} - shell_control_fields
        api_fields = set(ApiSettings.model_fields.keys())
        grouped_fields = set()
        for _, fields in self.workbench.GROUPS:
            grouped_fields.update(fields)
        widget_fields = set(self.workbench.text_widgets.keys()) | set(self.workbench.scalar_vars.keys())

        self.assertTrue((config_fields | api_fields).issubset(grouped_fields))
        self.assertTrue(grouped_fields.issubset(widget_fields))
        self.assertIn("analysis_passes", self.workbench.text_widgets)
        self.assertEqual(self.workbench.settings_mode_var.get(), "compact")
        self.assertFalse(self.workbench.show_advanced_settings.get())

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
        for field_name in (
            "relevance_threshold",
            "maybe_threshold_margin",
            "llm_temperature",
            "title_similarity_threshold",
            "topic_prefilter_match_threshold",
            "topic_prefilter_near_fit_threshold",
        ):
            self.assertIn(field_name, self.workbench.slider_value_labels)
            self.assertIn(field_name, self.workbench.scalar_vars)
        self.assertIn("google_scholar_pages", self.workbench.slider_value_label_groups)
        self.assertEqual(self.workbench.field_widget_types["google_scholar_pages"], "spinbox")
        self.assertEqual(self.workbench.field_widget_types["topic_prefilter_min_keyword_matches"], "spinbox")

    def test_research_fit_tab_and_badges_exist(self) -> None:
        notebook_labels = [self.workbench.notebook.tab(tab_id, "text") for tab_id in self.workbench.notebook.tabs()]

        self.assertIn("Research Fit", notebook_labels)
        self.assertIsNotNone(self.workbench.research_fit_tree)
        self.assertIsNotNone(self.workbench.research_fit_text)
        self.assertEqual(self.workbench.research_fit_strong_badge_var.get(), "[FIT] 0 strong")
        self.assertEqual(self.workbench.research_fit_near_badge_var.get(), "[FIT] 0 near")
        self.assertEqual(self.workbench.research_fit_weak_badge_var.get(), "[FIT] 0 weak")

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
        self.assertIsNotNone(self.workbench.workspace_overview_content)
        self.assertIsNotNone(self.workbench.workspace_overview_toggle_button)
        self.assertIsNotNone(self.workbench.settings_overview_content)
        self.assertIsNotNone(self.workbench.settings_overview_toggle_button)
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

    def test_settings_panes_allow_manual_resize_without_snapping_back(self) -> None:
        paned = self.workbench.settings_panedwindow
        self.assertIsNotNone(paned)
        self.assertEqual(str(paned.cget("cursor")), "sb_h_double_arrow")

        self.workbench.settings_panes_initialized = True
        self.workbench.settings_panes_user_resized = True
        self.workbench.settings_panes_mode = self.workbench.compact_window_mode.get()
        first_sash = paned.sashpos(0)
        second_sash = paned.sashpos(1)

        self.workbench._apply_default_settings_pane_positions()

        self.assertEqual(paned.sashpos(0), first_sash)
        self.assertEqual(paned.sashpos(1), second_sash)

    def test_settings_sidebar_controls_can_resize_and_reset_panes(self) -> None:
        paned = self.workbench.settings_panedwindow
        self.assertIsNotNone(paned)
        default_left, default_right = self.workbench._default_settings_pane_widths(bool(self.workbench.compact_window_mode.get()))

        self.workbench._adjust_settings_sidebar_width("left", 32)
        self.assertEqual(self.workbench.settings_left_pane_width, default_left + 32)

        self.workbench._adjust_settings_sidebar_width("right", 32)
        self.assertTrue(self.workbench.settings_panes_user_resized)
        self.assertEqual(self.workbench.settings_right_pane_width, default_right + 32)

        self.workbench._reset_settings_pane_widths()
        self.assertFalse(self.workbench.settings_panes_user_resized)
        self.assertEqual(self.workbench.settings_left_pane_width, default_left)
        self.assertEqual(self.workbench.settings_right_pane_width, default_right)

    def test_settings_overview_toggle_persists_across_layout_refreshes(self) -> None:
        self.workbench.settings_mode_var.set("advanced")
        self.workbench.compact_window_mode.set(False)
        self.workbench._apply_settings_mode()
        self.workbench._toggle_settings_overview()

        self.workbench.root.update_idletasks()
        self.assertFalse(bool(self.workbench.settings_overview_content and self.workbench.settings_overview_content.winfo_ismapped()))

        self.workbench._apply_responsive_layout()

        self.workbench.root.update_idletasks()
        self.assertFalse(bool(self.workbench.settings_overview_content and self.workbench.settings_overview_content.winfo_ismapped()))

    def test_workbench_includes_charts_history_audit_and_artifact_browser_widgets(self) -> None:
        notebook_labels = [self.workbench.notebook.tab(tab_id, "text") for tab_id in self.workbench.notebook.tabs()]
        self.assertIn("Charts", notebook_labels)
        self.assertIn("Run History", notebook_labels)
        self.assertIn("Screening Audit", notebook_labels)
        self.assertIn("Document Viewer", notebook_labels)
        self.assertIsNotNone(self.workbench.outputs_preview_text)
        self.assertIsNotNone(self.workbench.artifact_summary_text)
        self.assertIsNotNone(self.workbench.provider_health_tree)
        self.assertIsNotNone(self.workbench.chart_canvas)
        self.assertIsNotNone(self.workbench.run_history_tree)
        self.assertIsNotNone(self.workbench.screening_audit_tree)
        self.assertIsNotNone(self.workbench.document_summary_text)
        self.assertIsNotNone(self.workbench.document_content_text)
        self.assertIsNotNone(self.workbench.document_canvas)
        self.assertIsNotNone(self.workbench.document_prev_button)
        self.assertIsNotNone(self.workbench.document_next_button)

    def test_scrollable_shells_exist_for_tables_logs_panels_and_visuals(self) -> None:
        for tree_key in (
            "all_papers",
            "included_papers",
            "excluded_papers",
            "outputs_tree",
            "run_history_tree",
            "screening_audit_tree",
            "handbook_tree",
            "provider_health_tree",
        ):
            with self.subTest(tree_key=tree_key):
                self.assertIn(tree_key, self.workbench.tree_scrollbars)
                self.assertIn("vertical", self.workbench.tree_scrollbars[tree_key])
                self.assertIn("horizontal", self.workbench.tree_scrollbars[tree_key])

        for text_key in (
            "run_log",
            "handbook_text",
            "outputs_preview",
            "artifact_summary",
            "charts_summary",
            "run_history_text",
            "screening_audit_text",
            "document_summary",
            "document_content",
            "model_summary",
            "output_summary",
            "export_preview",
        ):
            with self.subTest(text_key=text_key):
                self.assertIn(text_key, self.workbench.text_scrollbars)
                self.assertIn("vertical", self.workbench.text_scrollbars[text_key])

        self.assertIn("horizontal", self.workbench.text_scrollbars["run_log"])
        self.assertIn("chart_preview", self.workbench.canvas_scrollbars)
        self.assertIn("vertical", self.workbench.canvas_scrollbars["chart_preview"])
        self.assertIn("horizontal", self.workbench.canvas_scrollbars["chart_preview"])
        self.assertIn("document_canvas", self.workbench.canvas_scrollbars)
        self.assertIn("vertical", self.workbench.canvas_scrollbars["document_canvas"])
        self.assertIn("horizontal", self.workbench.canvas_scrollbars["document_canvas"])

    def test_log_widget_uses_semantic_badges_and_tags(self) -> None:
        self.workbench._append_log("2026-03-12 10:00:00 | INFO | pipeline.pipeline_controller | Pipeline finished in 0.02 seconds.")
        log_text = self.workbench.log_widget.get("1.0", tk.END)
        self.assertIn("[OK]", log_text)
        self.assertIn("log_success", self.workbench.log_widget.tag_names())
        self.assertIn("log_warning", self.workbench.log_widget.tag_names())
        self.assertIn("log_error", self.workbench.log_widget.tag_names())

    def test_outputs_and_history_use_visible_badges(self) -> None:
        self.workbench._append_run_history(
            {
                "run_status": "completed",
                "run_mode": "analyze",
                "research_topic": "Topic",
                "results_dir": "results",
            }
        )
        history_values = self.workbench.run_history_tree.item(self.workbench.run_history_tree.get_children()[0]).get("values", [])
        self.assertIn("[OK] completed", history_values)

        self.workbench._load_outputs({"papers_csv": "results/papers.csv"})
        output_item = self.workbench.outputs_tree.get_children()[0]
        output_values = self.workbench.outputs_tree.item(output_item).get("values", [])
        self.assertTrue(str(output_values[0]).startswith("[CSV]"))
        self.assertIn("artifact_csv", self.workbench.outputs_tree.item(output_item).get("tags", ()))
        self.assertIn("[RUN] Completed", self.workbench.run_history_status_badge.cget("text"))
        self.assertIn("[MODE] analyze", self.workbench.run_history_mode_badge.cget("text"))

    def test_double_click_document_preview_can_open_from_result_table(self) -> None:
        title = "Preview paper"
        item_id = "all_papers-0"
        self.workbench.table_rows["all_papers"] = {
            item_id: {
                "title": title,
                "abstract": "Preview abstract",
                "source": "fixture",
                "inclusion_decision": "include",
                "relevance_score": 88.0,
            }
        }
        tree = self.workbench.treeviews["all_papers"]
        tree["columns"] = ("title",)
        tree.insert("", tk.END, iid=item_id, values=(title,))
        tree.selection_set(item_id)
        tree.focus(item_id)

        self.workbench._open_document_from_table("all_papers")

        summary_text = self.workbench.document_summary_text.get("1.0", tk.END)
        self.assertIn(title, summary_text)
        self.assertEqual(self.workbench.notebook.tab(self.workbench.notebook.select(), "text"), "Document Viewer")
        self.assertIn("[INC] Include", self.workbench.document_decision_badge.cget("text"))
        self.assertIn("[SRC] fixture", self.workbench.document_source_badge.cget("text"))

    def test_document_external_button_uses_stored_document_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "paper.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n%mock pdf\n")

            self.workbench._show_document_preview(
                {
                    "title": "Preview paper",
                    "abstract": "Preview abstract",
                    "source": "fixture",
                    "inclusion_decision": "include",
                    "pdf_path": str(pdf_path),
                },
                source_label="fixture",
            )

            with patch.object(self.workbench, "_open_path") as open_path:
                self.workbench._open_document_external()

            open_path.assert_called_once_with(pdf_path)

    def test_result_tables_render_visible_decision_badges(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "papers.csv"
            pd.DataFrame(
                [
                    {
                        "title": "Paper A",
                        "inclusion_decision": "include",
                        "relevance_score": 88.4,
                        "source": "OpenAlex",
                    }
                ]
            ).to_csv(csv_path, index=False)
            self.workbench.load_dataframe_into_tree("all_papers", csv_path)
            item_id = self.workbench.treeviews["all_papers"].get_children()[0]
            values = self.workbench.treeviews["all_papers"].item(item_id).get("values", [])
            joined = " ".join(map(str, values))
            self.assertIn("[INC] Include", joined)
            self.assertIn("[SCORE]", joined)
            self.assertIn("[SRC] OpenAlex", joined)

    def test_compact_and_advanced_settings_modes_toggle_helper_density(self) -> None:
        intro_label = self.workbench.settings_page_intro_labels["Review Setup"]
        summary_label = self.workbench.settings_section_summary_labels["Review Brief"]
        self.assertEqual(intro_label.winfo_manager(), "")
        self.assertEqual(summary_label.winfo_manager(), "")
        self.assertEqual(str(self.workbench.workspace_overview_toggle_button.cget("text")), "Show workspace overview")
        self.assertEqual(str(self.workbench.settings_overview_toggle_button.cget("text")), "Show page overview")

        self.workbench.settings_mode_var.set("advanced")
        self.workbench.compact_window_mode.set(False)
        self.workbench._apply_settings_mode()
        self.workbench._apply_workspace_overview_visibility(True)
        self.workbench._apply_settings_overview_visibility(True)

        self.assertEqual(intro_label.winfo_manager(), "grid")
        self.assertEqual(summary_label.winfo_manager(), "grid")
        self.assertEqual(str(self.workbench.workspace_overview_toggle_button.cget("text")), "Hide workspace overview")
        self.assertEqual(str(self.workbench.settings_overview_toggle_button.cget("text")), "Hide page overview")

    def test_overview_toggles_and_small_window_mode_keep_editing_area_visible(self) -> None:
        self.workbench.settings_mode_var.set("advanced")
        self.workbench.compact_window_mode.set(False)
        self.workbench._apply_settings_mode()
        self.workbench._apply_workspace_overview_visibility(True)
        self.workbench._apply_settings_overview_visibility(True)
        self.assertEqual(str(self.workbench.workspace_overview_toggle_button.cget("text")), "Hide workspace overview")
        self.assertEqual(str(self.workbench.settings_overview_toggle_button.cget("text")), "Hide page overview")

        self.workbench._toggle_workspace_overview()
        self.workbench._toggle_settings_overview()
        self.assertEqual(self.workbench.workspace_overview_user_visible, False)
        self.assertEqual(self.workbench.settings_overview_user_visible, False)
        self.assertEqual(str(self.workbench.workspace_overview_toggle_button.cget("text")), "Show workspace overview")
        self.assertEqual(str(self.workbench.settings_overview_toggle_button.cget("text")), "Show page overview")

        self.workbench.root.geometry("980x680")
        self.workbench.root.update_idletasks()
        self.workbench._apply_responsive_layout()
        self.assertTrue(self.workbench.compact_window_mode.get())
        self.assertEqual(str(self.workbench.workspace_overview_toggle_button.cget("text")), "Show workspace overview")
        self.assertEqual(str(self.workbench.settings_overview_toggle_button.cget("text")), "Show page overview")
        self.assertEqual(self.workbench.settings_page_description_label.winfo_manager(), "")

    def test_advanced_settings_page_is_hidden_until_requested(self) -> None:
        notebook = self.workbench.settings_pages_notebook
        advanced_page = self.workbench.settings_page_frames["Advanced Runtime"]

        self.assertFalse(self.workbench.show_advanced_settings.get())
        self.assertEqual(notebook.tab(advanced_page, "state"), "hidden")

        self.workbench._apply_form_values(
            {
                **self.workbench._collect_form_values(),
                "ui_settings_mode": "advanced",
                "ui_show_advanced_settings": True,
            }
        )
        self.assertEqual(self.workbench.settings_mode_var.get(), "advanced")
        self.assertTrue(self.workbench.show_advanced_settings.get())
        self.assertEqual(notebook.tab(advanced_page, "state"), "normal")

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
        self.assertEqual(self.workbench.field_widget_types["log_file_path"], "path")
        self.assertEqual(self.workbench.field_widget_types["partial_rerun_mode"], "combobox")
        self.assertEqual(self.workbench.field_widget_types["pages_to_retrieve"], "spinbox")
        self.assertEqual(self.workbench.field_widget_types["google_scholar_pages"], "spinbox")
        self.assertEqual(self.workbench.field_widget_types["google_scholar_page_min"], "spinbox")
        self.assertEqual(self.workbench.field_widget_types["google_scholar_page_max"], "spinbox")
        self.assertEqual(self.workbench.field_widget_types["google_scholar_results_per_page"], "spinbox")
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
        self.assertEqual(str(self.workbench.style.lookup("HeroPanel.TFrame", "background")), self.workbench.PALETTE["hero_bg"])
        self.assertEqual(
            str(self.workbench.style.lookup("MetricAccent.TFrame", "background")),
            self.workbench.PALETTE["muted_surface"],
        )
        self.assertEqual(
            str(self.workbench.style.lookup("MetricHeroValue.TLabel", "foreground")),
            self.workbench.PALETTE["inverse_text"],
        )
        self.assertEqual(
            self.workbench.style.lookup("Workbench.TNotebook.Tab", "background", ("selected",)),
            self.workbench.PALETTE["surface_bg"],
        )

    def test_visual_summary_cards_are_rendered_for_modern_dashboard_sections(self) -> None:
        expected_cards = {
            "hero_guided_pages",
            "hero_outputs",
            "hero_reruns",
            "hero_mode",
            "hero_help",
            "settings_brief_card",
            "settings_discovery_card",
            "settings_runtime_card",
            "log_visibility_card",
            "log_trace_card",
            "log_debug_card",
            "outputs_csv_card",
            "outputs_sqlite_card",
            "outputs_pdf_card",
            "charts_decisions_card",
            "charts_sources_card",
            "charts_audit_card",
        }
        self.assertTrue(expected_cards.issubset(set(self.workbench.visual_summary_cards.keys())))

    def test_quick_access_summaries_show_model_and_output_details(self) -> None:
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
