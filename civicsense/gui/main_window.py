"""Main application window for CivicSense.

Coordinates all pages, navigation, and application lifecycle.
Provides the primary user interface with sidebar navigation.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from civicsense.core.config import get_config
from civicsense.core.logging import get_logger
from civicsense.gui.analytics_page import AnalyticsPage
from civicsense.gui.dashboard_page import DashboardPage
from civicsense.gui.incident_page import IncidentManagerPage
from civicsense.gui.live_monitor_page import LiveMonitorPage
from civicsense.gui.settings_page import SettingsPage

logger = get_logger("app")


class NavButton(QPushButton):
    """Styled navigation button for the sidebar."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        """Initialize the navigation button.

        Args:
            text: Button label text.
            parent: Parent widget.
        """
        super().__init__(text, parent)
        self.setCheckable(True)
        self.setFixedHeight(44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #888888;
                border: none;
                border-radius: 6px;
                padding: 0 16px;
                text-align: left;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QPushButton:checked {
                background-color: #00d4aa;
                color: #1a1a1a;
                font-weight: bold;
            }
        """)


class MainWindow(QMainWindow):
    """Main application window.

    Provides sidebar navigation between Dashboard, Live Monitor,
    Incident Manager, Analytics, and Settings pages.
    """

    def __init__(self) -> None:
        """Initialize the main window with all pages and navigation."""
        super().__init__()
        self.setWindowTitle("CivicSense - AI Littering Detection")
        self.setMinimumSize(1280, 800)
        self.resize(1440, 900)

        # Workers (created on demand)
        self._camera_worker = None
        self._ai_worker = None
        self._save_worker = None
        self._camera_service = None
        self._model_manager = None
        self._incident_service = None
        self._analytics_service = None
        self._incident_count = 0
        self._prev_classification = ""

        self._setup_menubar()
        self._setup_ui()
        self._connect_signals()
        self._apply_dark_theme()
        self._init_services()

    def _setup_menubar(self) -> None:
        """Configure the application menu bar."""
        menubar = self.menuBar()
        if menubar is None:
            return
        menubar.setStyleSheet("""
            QMenuBar {
                background-color: #1a1a1a;
                color: #ffffff;
                border-bottom: 1px solid #333333;
            }
            QMenuBar::item:selected { background-color: #2b2b2b; }
        """)

        file_menu = menubar.addMenu("File")
        if file_menu:
            exit_action = QAction("Exit", self)
            exit_action.setShortcut("Ctrl+Q")
            exit_action.triggered.connect(self.close)
            file_menu.addAction(exit_action)

        view_menu = menubar.addMenu("View")
        if view_menu:
            dashboard_action = QAction("Dashboard", self)
            dashboard_action.triggered.connect(lambda: self._navigate(0))
            view_menu.addAction(dashboard_action)

            monitor_action = QAction("Live Monitor", self)
            monitor_action.triggered.connect(lambda: self._navigate(1))
            view_menu.addAction(monitor_action)

        help_menu = menubar.addMenu("Help")
        if help_menu:
            about_action = QAction("About", self)
            about_action.triggered.connect(self._show_about)
            help_menu.addAction(about_action)

    def _setup_ui(self) -> None:
        """Build the main window layout with sidebar and content area."""
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._nav_buttons: list[NavButton] = []
        self._pages = QStackedWidget()
        self._pages.setStyleSheet("background-color: #1e1e1e;")

        self._dashboard_page = DashboardPage()
        self._live_monitor_page = LiveMonitorPage()
        self._incident_page = IncidentManagerPage()
        self._analytics_page = AnalyticsPage()
        self._settings_page = SettingsPage()

        self._pages.addWidget(self._dashboard_page)
        self._pages.addWidget(self._live_monitor_page)
        self._pages.addWidget(self._incident_page)
        self._pages.addWidget(self._analytics_page)
        self._pages.addWidget(self._settings_page)

        sidebar = self._create_sidebar()
        main_layout.addWidget(sidebar)

        main_layout.addWidget(self._pages, stretch=1)

    def _connect_signals(self) -> None:
        """Connect page signals to handlers."""
        self._settings_page.settings_saved.connect(self._on_settings_saved)
        self._live_monitor_page.camera_toggle_requested.connect(self._on_camera_toggle)
        self._incident_page.search_requested.connect(self._apply_incident_filters)
        self._incident_page.status_filter_changed.connect(self._apply_incident_filters)
        self._incident_page.approve_requested.connect(self._on_incident_approve)
        self._incident_page.reject_requested.connect(self._on_incident_reject)
        self._incident_page.export_csv_requested.connect(self._on_export_csv)
        self._incident_page.export_json_requested.connect(self._on_export_json)
        self._analytics_page.generate_report_requested.connect(self._on_generate_report)

    def _init_services(self) -> None:
        """Initialize shared services and populate camera list."""
        from civicsense.database.engine import init_database
        from civicsense.services.analytics_service import AnalyticsService
        from civicsense.services.camera_service import CameraService
        from civicsense.services.incident_service import IncidentService

        self._camera_service = CameraService()
        cameras = CameraService.enumerate_cameras()
        self._live_monitor_page.populate_cameras(cameras)

        try:
            init_database()
            self._incident_service = IncidentService()
            self._analytics_service = AnalyticsService()
            self._dashboard_page.update_status(
                cameras_active=False,
                ai_loaded=False,
                gpu_available=False,
                db_connected=True,
            )
            self._refresh_dashboard()
            self._refresh_analytics()
            self._apply_incident_filters()
        except Exception as e:
            logger.error(f"Service init failed: {e}", module="app")

    def _create_sidebar(self) -> QWidget:
        """Create the navigation sidebar.

        Returns:
            The configured sidebar widget.
        """
        sidebar = QWidget()
        sidebar.setFixedWidth(220)
        sidebar.setStyleSheet("""
            QWidget {
                background-color: #1a1a1a;
                border-right: 1px solid #333333;
            }
        """)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 16, 12, 16)
        layout.setSpacing(4)

        logo = QLabel("CivicSense")
        logo.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #00d4aa; padding: 8px 0 16px 0;"
        )
        layout.addWidget(logo)

        pages = [
            ("Dashboard", 0),
            ("Live Monitor", 1),
            ("Incidents", 2),
            ("Analytics", 3),
            ("Settings", 4),
        ]

        for name, idx in pages:
            btn = NavButton(name)
            btn.clicked.connect(lambda checked, i=idx: self._navigate(i))
            layout.addWidget(btn)
            self._nav_buttons.append(btn)

        layout.addStretch()

        version = QLabel("v0.1.0")
        version.setStyleSheet("color: #555555; font-size: 11px;")
        layout.addWidget(version)

        self._navigate(0)
        return sidebar

    def _navigate(self, page_index: int) -> None:
        """Navigate to a page by index.

        Args:
            page_index: The page index to display.
        """
        self._pages.setCurrentIndex(page_index)
        for i, btn in enumerate(self._nav_buttons):
            btn.setChecked(i == page_index)

    def _on_settings_saved(self, settings: dict) -> None:
        """Apply saved settings to the config singleton.

        Args:
            settings: Dictionary of setting key-value pairs.
        """
        config = get_config()

        # Apply AI settings
        ai_keys = (
            "detection_model",
            "pose_model",
            "confidence_threshold",
            "auto_confirm_threshold",
            "device",
            "image_size",
        )
        for key in ai_keys:
            full_key = f"ai.{key}"
            if full_key in settings:
                setattr(config.ai, key, settings[full_key])

        # Apply camera settings
        for key in ("source", "fps"):
            full_key = f"camera.{key}"
            if full_key in settings:
                setattr(config.camera, key, settings[full_key])

        # Apply storage settings
        from pathlib import Path

        for key in ("evidence_dir", "snapshots_dir", "clips_dir", "exports_dir"):
            full_key = f"storage.{key}"
            if full_key in settings:
                setattr(config.storage, key, Path(settings[full_key]))

        # Apply database settings
        if "database.url" in settings:
            config.database.url = settings["database.url"]

        # Apply theme
        if "theme" in settings:
            from civicsense.core.config import ThemeMode

            try:
                config.theme = ThemeMode(settings["theme"])
            except ValueError:
                logger.warning(f"Unknown theme value: {settings['theme']}", module="app")

        logger.info("Settings applied to config", module="app")
        self.statusBar().showMessage("Settings saved", 3000)

    def _on_camera_toggle(self) -> None:
        """Toggle camera on/off."""
        if self._camera_worker is not None:
            self._stop_camera()
        else:
            self._start_camera()

    def _start_camera(self) -> None:
        """Start camera capture and AI processing."""
        config = get_config()
        self._prev_classification = ""
        source = self._live_monitor_page.get_selected_camera_index()

        if source < 0:
            url_text = self._live_monitor_page.get_stream_url()
            if not url_text:
                self._show_error(
                    "No Camera Selected",
                    "Please select a camera or enter a stream URL first.",
                )
                return
            source = url_text

        if self._camera_service is None:
            self._show_error("Camera Error", "Camera service not initialized.")
            return

        self._live_monitor_page.set_loading(True, "Opening camera...")

        try:
            from civicsense.ai.model_manager import ModelManager
            from civicsense.gui.workers.ai_worker import AIWorker
            from civicsense.gui.workers.camera_worker import CameraWorker

            camera_id = "live_monitor"
            self._camera_service.open(camera_id, source)
            self._live_monitor_page.add_alert(f"Camera opened: {source}")

            self._live_monitor_page.set_loading(True, "Loading AI models...")

            self._camera_worker = CameraWorker(self._camera_service, camera_id)
            self._camera_worker.frame_captured.connect(self._on_frame_captured)
            self._camera_worker.error_occurred.connect(self._on_worker_error)
            self._camera_worker.fps_updated.connect(
                lambda fps: self._live_monitor_page.update_stats(fps=fps)
            )

            self._model_manager = ModelManager()
            try:
                self._model_manager.load_models()
                self._ai_worker = AIWorker(self._model_manager)
                self._ai_worker.result_ready.connect(self._on_ai_result)
                self._ai_worker.error_occurred.connect(self._on_worker_error)
                self._ai_worker.start()
                device = config.ai.device
                self._live_monitor_page.update_stats(device=device.upper())
                self._live_monitor_page.add_alert("AI models loaded")
            except Exception as e:
                self._show_error("AI Model Error", f"Failed to load AI models:\n{e}")
                logger.error(f"Model load failed: {e}", module="app")

            self._camera_worker.start()
            self._live_monitor_page.set_camera_active(True)
            self._live_monitor_page.add_alert("Camera active")
            self.statusBar().showMessage("Camera active", 5000)

            self._dashboard_page.update_status(
                cameras_active=True,
                ai_loaded=self._model_manager is not None,
                gpu_available=config.ai.device != "cpu",
                db_connected=True,
            )

        except Exception as e:
            self._live_monitor_page.set_loading(False)
            self._show_error("Camera Error", f"Failed to start camera:\n{e}")
            logger.error(f"Camera start failed: {e}", module="app")

    def _stop_camera(self) -> None:
        """Stop camera capture and AI processing."""
        if self._camera_worker is not None:
            self._camera_worker.stop()
            self._camera_worker = None

        if self._ai_worker is not None:
            self._ai_worker.stop()
            self._ai_worker = None

        if self._camera_service is not None:
            self._camera_service.release_all()

        self._live_monitor_page.set_camera_active(False)
        self._live_monitor_page.add_alert("Camera stopped")
        self.statusBar().showMessage("Camera stopped", 5000)

        self._dashboard_page.update_status(
            cameras_active=False,
            ai_loaded=False,
            gpu_available=False,
            db_connected=True,
        )
        self._refresh_dashboard()
        self._refresh_analytics()
        self._apply_incident_filters()

    def _on_frame_captured(self, frame) -> None:
        """Handle a new camera frame.

        Args:
            frame: BGR numpy array from camera.
        """
        if self._ai_worker is None:
            # No AI pipeline running (e.g. model load failed) — show raw feed.
            self._live_monitor_page.update_frame(frame)
            return

        # Queue frame for AI processing; the annotated frame is displayed
        # once the corresponding result comes back in _on_ai_result.
        self._ai_worker.set_frame(frame)

    def _on_ai_result(self, result) -> None:
        """Handle AI inference result: update overlays, stats, and events.

        Args:
            result: InferenceResult from InferenceWorker.
        """
        from civicsense.ai.inference_worker import InferenceResult
        from civicsense.cli.classifier import annotate_frame

        if not isinstance(result, InferenceResult):
            return

        fr = result.frame_result

        self._live_monitor_page.update_stats(
            persons=len(fr.persons),
            waste=fr.waste_count,
            dustbins=len(fr.dustbins),
        )

        annotated = annotate_frame(result.frame, fr)
        self._live_monitor_page.update_frame(annotated)

        self._handle_classification_event(fr, result.frame)

    def _handle_classification_event(self, fr, frame) -> None:
        """Log a new incident whenever the frame classification changes.

        Every distinct classification the AI reaches (VALID, FLAGGED,
        GROUND LITTER, INCONCLUSIVE, etc.) is recorded — not just confirmed
        littering — so the Incident Manager shows the full activity history.
        Only state *transitions* are recorded to avoid flooding the database
        at video frame rate.

        Args:
            fr: FrameResult from civicsense.cli.classifier.classify_frame.
            frame: The source video frame (for dimensions).
        """
        from civicsense.dto.detection import IncidentDTO, IncidentStatus

        if self._incident_service is None:
            return
        if fr.classification == self._prev_classification:
            return
        self._prev_classification = fr.classification

        if fr.waste_objects:
            waste_type = fr.waste_objects[0].class_name
            confidence = max(w.confidence for w in fr.waste_objects)
        elif fr.ground_objects:
            waste_type = fr.ground_objects[0].class_name
            confidence = max(g.confidence for g in fr.ground_objects)
        else:
            waste_type = ""
            confidence = 0.0

        # A FLAGGED event with high enough detection confidence is treated
        # as confirmed automatically rather than waiting for manual review.
        is_flagged = "FLAGGED" in fr.classification
        auto_confirmed = (
            is_flagged and confidence >= get_config().ai.auto_confirm_threshold
        )
        status = IncidentStatus.APPROVED if auto_confirmed else IncidentStatus.PENDING

        self._incident_count += 1
        dto = IncidentDTO(
            camera_id="live_monitor",
            camera_name="Live Camera",
            confidence=confidence,
            person_track_id=0,
            waste_type=waste_type,
            classification=fr.classification,
            details=fr.details,
            frame_width=frame.shape[1],
            frame_height=frame.shape[0],
            status=status,
            review_notes="Auto-confirmed: confidence above threshold"
            if auto_confirmed
            else "",
        )
        try:
            created = self._incident_service.create_incident(dto)
            if is_flagged:
                suffix = " [AUTO-CONFIRMED]" if auto_confirmed else ""
                self._show_alert(f"{fr.classification}: {fr.details}{suffix}")
            self._refresh_dashboard()
            self._refresh_analytics()
            self._apply_incident_filters()
            logger.info(
                f"Event logged: id={created.id}, classification={fr.classification}, "
                f"confidence={confidence:.2f}, auto_confirmed={auto_confirmed}",
                module="app",
            )
        except Exception as e:
            logger.error(f"Failed to create incident: {e}", module="app")

    def _refresh_dashboard(self) -> None:
        """Refresh dashboard stats from incident service."""
        if self._incident_service is None:
            return
        try:
            total = self._incident_service.get_total_count()
            today = self._incident_service.get_today_count()
            self._dashboard_page.update_stats(
                total=total,
                today=today,
            )
        except Exception as e:
            logger.error(f"Dashboard refresh failed: {e}", module="app")

    def _refresh_analytics(self) -> None:
        """Refresh analytics charts from analytics service."""
        if self._analytics_service is None:
            return
        try:
            trend = self._analytics_service.get_trend_data(days=30)
            self._analytics_page.update_trend(trend)

            waste_dist = self._analytics_service.get_waste_type_statistics()
            self._analytics_page.update_waste_distribution(waste_dist)

            camera_stats = self._analytics_service.get_camera_statistics()
            self._analytics_page.update_camera_stats(camera_stats)
        except Exception as e:
            logger.error(f"Analytics refresh failed: {e}", module="app")

    def _apply_incident_filters(self, *_args: object) -> None:
        """Refresh the incident table using the current status filter and search text.

        Reads the current filter/search state directly from the incident
        page, so this can be called after any data change (new event,
        approve/reject, camera stop) without losing whatever view the user
        currently has selected.
        """
        from civicsense.dto.detection import IncidentStatus

        if self._incident_service is None:
            return
        try:
            status = self._incident_page.get_status_filter()
            if status and status != "all":
                incidents = self._incident_service.get_by_status(
                    IncidentStatus(status), limit=200
                )
            else:
                incidents = self._incident_service.get_incidents(limit=200)

            query = self._incident_page.get_search_query().strip().lower()
            if query:
                incidents = [
                    inc
                    for inc in incidents
                    if query in inc.waste_type.lower()
                    or query in inc.camera_name.lower()
                    or query in inc.classification.lower()
                ]

            self._incident_page.populate_incidents([inc.to_dict() for inc in incidents])
        except Exception as e:
            logger.error(f"Incident filter refresh failed: {e}", module="app")
            self._show_error("Filter Error", f"Failed to filter incidents:\n{e}")

    def _on_incident_approve(self, incident_id: int, notes: str) -> None:
        """Approve an incident by id.

        Args:
            incident_id: The incident to approve.
            notes: Optional reviewer notes entered in the confirmation dialog.
        """
        self._review_incident(incident_id, approve=True, notes=notes)

    def _on_incident_reject(self, incident_id: int, notes: str) -> None:
        """Reject an incident by id.

        Args:
            incident_id: The incident to reject.
            notes: Optional reviewer notes entered in the confirmation dialog.
        """
        self._review_incident(incident_id, approve=False, notes=notes)

    def _review_incident(self, incident_id: int, approve: bool, notes: str = "") -> None:
        """Update an incident's review status and refresh dependent views.

        Args:
            incident_id: The incident to review.
            approve: True to approve, False to reject.
            notes: Optional reviewer notes to store alongside the decision.
        """
        if self._incident_service is None or incident_id is None:
            return
        try:
            if approve:
                self._incident_service.approve_incident(incident_id, notes)
            else:
                self._incident_service.reject_incident(incident_id, notes)
            self._apply_incident_filters()
            self._refresh_dashboard()
            self._refresh_analytics()
            self.statusBar().showMessage(
                f"Incident #{incident_id} {'approved' if approve else 'rejected'}",
                3000,
            )
        except Exception as e:
            logger.error(f"Incident review failed: {e}", module="app")
            self._show_error("Review Error", f"Failed to update incident:\n{e}")

    def _on_export_csv(self) -> None:
        """Export all incidents to a CSV file."""
        self._export_incidents("csv")

    def _on_export_json(self) -> None:
        """Export all incidents to a JSON file."""
        self._export_incidents("json")

    def _export_incidents(self, fmt: str) -> None:
        """Export incidents to the given format using the export service.

        Args:
            fmt: Export format, either "csv" or "json".
        """
        try:
            from civicsense.services.export_service import ExportService

            export_service = ExportService()
            path = (
                export_service.export_csv()
                if fmt == "csv"
                else export_service.export_json()
            )
            self.statusBar().showMessage(f"Exported to {path}", 5000)
            QMessageBox.information(
                self, "Export Complete", f"Incidents exported to:\n{path}"
            )
        except Exception as e:
            logger.error(f"Export failed: {e}", module="app")
            self._show_error("Export Error", f"Failed to export {fmt.upper()}:\n{e}")

    def _on_generate_report(self, period: str) -> None:
        """Generate and display an analytics report for the given period.

        Args:
            period: One of "daily", "weekly", or "monthly".
        """
        if self._analytics_service is None:
            return
        try:
            if period == "daily":
                report = self._analytics_service.compute_daily()
            elif period == "weekly":
                report = self._analytics_service.compute_weekly()
            elif period == "monthly":
                report = self._analytics_service.compute_monthly()
            else:
                return
            self._analytics_page.display_report(report)
        except Exception as e:
            logger.error(f"Report generation failed: {e}", module="app")
            self._show_error("Report Error", f"Failed to generate report:\n{e}")

    def _on_worker_error(self, message: str) -> None:
        """Handle error from any worker thread.

        Args:
            message: Error description string.
        """
        self._show_alert(f"ERROR: {message}")
        logger.error(f"Worker error: {message}", module="app")

    def _show_error(self, title: str, message: str) -> None:
        """Display an error dialog to the user.

        Args:
            title: Dialog title.
            message: Error description.
        """
        QMessageBox.critical(self, title, message)

    def _show_alert(self, message: str) -> None:
        """Add an alert to the live monitor page.

        Args:
            message: Alert text.
        """
        self._live_monitor_page.add_alert(message)

    def _show_about(self) -> None:
        """Show the About dialog."""
        QMessageBox.about(
            self,
            "About CivicSense",
            "CivicSense - AI-Powered Littering Detection\n"
            "Version 0.1.0\n\n"
            "Detects littering events in real-time using\n"
            "YOLO26 object detection and pose estimation.",
        )

    def _apply_dark_theme(self) -> None:
        """Apply the dark theme stylesheet to the application."""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e1e;
            }
            QToolTip {
                background-color: #2b2b2b;
                color: #ffffff;
                border: 1px solid #444444;
                padding: 4px;
                border-radius: 4px;
            }
            QScrollBar:vertical {
                background-color: #1a1a1a;
                width: 10px;
                border: none;
                margin: 2px;
            }
            QScrollBar::handle:vertical {
                background-color: #444444;
                border-radius: 5px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #555555;
            }
            QScrollBar::handle:vertical:pressed {
                background-color: #00d4aa;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
            QStatusBar {
                background-color: #1a1a1a;
                color: #888888;
                border-top: 1px solid #333333;
            }
            QComboBox QAbstractItemView {
                background-color: #2b2b2b;
                color: #ffffff;
                selection-background-color: #00d4aa;
                selection-color: #1a1a1a;
                border: 1px solid #444444;
            }
        """)
        self.statusBar().showMessage("Ready")

    @property
    def dashboard(self) -> DashboardPage:
        """Return the dashboard page instance."""
        return self._dashboard_page

    @property
    def live_monitor(self) -> LiveMonitorPage:
        """Return the live monitor page instance."""
        return self._live_monitor_page

    @property
    def incidents(self) -> IncidentManagerPage:
        """Return the incident manager page instance."""
        return self._incident_page

    @property
    def analytics(self) -> AnalyticsPage:
        """Return the analytics page instance."""
        return self._analytics_page

    @property
    def settings(self) -> SettingsPage:
        """Return the settings page instance."""
        return self._settings_page

    def closeEvent(self, event: QCloseEvent) -> None:
        """Clean up threads on window close."""
        if self._camera_worker is not None:
            self._camera_worker.stop()
            self._camera_worker = None
        if self._ai_worker is not None:
            self._ai_worker.stop()
            self._ai_worker = None
        if self._camera_service is not None:
            self._camera_service.release_all()
        event.accept()
