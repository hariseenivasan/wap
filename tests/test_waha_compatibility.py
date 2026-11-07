"""
WAP - WAHA API Compatibility Test Suite
Adapted from WAHA (WhatsApp HTTP API) e2e test suite (https://github.com/devlikeapro/waha)
Licensed under Apache License 2.0 (http://www.apache.org/licenses/LICENSE-2.0)

Copyright (c) 2026 devlikeapro / WAP Contributors
"""

import pytest
import requests

WAP_BASE_URL = "http://127.0.0.1:3001"

class TestWahaApiCompatibility:
    """Tests WAP's conformance to the WAHA REST API specification."""

    def test_status_endpoint_returns_working_or_scan_qr(self):
        """WAHA GET /api/status or /api/sessions/default health check."""
        resp = requests.get(f"{WAP_BASE_URL}/api/status", timeout=5)
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert data["status"] in ["STARTING", "SCAN_QR_CODE", "WORKING", "STOPPED"]
        assert "engine" in data
        assert data["engine"] == "playwright"
        assert "authenticated" in data
        assert isinstance(data["authenticated"], bool)

    def test_qr_endpoint_image_format(self):
        """WAHA GET /api/qr returns valid image/png."""
        resp = requests.get(f"{WAP_BASE_URL}/api/qr?format=image", timeout=10)
        assert resp.status_code in [200, 400]
        if resp.status_code == 200:
            assert resp.headers.get("content-type") == "image/png"
            assert len(resp.content) > 0

    def test_qr_endpoint_json_format(self):
        """WAHA GET /api/qr?format=json returns base64 data URI."""
        resp = requests.get(f"{WAP_BASE_URL}/api/qr?format=json", timeout=10)
        assert resp.status_code in [200, 400]
        if resp.status_code == 200:
            data = resp.json()
            assert "qr" in data
            assert data["qr"].startswith("data:image/png;base64,")

    def test_screenshot_endpoint(self):
        """WAHA GET /api/screenshot returns valid viewport PNG."""
        resp = requests.get(f"{WAP_BASE_URL}/api/screenshot", timeout=10)
        assert resp.status_code == 200
        assert resp.headers.get("content-type") == "image/png"
        assert len(resp.content) > 100

    def test_send_text_validation_empty_body(self):
        """WAHA POST /api/sendText returns 422 Unprocessable Entity on empty body."""
        resp = requests.post(f"{WAP_BASE_URL}/api/sendText", json={}, timeout=5)
        assert resp.status_code == 422

    def test_send_text_validation_missing_text(self):
        """WAHA POST /api/sendText returns 422 if text is missing."""
        resp = requests.post(f"{WAP_BASE_URL}/api/sendText", json={"chatId": "1234567890@c.us"}, timeout=5)
        assert resp.status_code == 422

    def test_chats_list_structure(self):
        """WAHA GET /api/chats returns a list of chat summaries."""
        resp = requests.get(f"{WAP_BASE_URL}/api/chats?limit=5", timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_call_logs_endpoint_wap_extension(self):
        """WAP-exclusive GET /api/calls endpoint structure."""
        resp = requests.get(f"{WAP_BASE_URL}/api/calls?limit=5&includeDetails=false", timeout=15)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_maintenance_auto_clean_media_validation(self):
        """WAP-exclusive POST /api/maintenance/auto-clean-media validation."""
        resp = requests.post(f"{WAP_BASE_URL}/api/maintenance/auto-clean-media", json={}, timeout=5)
        assert resp.status_code == 422
