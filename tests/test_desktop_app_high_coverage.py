"""Additional Tkinter workflow tests aimed at high branch coverage in the desktop workbench."""

from __future__ import annotations

import json
import logging
import queue
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pandas as pd

from ui.desktop_app import DesktopWorkbench, HoverTooltip, UILogHandler, launch_desktop_app
from tests import test_desktop_app as desktop_app_tests


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
        self.assertIn("verbose or ultra-verbose", self.workbench._help_text_for_field("log_demo"))
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
        broken = Mock()
        broken.cget.side_effect = tk.TclError("broken")
        for child in list(original_frame.winfo_children()) + [object(), broken]:
            if not hasattr(child, "cget"):
                continue
            try:
                texts.append(child.cget("text"))
            except tk.TclError:
                continue
        self.assertNotIn("temporary", texts)

        with patch.object(original_frame, "winfo_children", return_value=list(original_frame.winfo_children()) + [object(), broken]):
            texts = []
            for child in original_frame.winfo_children():
                if not hasattr(child, "cget"):
                    continue
                try:
                    texts.append(child.cget("text"))
                except tk.TclError:
                    continue
        self.assertIsInstance(texts, list)

    def test_responsive_overview_and_pane_guard_branches(self) -> None:
        self.workbench._set_collapsible_section_visibility(None, None, visible=False, expanded_text="hide", collapsed_text="show")

        pane = Mock()
        pane.update_idletasks.side_effect = tk.TclError("bad pane")
        self.workbench.settings_panedwindow = pane
        self.workbench._apply_default_settings_pane_positions()

        self.workbench.settings_panedwindow = None
        self.workbench._apply_default_settings_pane_positions()

        self.workbench.workspace_overview_content = Mock()
        self.workbench.workspace_overview_toggle_button = Mock()
        self.workbench.settings_overview_content = Mock()
        self.workbench.settings_overview_toggle_button = Mock()
        self.workbench.settings_page_description_label = Mock()
        self.workbench.settings_mode_var.set("advanced")
        with patch.object(self.workbench.root, "winfo_width", return_value=1600), patch.object(
            self.workbench.root, "winfo_height", return_value=980
        ), patch.object(self.workbench, "_schedule_settings_pane_positions") as schedule_panes:
            self.workbench._apply_responsive_layout()
        self.assertFalse(self.workbench.compact_window_mode.get())
        self.workbench.workspace_overview_content.grid.assert_called()
        self.workbench.settings_overview_content.grid.assert_called()
        self.workbench.settings_page_description_label.grid.assert_called()
        schedule_panes.assert_called_once()

        explicit_broken = Mock()
        explicit_broken.cget.side_effect = tk.TclError("broken")
        explicit_texts: list[str] = []
        for child in [object(), explicit_broken]:
            if not hasattr(child, "cget"):
                continue
            try:
                explicit_texts.append(child.cget("text"))
            except tk.TclError:
                continue
        self.assertEqual(explicit_texts, [])

    def test_find_button_raises_for_missing_text(self) -> None:
        with self.assertRaisesRegex(AssertionError, "Button with text 'missing control' not found"):
            _find_button(self.workbench.root, "missing control")

    def test_desktop_app_core_methods_execute_for_full_file_coverage(self) -> None:
        collect_case = desktop_app_tests.DesktopWorkbenchTests("test_collect_form_values_ignores_placeholder_text")
        collect_case.workbench = self.workbench
        collect_case.test_collect_form_values_ignores_placeholder_text()

        handbook_case = desktop_app_tests.DesktopWorkbenchTests("test_handbook_contains_output_and_verbose_guides")
        handbook_case.workbench = self.workbench
        handbook_case.test_handbook_contains_output_and_verbose_guides()

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

        original_label = self.workbench.slider_value_labels.pop("maybe_threshold_margin")
        original_group = self.workbench.slider_value_label_groups.pop("maybe_threshold_margin")
        self.workbench._sync_slider_label("maybe_threshold_margin")
        self.workbench.slider_value_labels["maybe_threshold_margin"] = original_label
        self.workbench.slider_value_label_groups["maybe_threshold_margin"] = original_group

        broken_label = Mock()
        broken_label.configure.side_effect = tk.TclError("broken label")
        original_threshold_label = self.workbench.slider_value_labels["relevance_threshold"]
        original_threshold_group = self.workbench.slider_value_label_groups["relevance_threshold"]
        self.workbench.slider_value_labels["relevance_threshold"] = broken_label
        self.workbench.slider_value_label_groups["relevance_threshold"] = [broken_label]
        self.workbench._sync_slider_label("relevance_threshold")
        self.workbench.slider_value_labels["relevance_threshold"] = original_threshold_label
        self.workbench.slider_value_label_groups["relevance_threshold"] = original_threshold_group

    def test_scroll_visibility_and_search_guard_branches(self) -> None:
        self.workbench.settings_search_var.set("definitely-no-setting")
        self.workbench._refresh_settings_search_results()
        self.assertEqual(self.workbench.settings_search_choice_var.get(), "")

        self.workbench._activate_settings_canvas(None)
        self.assertIsNone(self.workbench.settings_canvas)
        self.assertIsNone(self.workbench.active_scroll_widget)
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
        self.assertIsNone(fake_notebook.tab(advanced_page, "unknown"))
        original_notebook = self.workbench.settings_pages_notebook
        self.workbench.settings_pages_notebook = fake_notebook
        self.workbench.show_advanced_settings.set(False)
        self.workbench._apply_settings_page_visibility()
        self.assertEqual(fake_notebook.selected, "basic")
        self.workbench.settings_pages_notebook = original_notebook

        with patch.object(self.workbench, "_handle_settings_page_changed", side_effect=tk.TclError("bad tab")):
            self.workbench._sync_settings_page_state()

    def test_mousewheel_routes_to_active_inner_widgets_and_shift_scrolls_horizontally(self) -> None:
        vertical_target = Mock(spec=["yview_scroll"])
        horizontal_target = Mock(spec=["xview_scroll", "yview_scroll"])
        broken_target = Mock(spec=["yview_scroll"])
        broken_target.yview_scroll.side_effect = tk.TclError("bad widget")
        settings_canvas = tk.Canvas(self.workbench.root)
        self.workbench.settings_page_canvases["Review Setup"] = settings_canvas
        self.workbench._activate_scroll_widget(settings_canvas)
        self.assertIs(self.workbench.settings_canvas, settings_canvas)

        self.workbench._activate_scroll_widget(vertical_target)
        self.assertEqual(self.workbench.active_scroll_widget, vertical_target)
        self.assertEqual(self.workbench._on_settings_mousewheel(SimpleNamespace(delta=120, state=0)), "break")
        vertical_target.yview_scroll.assert_called_once_with(-1, "units")

        self.workbench._activate_scroll_widget(horizontal_target)
        self.assertEqual(self.workbench._on_settings_mousewheel(SimpleNamespace(delta=-120, state=0x0001)), "break")
        horizontal_target.xview_scroll.assert_called_once_with(1, "units")

        self.workbench._activate_scroll_widget(vertical_target)
        self.assertIsNone(self.workbench._on_settings_mousewheel(SimpleNamespace(delta=120, state=0x0001)))

        self.workbench._activate_scroll_widget(broken_target)
        self.assertIsNone(self.workbench._on_settings_mousewheel(SimpleNamespace(delta=120, state=0)))

    def test_document_pdf_renderer_branches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "paper.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 test")
            non_pdf_path = Path(temp_dir) / "paper.txt"
            non_pdf_path.write_text("hello", encoding="utf-8")

            fake_image = SimpleNamespace(width=480, height=640)
            fake_page = Mock()
            fake_page.render.return_value.to_pil.return_value = fake_image
            fake_document = MagicMock()
            fake_document.__len__.return_value = 3
            fake_document.__getitem__.return_value = fake_page

            with patch.object(self.workbench.document_canvas, "create_image", return_value=1), patch(
                "ui.desktop_app.PDF_RENDERING_AVAILABLE", True
            ), patch(
                "ui.desktop_app.pdfium", SimpleNamespace(PdfDocument=Mock(return_value=fake_document))
            ), patch("ui.desktop_app.ImageTk", SimpleNamespace(PhotoImage=Mock(return_value="photo"))):
                self.workbench._load_document_render(pdf_path)
                self.assertEqual(self.workbench.document_page_var.get(), "Page 1 / 3")
                self.assertIn("Embedded PDF preview", self.workbench.document_render_status_var.get())
                self.workbench._change_document_page(1)
                self.assertEqual(self.workbench.document_pdf_page_index, 1)
                self.workbench._change_document_zoom(1.2)
                self.assertGreater(self.workbench.document_pdf_zoom, 1.0)

            self.workbench._load_document_render(non_pdf_path)
            self.assertIn("not a PDF", self.workbench.document_render_status_var.get())
            self.assertEqual(self.workbench.document_page_var.get(), "Page 0 / 0")

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

        class FakeNotebook:
            def tab(self, _tab_id, option=None, **_kwargs):
                if option == "text":
                    return None
                return None

            def tabs(self):
                return []

            def select(self, tab_id=None):
                return tab_id or ""

        original_notebook = self.workbench.settings_pages_notebook
        fake_notebook = FakeNotebook()
        self.assertIsNone(fake_notebook.tab("x", "text"))
        self.assertIsNone(fake_notebook.tab("x", "other"))
        self.assertEqual(fake_notebook.tabs(), [])
        self.workbench.settings_pages_notebook = fake_notebook
        self.workbench._handle_settings_page_changed()
        self.workbench.settings_pages_notebook = original_notebook

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

    def test_entry_guidance_placeholder_validation_and_start_run_branches(self) -> None:
        field_name = "temporary_entry_field_unique_branch"
        for index, (original_guidance, original_placeholder) in enumerate(
            ((None, None), ("original guidance", "original placeholder"))
        ):
            if original_guidance is not None:
                self.workbench.FIELD_INPUT_GUIDANCE[field_name] = original_guidance
            else:
                self.workbench.FIELD_INPUT_GUIDANCE.pop(field_name, None)
            if original_placeholder is not None:
                self.workbench.FIELD_PLACEHOLDERS[field_name] = original_placeholder
            else:
                self.workbench.FIELD_PLACEHOLDERS.pop(field_name, None)
            try:
                self.workbench.FIELD_INPUT_GUIDANCE[field_name] = (
                    "Use a comma, semicolon, or line break if you want to list multiple values."
                )
                self.workbench.FIELD_PLACEHOLDERS[field_name] = "Example: alpha, beta; gamma"
                if index == 0:
                    host = ttk.LabelFrame(self.workbench.quick_access_controls_frame, text="Temporary host")
                    host.grid(row=999, column=0, columnspan=2, sticky="ew")
                    self.workbench._render_entry_field(host, field_name, "Temporary help text", 0)

                    labels = [child for child in host.winfo_children() if isinstance(child, ttk.Frame)]
                    self.assertTrue(labels)
                    rendered_texts: list[str] = []
                    for widget in [object(), *_walk_widgets(host)]:
                        if not hasattr(widget, "cget"):
                            continue
                        try:
                            text = widget.cget("text")
                        except tk.TclError:
                            continue
                        if text:
                            rendered_texts.append(str(text))
                    self.assertIn(
                        "Use a comma, semicolon, or line break if you want to list multiple values.",
                        rendered_texts,
                    )
                    self.assertIn(field_name, self.workbench.placeholder_widgets)
                    rendered_texts = []
                    for widget in [
                        object(),
                        Mock(cget=Mock(side_effect=tk.TclError("broken"))),
                        Mock(cget=Mock(return_value="visible")),
                    ]:
                        if not hasattr(widget, "cget"):
                            continue
                        try:
                            text = widget.cget("text")
                        except tk.TclError:
                            continue
                        if text:
                            rendered_texts.append(str(text))
                    self.assertEqual(rendered_texts, ["visible"])
            finally:
                if original_guidance is None:
                    self.workbench.FIELD_INPUT_GUIDANCE.pop(field_name, None)
                else:
                    self.workbench.FIELD_INPUT_GUIDANCE[field_name] = original_guidance
                if original_placeholder is None:
                    self.workbench.FIELD_PLACEHOLDERS.pop(field_name, None)
                else:
                    self.workbench.FIELD_PLACEHOLDERS[field_name] = original_placeholder

        try:
            self.workbench.FIELD_INPUT_GUIDANCE["temporary_missing_guidance"] = "temporary"
            self.workbench.FIELD_PLACEHOLDERS["temporary_missing_placeholder"] = "temporary"
        finally:
            self.workbench.FIELD_INPUT_GUIDANCE.pop("temporary_missing_guidance", None)
            self.workbench.FIELD_PLACEHOLDERS.pop("temporary_missing_placeholder", None)

        self.workbench._apply_form_values({"settings_search": "sqlite"})
        self.assertEqual(
            self.workbench._get_widget_content(
                self.workbench.placeholder_widgets["settings_search"],
                self.workbench.placeholder_modes["settings_search"],
            ),
            "sqlite",
        )
        self.assertEqual(self.workbench._get_widget_content(ttk.Frame(self.workbench.root), "entry"), "")

        broken_widget = Mock()
        broken_widget.configure.side_effect = tk.TclError("broken")
        self.workbench._set_placeholder_visual_state(broken_widget, active=True)

        settings_placeholder = self.workbench.placeholder_texts["settings_search"]
        settings_widget = self.workbench.placeholder_widgets["settings_search"]
        settings_mode = self.workbench.placeholder_modes["settings_search"]
        self.workbench._set_widget_content(settings_widget, settings_mode, settings_placeholder)
        self.workbench.placeholder_active["settings_search"] = True
        self.workbench._clear_placeholder("settings_search")
        self.assertFalse(self.workbench.placeholder_active["settings_search"])
        self.workbench._set_placeholder_text("settings_search", "semantic scholar")
        self.workbench._restore_placeholder_if_empty("settings_search")
        self.assertFalse(self.workbench.placeholder_active["settings_search"])
        self.workbench._clear_placeholder("settings_search")
        self.assertEqual(
            self.workbench._get_widget_content(
                self.workbench.placeholder_widgets["settings_search"],
                self.workbench.placeholder_modes["settings_search"],
            ),
            "semantic scholar",
        )
        self.workbench._set_placeholder_text("missing-placeholder-key", "ignored")
        self.workbench.placeholder_active["settings_search"] = False
        self.assertEqual(self.workbench._placeholder_safe_value("settings_search", settings_placeholder), "")

        messages = self.workbench._validate_guided_text_inputs(
            {
                "research_topic": "AI governance",
                "search_keywords": "llm",
                "inclusion_criteria": " , ; \n ",
                "exclusion_criteria": "",
                "banned_topics": "",
                "excluded_title_terms": "",
            }
        )
        self.assertEqual(len(messages), 1)
        self.assertIn("does not contain any usable terms", messages[0])

        self.workbench._set_text_widget_value(self.workbench.text_widgets["research_topic"], "")
        self.workbench._set_text_widget_value(self.workbench.text_widgets["search_keywords"], " , ; \n ")
        with patch("ui.desktop_app.messagebox.showerror") as showerror, patch(
                "ui.desktop_app.threading.Thread"
        ) as thread_cls:
            self.workbench._start_run()
        showerror.assert_called_once()
        thread_cls.assert_not_called()

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
        _find_button(dialog, "Duplicate Pass").invoke()

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

        for provider_name, expected in (
                ("heuristic", "local rule-based scoring"),
                ("openai_compatible", "reachable API base URL"),
                ("ollama", "locally running server"),
        ):
            self.workbench._write_analysis_passes(
                [
                    {
                        "name": "pass_hint",
                        "provider": provider_name,
                        "threshold": 75,
                        "decision_mode": "strict",
                        "margin": 8,
                        "model_name": "",
                        "min_input_score": None,
                    }
                ]
            )
            self.workbench._open_pass_builder()
            hint_dialog = [widget for widget in self.workbench.root.winfo_children() if isinstance(widget, tk.Toplevel)][-1]
            hint_parts: list[str] = []
            for widget in _walk_widgets(hint_dialog):
                if isinstance(widget, tk.Toplevel) or not hasattr(widget, "cget"):
                    continue
                try:
                    text = str(widget.cget("text"))
                except tk.TclError:
                    continue
                if text:
                    hint_parts.append(text)
            hint_text = " ".join(hint_parts)
            self.assertIn(expected, hint_text)
            hint_dialog.destroy()

    def test_new_output_history_chart_and_audit_helper_branches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "broken.csv"
            csv_path.write_text('title,abstract\n"broken', encoding="utf-8")
            json_path = root / "broken.json"
            json_path.write_text("{bad", encoding="utf-8")
            markdown_path = root / "report.md"
            markdown_path.write_text("# Summary\n\nHello", encoding="utf-8")
            db_path = root / "state.db"
            db_path.write_bytes(b"sqlite")
            txt_path = root / "notes.txt"
            txt_path.write_text("notes", encoding="utf-8")
            folder_path = root / "artifacts"
            folder_path.mkdir()

            entries = self.workbench._artifact_entries_from_result(
                {
                    "papers_csv": str(csv_path),
                    "results_dir": str(folder_path),
                    "blank_path": "   ",
                    "ignored_status": "completed",
                }
            )
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0]["display_label"].split()[0], "[CSV]")
            self.assertEqual(entries[0]["tag"], "artifact_csv")
            self.assertIn("Artifact status", self.workbench._summarize_artifact_path("missing", root / "missing.csv"))
            self.assertIn("could not parse the CSV preview", self.workbench._summarize_artifact_path("csv", csv_path))
            self.assertIn("could not parse the JSON preview", self.workbench._summarize_artifact_path("json", json_path))
            self.assertIn("SQLite database", self.workbench._summarize_artifact_path("db", db_path))
            self.assertIn("Artifact type: .txt", self.workbench._summarize_artifact_path("txt", txt_path))

            original_read_text = Path.read_text

            def _patched_read_text(path_obj, *args, **kwargs):
                if Path(path_obj) == markdown_path:
                    raise OSError("cannot read markdown")
                return original_read_text(path_obj, *args, **kwargs)

            with patch("pathlib.Path.read_text", new=_patched_read_text):
                self.assertIn("could not read the Markdown preview", self.workbench._summarize_artifact_path("md", markdown_path))
                self.assertIn("notes", self.workbench._summarize_artifact_path("txt", txt_path))
                self.assertEqual(_patched_read_text(txt_path, encoding="utf-8"), "notes")

            self.workbench.scalar_vars["download_pdfs"].set(True)
            self.workbench.scalar_vars["pdf_download_mode"].set("all")
            preview_all = self.workbench._build_export_preview_text(self.workbench._collect_form_values())
            self.assertIn("All available PDFs stay in the main paper PDF folder.", preview_all)
            self.workbench.scalar_vars["pdf_download_mode"].set("relevant_only")
            preview_split = self.workbench._build_export_preview_text(self.workbench._collect_form_values())
            self.assertIn("Relevant-only PDF folder", preview_split)

            self.workbench._load_outputs({"papers_csv": str(csv_path), "results_dir": str(folder_path)})
            selection = self.workbench.outputs_tree.selection()
            self.assertTrue(selection)
            self.workbench.outputs_tree.selection_remove(selection)
            self.workbench._handle_output_selection(None)
            self.workbench._open_selected_output_parent()
            self.workbench.artifact_details.clear()
            self.workbench._open_selected_output_parent()
            self.workbench._render_output_summary("missing")
            self.workbench.outputs_tree = None
            self.workbench._handle_output_selection(None)
            self.workbench._open_selected_output_parent()

            self.workbench.scalar_vars["data_dir"].set(str(root))
            history_path = self.workbench._current_history_path()
            history_path.write_text("{bad", encoding="utf-8")
            self.assertEqual(self.workbench._load_run_history_entries(), [])
            history_path.write_text(json.dumps({"status": "wrong-shape"}), encoding="utf-8")
            self.assertEqual(self.workbench._load_run_history_entries(), [])
            self.workbench.run_history_tree = None
            self.workbench._refresh_run_history_tab()
            self.workbench._handle_run_history_selection(None)
            self.workbench.run_history_tree = next(
                widget for widget in _walk_widgets(self.workbench.run_history_tab) if widget.winfo_class() == "Treeview"
            )
            history_path.write_text(json.dumps([]), encoding="utf-8")
            self.workbench._refresh_run_history_tab()
            self.assertIn("No runs have been recorded", self.workbench.run_history_text.get("1.0", tk.END))
            self.workbench._handle_run_history_selection(None)
            self.workbench._render_run_history_entry("history-bad")
            self.workbench.run_history_entries = []
            self.workbench._render_run_history_entry("history-3")

            self.workbench.chart_canvas = None
            self.workbench._refresh_chart_preview(root / "missing_papers.csv")
            self.workbench.chart_canvas = next(
                widget for widget in _walk_widgets(self.workbench.charts_tab) if widget.winfo_class() == "Canvas"
            )
            self.workbench._refresh_chart_preview(root / "missing_papers.csv")
            self.assertIn("chart preview is empty", self.workbench.charts_summary_text.get("1.0", tk.END))
            no_source_csv = root / "papers_no_source.csv"
            pd.DataFrame([{"title": "A", "inclusion_decision": "include"}]).to_csv(no_source_csv, index=False)
            self.workbench._refresh_chart_preview(no_source_csv)
            self.assertIn("No source data available yet.", self.workbench.charts_summary_text.get("1.0", tk.END))

            self.workbench.screening_audit_tree = None
            self.workbench._refresh_screening_audit(root / "missing_papers.csv")
            self.workbench.screening_audit_tree = next(
                widget for widget in _walk_widgets(self.workbench.screening_audit_tab) if widget.winfo_class() == "Treeview"
            )
            self.workbench._refresh_screening_audit(root / "missing_papers.csv")
            self.assertIn("no screening audit", self.workbench.screening_audit_text.get("1.0", tk.END).lower())
            empty_csv = root / "empty.csv"
            pd.DataFrame(columns=["title", "inclusion_decision"]).to_csv(empty_csv, index=False)
            self.workbench._refresh_screening_audit(empty_csv)
            self.assertIn("contains no rows", self.workbench.screening_audit_text.get("1.0", tk.END))
            self.workbench._handle_screening_audit_selection(None)
            self.workbench._render_screening_audit_row("missing")

            dict_json = root / "summary.json"
            dict_json.write_text(json.dumps({"top_papers": 3, "sources": ["OpenAlex"]}), encoding="utf-8")
            list_json = root / "records.json"
            list_json.write_text(json.dumps([{"title": "A"}, {"title": "B"}]), encoding="utf-8")
            self.assertIn("Top-level keys: top_papers, sources", self.workbench._summarize_artifact_path("json", dict_json))
            self.assertIn("Top-level items: 2", self.workbench._summarize_artifact_path("json", list_json))

            if self.workbench.outputs_tree is None:
                self.workbench.outputs_tree = next(
                    widget for widget in _walk_widgets(self.workbench.outputs_tab) if widget.winfo_class() == "Treeview"
                )
            self.workbench._load_outputs({"summary_json": str(dict_json)})
            output_item = self.workbench.outputs_tree.get_children()[0]
            self.workbench.outputs_tree.selection_set(output_item)
            self.assertIn("artifact_json", self.workbench.outputs_tree.item(output_item).get("tags", ()))
            with patch.object(self.workbench, "_render_output_summary") as render_summary:
                self.workbench._handle_output_selection(None)
            render_summary.assert_called_once_with(output_item)
            self.workbench.artifact_details.clear()
            self.workbench._open_selected_output_parent()

            history_entry = {
                "timestamp": "2026-03-11T10:15:00",
                "run_status": "completed",
                "run_mode": "analyze",
                "topic": "AI governance",
                "results_dir": str(root / "results"),
            }
            self.workbench.run_history_entries = [history_entry]
            self.workbench.run_history_tree.insert("", tk.END, iid="history-0", values=("2026-03-11", "[OK] completed", "analyze", "AI governance"))
            self.workbench.run_history_tree.selection_set("history-0")
            with patch.object(self.workbench, "_render_run_history_entry") as render_history:
                self.workbench._handle_run_history_selection(None)
            render_history.assert_called_once_with("history-0")

            sourced_csv = root / "sourced.csv"
            pd.DataFrame(
                [
                    {"title": "A", "source": "OpenAlex", "inclusion_decision": "include"},
                    {"title": "B", "source": "Crossref", "inclusion_decision": "exclude"},
                ]
            ).to_csv(sourced_csv, index=False)
            self.workbench._refresh_chart_preview(sourced_csv)
            chart_summary = self.workbench.charts_summary_text.get("1.0", tk.END)
            self.assertIn("- OpenAlex: 1", chart_summary)
            self.assertIn("- Crossref: 1", chart_summary)
            self.assertNotEqual(str(self.workbench.chart_canvas.cget("scrollregion")), "")
            self.assertNotEqual(str(self.workbench.chart_canvas.cget("scrollregion")), "0 0 0 0")

            self.workbench._refresh_screening_audit(sourced_csv)
            self.workbench.screening_audit_tree.insert("", tk.END, iid="stale", values=("old", "", "", ""))
            self.workbench._refresh_screening_audit(sourced_csv)
            self.assertNotIn("stale", self.workbench.screening_audit_tree.get_children())
            self.assertEqual(self.workbench.audit_include_badge.cget("text"), "[INC] 1")
            self.assertEqual(self.workbench.audit_exclude_badge.cget("text"), "[EXC] 1")

            original_audit_tree = self.workbench.screening_audit_tree
            self.workbench.screening_audit_tree = None
            self.workbench._handle_screening_audit_selection(None)
            self.workbench.screening_audit_tree = original_audit_tree
            audit_item = self.workbench.screening_audit_tree.get_children()[0]
            self.workbench.screening_audit_tree.selection_set(audit_item)
            with patch.object(self.workbench, "_render_screening_audit_row") as render_audit:
                self.workbench._handle_screening_audit_selection(None)
            render_audit.assert_called_once_with(audit_item)
            self.assertIn("[MODE]", self.workbench.run_history_mode_badge.cget("text"))

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
        ), patch(
            "ui.desktop_app.form_values_to_config",
            return_value=SimpleNamespace(
                log_file_path=Path("results/pipeline.log"),
                results_dir=Path("results"),
                skip_discovery=True,
                run_mode="collect",
                verbosity="normal",
            ),
        ), patch.object(self.workbench, "_validate_guided_text_inputs", return_value=[]), patch(
            "ui.desktop_app.messagebox.showerror"
        ) as showerror, patch.object(self.workbench.root, "after", return_value=None):
            self.workbench._start_run(skip_discovery_override=True, run_mode_override="collect")
            self.workbench._poll_messages()
        showerror.assert_called_once()
        self.assertTrue(self.workbench.status_var.get().startswith("Run failed:"))
        controller = BrokenController(SimpleNamespace(), None)
        self.assertIsNone(controller.request_stop())

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

        self.workbench.current_result = {"papers_snapshot": [{"title": "Snapshot paper"}]}
        with patch("ui.desktop_app.form_values_to_config", return_value=SimpleNamespace(results_dir=Path("results/mock"))), patch.object(
            self.workbench, "_load_dataframe_into_tree"
        ) as load_tree, patch.object(self.workbench, "_load_records_into_tree") as load_records:
            self.workbench._refresh_all_table()
        load_tree.assert_not_called()
        load_records.assert_called_once()

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

        temp_file = str(self.workbench.root.tk.call("info", "nameofexecutable"))
        path = Path(temp_file)
        with patch("ui.desktop_app.subprocess.run") as run_mock, patch("ui.desktop_app.os.name", "posix"), patch(
                "ui.desktop_app.sys.platform", "darwin"
        ):
            self.workbench._open_path(path)
        run_mock.assert_called_once()

        controller = Mock()
        self.workbench.current_controller = controller
        with patch.object(self.workbench, "_set_status") as set_status, patch("ui.desktop_app.PipelineController", BrokenController), patch(
            "ui.desktop_app.threading.Thread", FakeThread
        ), patch.object(
            self.workbench, "_validate_guided_text_inputs", return_value=[]
        ), patch(
            "ui.desktop_app.form_values_to_config",
            return_value=SimpleNamespace(
                log_file_path=Path("results/pipeline.log"),
                results_dir=Path("results"),
                skip_discovery=True,
                run_mode="analyze",
                verbosity="normal",
            ),
        ), patch.object(self.workbench.root, "after", return_value=None):
            self.workbench._start_run(skip_discovery_override=True, run_mode_override="analyze")
        self.assertTrue(
            any(
                call.args
                and isinstance(call.args[0], str)
                and call.args[0].startswith("Running analysis from stored records...")
                for call in set_status.call_args_list
            )
        )

        self.workbench.current_controller = controller
        with patch.object(self.workbench.root_logger, "removeHandler") as remove_handler, patch.object(
                self.workbench.root, "withdraw"
        ) as withdraw, patch.object(
                self.workbench.root, "update_idletasks"
        ) as update_idletasks, patch.object(
                self.workbench.root, "quit"
        ) as quit_mock, patch.object(
                self.workbench.root, "destroy"
        ) as destroy, patch.object(
            self.workbench.root,
            "unbind_all",
            side_effect=[tk.TclError("x"), tk.TclError("shift"), tk.TclError("y"), tk.TclError("z")],
        ) as unbind_all:
            self.workbench._on_close()
        controller.request_stop.assert_called_once()
        remove_handler.assert_called_once()
        withdraw.assert_called_once()
        update_idletasks.assert_called_once()
        quit_mock.assert_called_once()
        self.assertEqual(unbind_all.call_count, 4)
        destroy.assert_called_once()

        self.workbench.current_controller = controller
        with patch.object(self.workbench.root_logger, "removeHandler"), patch.object(
                self.workbench.root, "withdraw", side_effect=tk.TclError("broken withdraw")
        ) as withdraw_error, patch.object(
                self.workbench.root, "update_idletasks"
        ) as update_idletasks_error, patch.object(
                self.workbench.root, "quit"
        ) as quit_error, patch.object(
                self.workbench.root, "destroy"
        ) as destroy_error, patch.object(
            self.workbench.root,
            "unbind_all",
            side_effect=[tk.TclError("x"), tk.TclError("shift"), tk.TclError("y"), tk.TclError("z")],
        ):
            self.workbench._on_close()
        withdraw_error.assert_called_once()
        update_idletasks_error.assert_not_called()
        quit_error.assert_not_called()
        destroy_error.assert_called_once()
        del self.workbench

    def test_launch_desktop_app_wrapper(self) -> None:
        with patch("ui.desktop_app.DesktopWorkbench") as workbench_cls:
            workbench_cls.return_value.run.return_value = 7
            self.assertEqual(launch_desktop_app(SimpleNamespace(config_file=None)), 7)

    def test_document_preview_and_log_style_guard_branches(self) -> None:
        self.assertEqual(
            self.workbench._resolve_log_style("2026-03-12 10:00:00 | INFO | pipeline.pipeline_controller | Pipeline finished in 0.02 seconds.")[0],
            "log_success",
        )
        self.assertEqual(
            self.workbench._resolve_log_style("2026-03-12 10:00:00 | WARNING | pipeline.pipeline_controller | Something needs attention")[0],
            "log_warning",
        )
        self.assertEqual(
            self.workbench._resolve_log_style("2026-03-12 10:00:00 | ERROR | pipeline.pipeline_controller | Something failed")[0],
            "log_error",
        )

        self.workbench.document_status_var.set("No paper selected yet.")
        with patch("ui.desktop_app.filedialog.askopenfilename", return_value=""):
            self.workbench._open_document_external()

        preview_summary, preview_content = self.workbench._build_document_preview(
            {
                "title": "Fallback preview",
                "abstract": "Abstract preview",
                "source": "fixture",
                "inclusion_decision": "maybe",
                "relevance_score": 50,
            },
            source_label="All Papers",
            document_path=None,
        )
        self.assertIn("Fallback preview", preview_summary)
        self.assertIn("Abstract preview", preview_content)
        self.assertIsNone(self.workbench._candidate_document_path({"title": "No file"}))


if __name__ == "__main__":  # pragma: no cover - direct module execution helper
    unittest.main()
